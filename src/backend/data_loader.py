"""
data_loader.py - Carga de archivos Excel con Pandas
RPK Producción - Arquitectura Sidecar

Este módulo maneja:
- Lectura de Excel V5 (programacion_reunion_V5.xlsx)
- Parseo de todas las hojas necesarias
- Cache en memoria (RAM) para evitar lecturas repetidas
- Detección de cambios en archivos por timestamp
"""

import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

# ============================================
# ALMACÉN DE DATOS EN MEMORIA (STATEFUL)
# ============================================

DATA_STORE: Dict[str, Any] = {
    "pedidos": pd.DataFrame(),
    "rutas_ops": pd.DataFrame(),
    "stock": pd.DataFrame(),
    "wip": pd.DataFrame(),
    "puntos_lotes": pd.DataFrame(),
    "capacidad_centros": pd.DataFrame(),
    "maestro_articulos": pd.DataFrame(),
    "last_modified": {},  # {filename: mtime}
    "stats": {},
    "is_loaded": False,
    "load_time": None
}


def get_data_store() -> Dict[str, Any]:
    """Retorna el almacén de datos global."""
    return DATA_STORE


def is_data_loaded() -> bool:
    """Verifica si los datos están cargados en memoria."""
    return DATA_STORE["is_loaded"]


def get_stats() -> Dict[str, Any]:
    """Retorna estadísticas de los datos cargados."""
    return DATA_STORE["stats"]


# ============================================
# FUNCIONES DE CARGA
# ============================================

def check_files_changed(folder_path: str) -> bool:
    """
    Verifica si los archivos Excel han cambiado desde la última carga.
    Retorna True si hay cambios y se necesita recargar.
    """
    path = Path(folder_path)
    if not path.exists():
        return True
    
    excel_files = list(path.glob("*.xlsx"))
    
    for file in excel_files:
        mtime = file.stat().st_mtime
        stored_mtime = DATA_STORE["last_modified"].get(str(file), 0)
        if mtime > stored_mtime:
            return True
    
    return False


