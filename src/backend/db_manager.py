"""
db_manager.py - Gestor de Base de Datos SQLite
RPK Producción - Arquitectura Persistente

Este módulo implementa:
- Conexión y gestión de SQLite local
- Esquema de tablas replicando estructura Excel
- Operaciones CRUD atómicas
- Metadatos de sincronización
"""

import sqlite3
import os
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
from contextlib import contextmanager

import pandas as pd

# ============================================
# CONFIGURACIÓN
# ============================================

# Ruta a la base de datos (relativa al directorio del proyecto)
DB_PATH = Path(__file__).parent.parent.parent / "data" / "rpk_production.db"

# Timeout para conexiones (segundos)
CONNECTION_TIMEOUT = 30

# ============================================
# CONEXIÓN Y GESTIÓN
# ============================================

@contextmanager
def get_connection():
    """
    Context manager para obtener conexión a SQLite.
    Usa WAL mode para mejor concurrencia.
    """
    # Asegurar que existe el directorio
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=CONNECTION_TIMEOUT,
        check_same_thread=False
    )
    
    # Configurar para mejor rendimiento
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    conn.execute("PRAGMA foreign_keys=ON")
    
    conn.row_factory = sqlite3.Row
    
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_database() -> None:
    """
    Inicializa la base de datos creando todas las tablas si no existen.
    """
    print(f"[DB] Inicializando base de datos en: {DB_PATH}")
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Tabla: pedidos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                articulo TEXT NOT NULL,
                pedido TEXT,
                cantidad REAL DEFAULT 0,
                pedidas REAL DEFAULT 0,
                servidas REAL DEFAULT 0,
                fecha_entrega TEXT,
                cliente TEXT,
                prioridad INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(articulo, pedido)
            )
        """)
        
        # Tabla: rutas_ops
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rutas_ops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                articulo TEXT NOT NULL,
                centro TEXT,
                fase INTEGER DEFAULT 0,
                t_prep REAL DEFAULT 0,
                prod_horaria REAL DEFAULT 0,
                horas_por_ud REAL DEFAULT 0,
                uatc TEXT,
                subuatc TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(articulo, fase)
            )
        """)
        
        # Tabla: stock
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                articulo TEXT NOT NULL UNIQUE,
                stock REAL DEFAULT 0,
                ubicacion TEXT,
                lote TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla: wip (Work In Progress)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wip (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                articulo TEXT NOT NULL,
                of TEXT,
                fase INTEGER DEFAULT 0,
                centro TEXT,
                cantidad_disponible REAL DEFAULT 0,
                cantidad_total REAL DEFAULT 0,
                estado TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(articulo, of, fase)
            )
        """)
        
        # Tabla: puntos_lotes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS puntos_lotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                articulo TEXT NOT NULL UNIQUE,
                punto_pedido REAL DEFAULT 0,
                lote_produccion REAL DEFAULT 0,
                mp TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla: capacidad_centros
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capacidad_centros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                centro TEXT NOT NULL UNIQUE,
                capacidad_horas REAL DEFAULT 8,
                turnos INTEGER DEFAULT 1,
                eficiencia REAL DEFAULT 1.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla: sync_metadata (para tracking de sincronización)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL UNIQUE,
                source_file TEXT,
                last_sync_at TEXT,
                row_count INTEGER DEFAULT 0,
                checksum TEXT,
                sync_duration_ms INTEGER DEFAULT 0
            )
        """)
        
        # Crear índices para mejorar rendimiento de queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_articulo ON pedidos(articulo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_fecha ON pedidos(fecha_entrega)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rutas_articulo ON rutas_ops(articulo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rutas_centro ON rutas_ops(centro)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_articulo ON stock(articulo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wip_articulo ON wip(articulo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wip_centro ON wip(centro)")
        
        conn.commit()
        print("[DB] Tablas e índices creados correctamente")


# ============================================
# OPERACIONES DE SINCRONIZACIÓN ATÓMICA
# ============================================

def _calculate_checksum(df: pd.DataFrame) -> str:
    """Calcula checksum MD5 de un DataFrame para detectar cambios."""
    if df.empty:
        return "empty"
    return hashlib.md5(pd.util.hash_pandas_object(df).values.tobytes()).hexdigest()


