"""
test_sqlite_sync.py - Script de Verificacion
RPK Produccion - Arquitectura SQLite

Este script verifica:
1. Creacion correcta de la base de datos
2. Sincronizacion de archivos Excel
3. Lectura de datos desde SQLite
"""

import sys
import os

# Anadir path del backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from datetime import datetime

print("=" * 60)
print("RPK Produccion - Test de Arquitectura SQLite")
print("=" * 60)
print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================
# TEST 1: Inicializacion de Base de Datos
# ============================================

print("[TEST 1] Inicializacion de Base de Datos")
print("-" * 40)

try:
    from db_manager import init_database, get_sync_status, DB_PATH, get_table_count
    
    print(f"  Ruta DB: {DB_PATH}")
    
    # Inicializar DB
    init_database()
    
    # Verificar que existe
    if DB_PATH.exists():
        size_kb = DB_PATH.stat().st_size / 1024
        print(f"  [OK] Base de datos creada ({size_kb:.1f} KB)")
    else:
        print("  [ERROR] Base de datos no se creo")
        
except Exception as e:
    print(f"  [ERROR] {e}")

print()

# ============================================
# TEST 2: Carpeta de Inputs
# ============================================

print("[TEST 2] Verificacion de Carpeta de Inputs")
print("-" * 40)

inputs_path = Path(__file__).parent.parent.parent / "data" / "inputs"
print(f"  Ruta: {inputs_path}")

excel_files = []
if inputs_path.exists():
    excel_files = list(inputs_path.glob("*.xlsx")) + list(inputs_path.glob("*.xls"))
    print(f"  [OK] Carpeta existe")
    print(f"  Archivos Excel encontrados: {len(excel_files)}")
    for f in excel_files[:5]:
        print(f"     - {f.name}")
    if len(excel_files) > 5:
        print(f"     ... y {len(excel_files) - 5} mas")
else:
    print("  [WARN] Carpeta no existe (se creara automaticamente)")
    inputs_path.mkdir(parents=True, exist_ok=True)
    print("  [OK] Carpeta creada")

print()

# ============================================
# TEST 3: Sincronizacion de Excel
# ============================================

print("[TEST 3] Sincronizacion Excel -> SQLite")
print("-" * 40)

try:
    from file_watcher import sync_all_excel_files
    
    if excel_files:
        result = sync_all_excel_files(str(inputs_path))
        print(f"  Status: {result.get('status')}")
        print(f"  Archivos procesados: {result.get('files_synced', 0)}")
        
        if result.get('results'):
            for r in result['results']:
                file_name = r.get('file', 'unknown')
                tables = r.get('result', {}).get('tables', {})
                total_rows = sum(t.get('rows', 0) for t in tables.values())
                print(f"     {file_name}: {total_rows} filas totales")
    else:
        print("  [WARN] No hay archivos Excel para sincronizar")
        print("  [TIP] Copie archivos Excel a: data/inputs/")
        
except Exception as e:
    print(f"  [ERROR] {e}")

print()

# ============================================
# TEST 4: Estado de Sincronizacion
# ============================================

print("[TEST 4] Estado de Sincronizacion")
print("-" * 40)

try:
    status = get_sync_status()
    
    print(f"  DB Path: {status.get('database_path')}")
    print(f"  DB Existe: {status.get('database_exists')}")
    
    tables = status.get('tables', [])
    if tables:
        print(f"  Tablas sincronizadas:")
        for t in tables:
            sync_time = t.get('last_sync', 'N/A')
            if sync_time and sync_time != 'N/A':
                sync_time = sync_time[:19]
            print(f"     - {t['name']}: {t['rows']} filas (sync: {sync_time})")
    else:
        print("  [WARN] No hay tablas sincronizadas aun")
        
except Exception as e:
    print(f"  [ERROR] {e}")

print()

# ============================================
# TEST 5: Lectura desde SQLite
# ============================================

print("[TEST 5] Lectura de Datos desde SQLite")
print("-" * 40)

try:
    from db_manager import read_table
    
    tables_to_check = ['pedidos', 'rutas_ops', 'stock', 'wip', 'puntos_lotes', 'capacidad_centros']
    
    for table in tables_to_check:
        df = read_table(table)
        if not df.empty:
            print(f"  [OK] {table}: {len(df)} filas, {len(df.columns)} columnas")
            # Mostrar primeras columnas
            cols = list(df.columns[:5])
            print(f"     Columnas: {', '.join(cols)}...")
        else:
            print(f"  [WARN] {table}: vacia")
            
except Exception as e:
    print(f"  [ERROR] {e}")

print()

# ============================================
# TEST 6: Integracion con data_loader
# ============================================

print("[TEST 6] Integracion con data_loader")
print("-" * 40)

try:
    from data_loader import get_dataframe, get_data_source_info
    
    # Verificar fuente de datos
    source_info = get_data_source_info()
    print(f"  Fuente primaria: {source_info.get('primary_source')}")
    print(f"  DB disponible: {source_info.get('db_available')}")
    
    # Leer datos via get_dataframe
    df_pedidos = get_dataframe('pedidos')
    df_rutas = get_dataframe('rutas_ops')
    
    print(f"  get_dataframe('pedidos'): {len(df_pedidos)} filas")
    print(f"  get_dataframe('rutas_ops'): {len(df_rutas)} filas")
    
    if not df_pedidos.empty or not df_rutas.empty:
        print("  [OK] Integracion funcionando correctamente")
    else:
        print("  [WARN] Sin datos (sincronice archivos Excel primero)")
        
except Exception as e:
    print(f"  [ERROR] {e}")

print()
print("=" * 60)
print("Test completado")
print("=" * 60)
