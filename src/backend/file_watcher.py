"""
file_watcher.py - Sistema de Monitoreo de Archivos Excel
RPK Producción - Sincronización Automática

Este módulo implementa:
- Monitoreo de carpeta ./data/inputs/ con watchdog
- Sincronización automática Excel -> SQLite al detectar cambios
- Debouncing para evitar sincronizaciones múltiples
- Sync inicial de archivos existentes
"""

import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

import pandas as pd

# Imports locales
from db_manager import (
    init_database,
    sync_table_atomic,
    get_sync_status
)

# ============================================
# CONFIGURACIÓN
# ============================================

# Extensiones de archivo a monitorear
WATCHED_EXTENSIONS = {".xlsx", ".xls"}

# Tiempo de debounce en segundos (evita múltiples syncs por el mismo archivo)
DEBOUNCE_SECONDS = 2.0

# Lock para sincronización thread-safe
_sync_lock = threading.Lock()

# Diccionario para debouncing: {filepath: last_event_time}
_last_events: Dict[str, float] = {}


# ============================================
# PARSEADORES DE EXCEL (Reutilizados de data_loader)
# ============================================

def _find_sheet(sheet_names: list, possible_names: list) -> Optional[str]:
    """Busca una hoja por nombres posibles (case-insensitive)."""
    for name in possible_names:
        for sheet in sheet_names:
            if name.lower() == sheet.lower():
                return sheet
    return None


def _normalize_columns(df: pd.DataFrame, column_map: Dict[str, str]) -> pd.DataFrame:
    """Normaliza nombres de columnas según mapeo."""
    return df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})