def sync_table_atomic(table_name: str, df: pd.DataFrame, source_file: str = "") -> Dict[str, Any]:
    """
    Sincroniza una tabla de forma atómica (TRUNCATE + INSERT en una transacción).
    
    Args:
        table_name: Nombre de la tabla destino
        df: DataFrame con los datos a insertar
        source_file: Nombre del archivo fuente (para metadatos)
    
    Returns:
        Dict con estadísticas de la sincronización
    """
    start_time = datetime.now()
    
    if df.empty:
        print(f"[DB] Tabla {table_name}: DataFrame vacío, saltando sincronización")
        return {"table": table_name, "rows": 0, "status": "skipped"}
    
    # Calcular checksum para detectar si hay cambios
    new_checksum = _calculate_checksum(df)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Verificar si necesitamos sincronizar (comparar checksum)
        cursor.execute(
            "SELECT checksum FROM sync_metadata WHERE table_name = ?",
            (table_name,)
        )
        row = cursor.fetchone()
        if row and row["checksum"] == new_checksum:
            print(f"[DB] Tabla {table_name}: Sin cambios (checksum igual)")
            return {"table": table_name, "rows": len(df), "status": "unchanged"}
        
        # TRUNCATE (DELETE all)
        cursor.execute(f"DELETE FROM {table_name}")
        
        # Preparar columnas que existen en la tabla
        cursor.execute(f"PRAGMA table_info({table_name})")
        table_columns = {row["name"] for row in cursor.fetchall()}
        
        # Filtrar columnas del DataFrame que existen en la tabla
        df_columns = [col for col in df.columns if col in table_columns]
        
        if not df_columns:
            print(f"[DB] Tabla {table_name}: No hay columnas coincidentes")
            return {"table": table_name, "rows": 0, "status": "no_matching_columns"}
        
        # INSERT masivo
        placeholders = ", ".join(["?" for _ in df_columns])
        columns_str = ", ".join(df_columns)
        insert_sql = f"INSERT OR REPLACE INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        
        # Convertir DataFrame a lista de tuplas
        data = df[df_columns].values.tolist()
        cursor.executemany(insert_sql, data)
        
        # Calcular duración
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Actualizar metadatos de sincronización
        cursor.execute("""
            INSERT OR REPLACE INTO sync_metadata 
            (table_name, source_file, last_sync_at, row_count, checksum, sync_duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            table_name,
            source_file,
            datetime.now().isoformat(),
            len(df),
            new_checksum,
            duration_ms
        ))
        
        conn.commit()
        
        print(f"[DB] Tabla {table_name}: {len(df)} filas sincronizadas en {duration_ms}ms")
        
        return {
            "table": table_name,
            "rows": len(df),
            "status": "synced",
            "duration_ms": duration_ms,
            "checksum": new_checksum
        }


# ============================================
# OPERACIONES DE LECTURA
# ============================================

def read_table(table_name: str) -> pd.DataFrame:
    """
    Lee una tabla completa y retorna como DataFrame.
    
    Args:
        table_name: Nombre de la tabla a leer
    
    Returns:
        DataFrame con los datos de la tabla
    """
    valid_tables = ["pedidos", "rutas_ops", "stock", "wip", "puntos_lotes", "capacidad_centros"]
    
    if table_name not in valid_tables:
        print(f"[DB] Tabla inválida: {table_name}")
        return pd.DataFrame()
    
    try:
        with get_connection() as conn:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            return df
    except Exception as e:
        print(f"[DB] Error leyendo tabla {table_name}: {e}")
        return pd.DataFrame()


def is_database_populated(table_name: str = None) -> bool:
    """
    Verifica si la base de datos tiene datos.
    
    Args:
        table_name: Si se especifica, verifica solo esa tabla.
                   Si es None, verifica que al menos una tabla tenga datos.
    
    Returns:
        True si hay datos, False si está vacía
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            if table_name:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
                result = cursor.fetchone()
                return result["cnt"] > 0
            else:
                # Verificar al menos pedidos o rutas_ops
                for table in ["pedidos", "rutas_ops"]:
                    cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    result = cursor.fetchone()
                    if result["cnt"] > 0:
                        return True
                return False
    except Exception as e:
        print(f"[DB] Error verificando población: {e}")
        return False


def get_sync_status() -> Dict[str, Any]:
    """
    Obtiene el estado de sincronización de todas las tablas.
    
    Returns:
        Dict con información de sincronización por tabla
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_name, source_file, last_sync_at, row_count, checksum, sync_duration_ms
                FROM sync_metadata
                ORDER BY last_sync_at DESC
            """)
            rows = cursor.fetchall()
            
            return {
                "database_path": str(DB_PATH),
                "database_exists": DB_PATH.exists(),
                "tables": [
                    {
                        "name": row["table_name"],
                        "source": row["source_file"],
                        "last_sync": row["last_sync_at"],
                        "rows": row["row_count"],
                        "duration_ms": row["sync_duration_ms"]
                    }
                    for row in rows
                ]
            }
    except Exception as e:
        return {
            "database_path": str(DB_PATH),
            "database_exists": DB_PATH.exists(),
            "error": str(e),
            "tables": []
        }


def get_table_count(table_name: str) -> int:
    """Obtiene el conteo de filas de una tabla."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
            result = cursor.fetchone()
            return result["cnt"]
    except Exception:
        return 0


# ============================================
# UTILIDADES
# ============================================

def drop_all_tables() -> None:
    """Elimina todas las tablas (para testing/reset)."""
    tables = ["pedidos", "rutas_ops", "stock", "wip", "puntos_lotes", "capacidad_centros", "sync_metadata"]
    
    with get_connection() as conn:
        cursor = conn.cursor()
        for table in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        print("[DB] Todas las tablas eliminadas")


def vacuum_database() -> None:
    """Compacta la base de datos para recuperar espacio."""
    with get_connection() as conn:
        conn.execute("VACUUM")
        print("[DB] Base de datos compactada")


# ============================================
# INICIALIZACIÓN AL IMPORTAR
# ============================================

# Crear directorio si no existe
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