def load_excel_folder(folder_path: str, force_reload: bool = False) -> Dict[str, Any]:
    """
    Carga todos los archivos Excel de una carpeta en DataFrames.
    
    Args:
        folder_path: Ruta a la carpeta con archivos Excel
        force_reload: Si es True, recarga aunque no haya cambios
    
    Returns:
        Dict con estadísticas de carga
    """
    path = Path(folder_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Carpeta no encontrada: {folder_path}")
    
    # Verificar si necesitamos recargar
    if DATA_STORE["is_loaded"] and not force_reload and not check_files_changed(folder_path):
        return {
            "status": "cached",
            "message": "Datos ya cargados en memoria, sin cambios detectados",
            "stats": DATA_STORE["stats"]
        }
    
    # Buscar archivo V5 o V4
    v5_file = path / "programacion_reunion_V5.xlsx"
    v4_file = path / "programacion_reunion_V4.xlsx"
    
    excel_file = None
    if v5_file.exists():
        excel_file = v5_file
    elif v4_file.exists():
        excel_file = v4_file
    else:
        # Buscar cualquier xlsx
        xlsx_files = list(path.glob("*.xlsx"))
        if xlsx_files:
            excel_file = xlsx_files[0]
    
    if excel_file is None:
        raise FileNotFoundError(f"No se encontraron archivos Excel en: {folder_path}")
    
    print(f"[LOAD] Cargando archivo: {excel_file.name}")
    
    # Cargar el archivo Excel
    result = parse_programacion_excel(str(excel_file))
    
    # Actualizar timestamps
    DATA_STORE["last_modified"][str(excel_file)] = excel_file.stat().st_mtime
    DATA_STORE["is_loaded"] = True
    DATA_STORE["load_time"] = datetime.now().isoformat()
    
    return result


def parse_programacion_excel(file_path: str) -> Dict[str, Any]:
    """
    Parsea el archivo de programación Excel (V5/V4).
    
    Args:
        file_path: Ruta completa al archivo Excel
    
    Returns:
        Dict con estadísticas de cada hoja parseada
    """
    print(f"[PARSE] Parseando: {file_path}")
    
    # Leer todas las hojas
    xl = pd.ExcelFile(file_path)
    sheet_names = xl.sheet_names
    print(f"   Hojas encontradas: {sheet_names}")
    
    stats = {}
    
    # Parsear cada hoja conocida
    # 1. Pedidos
    pedidos_df = parse_sheet_pedidos(xl, sheet_names)
    DATA_STORE["pedidos"] = pedidos_df
    stats["pedidos"] = len(pedidos_df)
    
    # 2. RutasOps
    rutas_df = parse_sheet_rutas_ops(xl, sheet_names)
    DATA_STORE["rutas_ops"] = rutas_df
    stats["rutas_ops"] = len(rutas_df)
    
    # 3. StockSKU
    stock_df = parse_sheet_stock(xl, sheet_names)
    DATA_STORE["stock"] = stock_df
    stats["stock"] = len(stock_df)
    
    # 4. WIP_Unidades
    wip_df = parse_sheet_wip(xl, sheet_names)
    DATA_STORE["wip"] = wip_df
    stats["wip"] = len(wip_df)
    
    # 5. Puntos y Lotes
    puntos_df = parse_sheet_puntos_lotes(xl, sheet_names)
    DATA_STORE["puntos_lotes"] = puntos_df
    stats["puntos_lotes"] = len(puntos_df)
    
    # 6. Capacidad Centros
    capacidad_df = parse_sheet_capacidad(xl, sheet_names)
    DATA_STORE["capacidad_centros"] = capacidad_df
    stats["capacidad_centros"] = len(capacidad_df)
    
    # Guardar stats
    DATA_STORE["stats"] = {
        **stats,
        "archivo": Path(file_path).name,
        "fecha_carga": datetime.now().isoformat()
    }
    
    print(f"[OK] Carga completada: {stats}")
    
    return {
        "status": "ok",
        "message": "Datos cargados correctamente",
        "stats": DATA_STORE["stats"]
    }


# ============================================
# PARSEADORES DE HOJAS
# ============================================

def find_sheet(sheet_names: List[str], possible_names: List[str]) -> Optional[str]:
    """Busca una hoja por nombres posibles (case-insensitive)."""
    for name in possible_names:
        for sheet in sheet_names:
            if name.lower() == sheet.lower():
                return sheet
    return None


def parse_sheet_pedidos(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de Pedidos."""
    sheet = find_sheet(sheet_names, ["Pedidos", "pedidos", "PEDIDOS"])
    if not sheet:
        print("   [WARN] Hoja 'Pedidos' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [PEDIDOS] Pedidos: {len(df)} registros")
    
    # Normalizar nombres de columnas
    column_map = {
        "Artículo": "articulo",
        "Articulo": "articulo",
        "ARTICULO": "articulo",
        "Pedido": "pedido",
        "PEDIDO": "pedido",
        "Cantidad": "cantidad",
        "CANTIDAD": "cantidad",
        "Pedidas": "pedidas",
        "Servidas": "servidas",
        "Fecha Entrega": "fecha_entrega",
        "FechaEntrega": "fecha_entrega",
        "FECHA ENTREGA": "fecha_entrega"
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
    
    # Convertir fechas
    if "fecha_entrega" in df.columns:
        df["fecha_entrega"] = pd.to_datetime(df["fecha_entrega"], errors="coerce")
    
    return df


def parse_sheet_rutas_ops(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de Rutas de Operaciones."""
    sheet = find_sheet(sheet_names, ["RutasOps", "rutasops", "RUTASOPS", "Rutas"])
    if not sheet:
        print("   [WARN] Hoja 'RutasOps' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [RUTAS] RutasOps: {len(df)} registros")
    
    column_map = {
        "Artículo": "articulo",
        "Articulo": "articulo",
        "Centro": "centro",
        "CENTRO": "centro",
        "MAQUINA": "centro",  # En V5 la columna se llama MAQUINA
        "Maquina": "centro",
        "UATC": "uatc",
        "SubUATC": "subuatc",
        "SUBUATC": "subuatc",
        "Fase": "fase",
        "FASE": "fase",
        "T.Prep": "t_prep",
        "TPrep": "t_prep",
        "Prod.Horaria": "prod_horaria",
        "ProdHoraria": "prod_horaria",
        "Horas/Ud": "horas_por_ud",
        "HorasPorUd": "horas_por_ud"
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
    
    # Asegurar tipos numéricos
    for col in ["fase", "t_prep", "prod_horaria", "horas_por_ud"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    return df


def parse_sheet_stock(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de Stock."""
    sheet = find_sheet(sheet_names, ["StockSKU", "Stock", "STOCK", "stock"])
    if not sheet:
        print("   [WARN] Hoja 'StockSKU' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [STOCK] Stock: {len(df)} registros")
    
    column_map = {
        "Artículo": "articulo",
        "Articulo": "articulo",
        "Stock": "stock",
        "STOCK": "stock"
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
    
    return df


def parse_sheet_wip(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de WIP (Work In Progress)."""
    sheet = find_sheet(sheet_names, ["WIP_Unidades", "WIP", "wip"])
    if not sheet:
        print("   [WARN] Hoja 'WIP_Unidades' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [WIP] WIP: {len(df)} registros")
    
    # Normalizar columnas con deteccion flexible
    normalized_cols = {}
    for col in df.columns:
        col_lower = col.lower().replace(" ", "").replace(".", "")
        
        if 'art' in col_lower and ('culo' in col_lower or 'iculo' in col_lower):
            normalized_cols[col] = "articulo"
        elif col_lower in ['of', 'of', 'orden']:
            normalized_cols[col] = "of"
        elif 'fase' in col_lower:
            normalized_cols[col] = "fase"
        elif 'centro' in col_lower:
            normalized_cols[col] = "centro"
        elif 'disponible' in col_lower and 'cantidad' in col_lower:
            normalized_cols[col] = "cantidad_disponible"
        elif 'requerid' in col_lower:
            normalized_cols[col] = "cantidad_total"
    
    df = df.rename(columns=normalized_cols)
    
    # Si no hay cantidad_total, crear desde cantidad_disponible
    if "cantidad_total" not in df.columns and "cantidad_disponible" in df.columns:
        df["cantidad_total"] = df["cantidad_disponible"]
    
    return df


def parse_sheet_puntos_lotes(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de Puntos y Lotes."""
    sheet = find_sheet(sheet_names, ["puntos", "Puntos", "PUNTO Y LOTES", "PuntosLotes"])
    if not sheet:
        print("   [WARN] Hoja 'puntos' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [LOTES] PuntosLotes: {len(df)} registros")
    
    # Normalizar nombres de columnas (eliminar acentos, mayusculas, etc.)
    normalized_cols = {}
    for col in df.columns:
        col_lower = col.lower()
        # Detectar columna de articulo
        if 'art' in col_lower and ('culo' in col_lower or 'iculo' in col_lower):
            normalized_cols[col] = "articulo"
        elif 'punto' in col_lower and 'pedido' in col_lower:
            normalized_cols[col] = "punto_pedido"
        elif 'lote' in col_lower and 'prod' in col_lower:
            normalized_cols[col] = "lote_produccion"
        elif col_lower in ['mp', 'material']:
            normalized_cols[col] = "mp"
    
    df = df.rename(columns=normalized_cols)
    
    return df


def parse_sheet_capacidad(xl: pd.ExcelFile, sheet_names: List[str]) -> pd.DataFrame:
    """Parsea la hoja de Capacidad de Centros."""
    sheet = find_sheet(sheet_names, ["Param_CapacidadCentro", "Capacidad", "CapacidadCentro"])
    if not sheet:
        print("   [WARN] Hoja 'Param_CapacidadCentro' no encontrada")
        return pd.DataFrame()
    
    df = pd.read_excel(xl, sheet_name=sheet)
    print(f"   [CAP] Capacidad: {len(df)} registros")
    
    column_map = {
        "Centro": "centro",
        "CENTRO": "centro",
        "CapacidadHoras": "capacidad_horas",
        "Capacidad": "capacidad_horas",
        "Turnos": "turnos"
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})
    
    return df


# ============================================
# FUNCIONES DE UTILIDAD
# ============================================

def get_dataframe(name: str) -> pd.DataFrame:
    """
    Obtiene un DataFrame del almacén por nombre.
    
    Args:
        name: Nombre del DataFrame (pedidos, rutas_ops, stock, wip, puntos_lotes, capacidad_centros)
    
    Returns:
        DataFrame correspondiente o DataFrame vacío si no existe
    """
    return DATA_STORE.get(name, pd.DataFrame())


def reset_data_store():
    """Limpia todos los datos del almacén."""
    global DATA_STORE
    DATA_STORE = {
        "pedidos": pd.DataFrame(),
        "rutas_ops": pd.DataFrame(),
        "stock": pd.DataFrame(),
        "wip": pd.DataFrame(),
        "puntos_lotes": pd.DataFrame(),
        "capacidad_centros": pd.DataFrame(),
        "maestro_articulos": pd.DataFrame(),
        "last_modified": {},
        "stats": {},
        "is_loaded": False,
        "load_time": None
    }
    print("[RESET] Almacen de datos reseteado")