def parse_excel_to_dataframes(file_path: str) -> Dict[str, pd.DataFrame]:
    """
    Parsea un archivo Excel y extrae DataFrames para cada tabla.
    
    Args:
        file_path: Ruta al archivo Excel
    
    Returns:
        Dict con nombre_tabla -> DataFrame
    """
    result = {}
    
    try:
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names
        print(f"[WATCHER] Parseando {Path(file_path).name}: {len(sheet_names)} hojas")
        
        # 1. Pedidos
        sheet = _find_sheet(sheet_names, ["Pedidos", "pedidos", "PEDIDOS"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            df = _normalize_columns(df, {
                "Artículo": "articulo", "Articulo": "articulo", "ARTICULO": "articulo",
                "Pedido": "pedido", "PEDIDO": "pedido",
                "Cantidad": "cantidad", "CANTIDAD": "cantidad",
                "Pedidas": "pedidas", "Servidas": "servidas",
                "Fecha Entrega": "fecha_entrega", "FechaEntrega": "fecha_entrega",
                "Cliente": "cliente", "CLIENTE": "cliente"
            })
            if "fecha_entrega" in df.columns:
                df["fecha_entrega"] = pd.to_datetime(df["fecha_entrega"], errors="coerce")
                df["fecha_entrega"] = df["fecha_entrega"].dt.strftime('%Y-%m-%d')
            result["pedidos"] = df
        
        # 2. RutasOps
        sheet = _find_sheet(sheet_names, ["RutasOps", "rutasops", "RUTASOPS", "Rutas"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            df = _normalize_columns(df, {
                "Artículo": "articulo", "Articulo": "articulo",
                "Centro": "centro", "CENTRO": "centro",
                "MAQUINA": "centro", "Maquina": "centro",
                "UATC": "uatc", "SubUATC": "subuatc", "SUBUATC": "subuatc",
                "Fase": "fase", "FASE": "fase",
                "T.Prep": "t_prep", "TPrep": "t_prep",
                "Prod.Horaria": "prod_horaria", "ProdHoraria": "prod_horaria",
                "Horas/Ud": "horas_por_ud", "HorasPorUd": "horas_por_ud"
            })
            for col in ["fase", "t_prep", "prod_horaria", "horas_por_ud"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            result["rutas_ops"] = df
        
        # 3. Stock
        sheet = _find_sheet(sheet_names, ["StockSKU", "Stock", "STOCK", "stock"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            df = _normalize_columns(df, {
                "Artículo": "articulo", "Articulo": "articulo",
                "Stock": "stock", "STOCK": "stock",
                "Ubicacion": "ubicacion", "UBICACION": "ubicacion"
            })
            result["stock"] = df
        
        # 4. WIP
        sheet = _find_sheet(sheet_names, ["WIP_Unidades", "WIP", "wip"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            # Normalización flexible para WIP
            normalized = {}
            for col in df.columns:
                col_lower = col.lower().replace(" ", "").replace(".", "")
                if 'art' in col_lower and ('culo' in col_lower or 'iculo' in col_lower):
                    normalized[col] = "articulo"
                elif col_lower in ['of', 'orden']:
                    normalized[col] = "of"
                elif 'fase' in col_lower:
                    normalized[col] = "fase"
                elif 'centro' in col_lower:
                    normalized[col] = "centro"
                elif 'disponible' in col_lower:
                    normalized[col] = "cantidad_disponible"
                elif 'requerid' in col_lower or 'total' in col_lower:
                    normalized[col] = "cantidad_total"
            df = df.rename(columns=normalized)
            result["wip"] = df
        
        # 5. Puntos y Lotes
        sheet = _find_sheet(sheet_names, ["puntos", "Puntos", "PUNTO Y LOTES", "PuntosLotes"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            normalized = {}
            for col in df.columns:
                col_lower = col.lower()
                if 'art' in col_lower and ('culo' in col_lower or 'iculo' in col_lower):
                    normalized[col] = "articulo"
                elif 'punto' in col_lower and 'pedido' in col_lower:
                    normalized[col] = "punto_pedido"
                elif 'lote' in col_lower and 'prod' in col_lower:
                    normalized[col] = "lote_produccion"
                elif col_lower in ['mp', 'material']:
                    normalized[col] = "mp"
            df = df.rename(columns=normalized)
            result["puntos_lotes"] = df
        
        # 6. Capacidad
        sheet = _find_sheet(sheet_names, ["Param_CapacidadCentro", "Capacidad", "CapacidadCentro"])
        if sheet:
            df = pd.read_excel(xl, sheet_name=sheet)
            df = _normalize_columns(df, {
                "Centro": "centro", "CENTRO": "centro",
                "CapacidadHoras": "capacidad_horas", "Capacidad": "capacidad_horas",
                "Turnos": "turnos", "TURNOS": "turnos"
            })
            result["capacidad_centros"] = df
        
        return result
        
    except Exception as e:
        print(f"[WATCHER] Error parseando Excel: {e}")
        return {}


# ============================================
# SINCRONIZACIÓN
# ============================================

def sync_excel_to_sqlite(excel_path: str) -> Dict[str, Any]:
    """
    Sincroniza un archivo Excel completo a SQLite.
    
    Args:
        excel_path: Ruta al archivo Excel
    
    Returns:
        Dict con resultados de sincronización por tabla
    """
    print(f"\n[SYNC] Iniciando sincronización: {Path(excel_path).name}")
    start_time = datetime.now()
    
    # Asegurar que la DB está inicializada
    init_database()
    
    # Parsear Excel
    dataframes = parse_excel_to_dataframes(excel_path)
    
    if not dataframes:
        return {"status": "error", "message": "No se pudieron parsear datos del Excel"}
    
    # Sincronizar cada tabla
    results = {}
    source_file = Path(excel_path).name
    
    for table_name, df in dataframes.items():
        try:
            result = sync_table_atomic(table_name, df, source_file)
            results[table_name] = result
        except Exception as e:
            print(f"[SYNC] Error sincronizando {table_name}: {e}")
            results[table_name] = {"status": "error", "error": str(e)}
    
    duration = (datetime.now() - start_time).total_seconds()
    print(f"[SYNC] Sincronización completada en {duration:.2f}s")
    
    return {
        "status": "ok",
        "source": source_file,
        "duration_seconds": round(duration, 2),
        "tables": results
    }


def sync_all_excel_files(folder_path: str) -> Dict[str, Any]:
    """
    Sincroniza todos los archivos Excel de una carpeta.
    Útil para sincronización inicial.
    
    Args:
        folder_path: Ruta a la carpeta con archivos Excel
    
    Returns:
        Dict con resultados de sincronización
    """
    path = Path(folder_path)
    if not path.exists():
        return {"status": "error", "message": f"Carpeta no existe: {folder_path}"}
    
    excel_files = list(path.glob("*.xlsx")) + list(path.glob("*.xls"))
    
    if not excel_files:
        print(f"[SYNC] No se encontraron archivos Excel en {folder_path}")
        return {"status": "ok", "files_synced": 0}
    
    print(f"[SYNC] Sincronizando {len(excel_files)} archivos Excel...")
    
    results = []
    for excel_file in excel_files:
        result = sync_excel_to_sqlite(str(excel_file))
        results.append({
            "file": excel_file.name,
            "result": result
        })
    
    return {
        "status": "ok",
        "files_synced": len(excel_files),
        "results": results
    }


# ============================================
# FILE WATCHER
# ============================================

class ExcelFileHandler(FileSystemEventHandler):
    """
    Handler para eventos del sistema de archivos.
    Detecta cambios en archivos Excel y dispara sincronización.
    """
    
    def __init__(self, on_sync_complete: Optional[Callable] = None):
        super().__init__()
        self.on_sync_complete = on_sync_complete
    
    def _should_process(self, event) -> bool:
        """Determina si el evento debe procesarse."""
        if event.is_directory:
            return False
        
        file_path = Path(event.src_path)
        
        # Ignorar archivos temporales de Excel (~$...)
        if file_path.name.startswith("~$"):
            return False
        
        # Verificar extensión
        return file_path.suffix.lower() in WATCHED_EXTENSIONS
    
    def _process_with_debounce(self, file_path: str) -> None:
        """Procesa un archivo con debouncing."""
        global _last_events
        
        current_time = time.time()
        last_time = _last_events.get(file_path, 0)
        
        # Si el último evento fue muy reciente, ignorar
        if current_time - last_time < DEBOUNCE_SECONDS:
            return
        
        _last_events[file_path] = current_time
        
        # Esperar un poco para que el archivo termine de escribirse
        time.sleep(0.5)
        
        # Ejecutar sincronización en un thread separado
        def do_sync():
            with _sync_lock:
                try:
                    result = sync_excel_to_sqlite(file_path)
                    if self.on_sync_complete:
                        self.on_sync_complete(file_path, result)
                except Exception as e:
                    print(f"[WATCHER] Error en sincronización: {e}")
        
        sync_thread = threading.Thread(target=do_sync, daemon=True)
        sync_thread.start()
    
    def on_modified(self, event):
        """Manejador para archivos modificados."""
        if self._should_process(event):
            print(f"[WATCHER] Detectado cambio: {Path(event.src_path).name}")
            self._process_with_debounce(event.src_path)
    
    def on_created(self, event):
        """Manejador para archivos creados."""
        if self._should_process(event):
            print(f"[WATCHER] Nuevo archivo: {Path(event.src_path).name}")
            self._process_with_debounce(event.src_path)


def start_watcher(watch_path: str, on_sync_complete: Optional[Callable] = None) -> Observer:
    """
    Inicia el watcher de archivos.
    
    Args:
        watch_path: Ruta a la carpeta a monitorear
        on_sync_complete: Callback opcional cuando se completa una sincronización
    
    Returns:
        Observer instance (para poder detenerlo después)
    """
    path = Path(watch_path)
    
    # Crear carpeta si no existe
    path.mkdir(parents=True, exist_ok=True)
    
    print(f"[WATCHER] Iniciando monitoreo de: {path}")
    
    # Hacer sincronización inicial de archivos existentes
    print("[WATCHER] Ejecutando sincronización inicial...")
    sync_all_excel_files(str(path))
    
    # Crear y configurar observer
    event_handler = ExcelFileHandler(on_sync_complete)
    observer = Observer()
    observer.schedule(event_handler, str(path), recursive=False)
    observer.start()
    
    print(f"[WATCHER] Monitoreo activo. Esperando cambios en archivos Excel...")
    
    return observer


def stop_watcher(observer: Observer) -> None:
    """
    Detiene el watcher de archivos.
    
    Args:
        observer: Instancia del Observer a detener
    """
    if observer:
        print("[WATCHER] Deteniendo monitoreo...")
        observer.stop()
        observer.join(timeout=5)
        print("[WATCHER] Monitoreo detenido")


# ============================================
# UTILIDADES
# ============================================

def get_watch_status(observer: Optional[Observer]) -> Dict[str, Any]:
    """Obtiene el estado del watcher."""
    return {
        "is_running": observer is not None and observer.is_alive() if observer else False,
        "sync_status": get_sync_status()
    }


# ============================================
# CLI PARA TESTING
# ============================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        watch_path = sys.argv[1]
    else:
        # Ruta por defecto
        watch_path = str(Path(__file__).parent.parent.parent / "data" / "inputs")
    
    print(f"=== RPK File Watcher ===")
    print(f"Monitoreando: {watch_path}")
    print("Presiona Ctrl+C para detener...")
    
    observer = start_watcher(watch_path)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_watcher(observer)
        print("\n¡Hasta luego!")
