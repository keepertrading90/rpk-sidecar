"""
calculator.py - Motor MRP V2.0 (Backward Scheduling + Head Batching)
RPK Produccion - Arquitectura Sidecar

Este modulo implementa:
- Agrupacion de demandas por Articulo
- Logica Fase a Fase (WIP descuenta necesidad aguas arriba)
- Loteo estricto en Fase Cabecera (Fase 10)
- Explosion de materiales hacia adelante (Forward Pass)
"""

import math
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
import numpy as np

# ============================================
# CONFIGURACION
# ============================================

MAX_WORKERS = 4  # Ajustar segun CPU

COLUMN_MAPPINGS = {
    "pedidos": {
        "articulo": "articulo",
        "cantidad": "cantidad",
        "fecha_entrega": "fecha_entrega",
        "pedido": "pedido",
    },
    "stock": {
        "articulo": "articulo",
        "stock": "stock",
    },
    "rutas_ops": {
        "articulo": "articulo",
        "centro": "centro",
        "fase": "fase",
        "t_prep": "t_prep",
        "prod_horaria": "prod_horaria",
    },
    "puntos_lotes": {
        "articulo": "articulo",
        "lote": "lote_produccion",
        "punto_pedido": "punto_pedido",
        "mp": "mp"
    },
    "capacidad": {
        "centro": "centro",
        "capacidad_horas": "capacidad_horas",
        "turnos": "turnos",
    },
    "wip": {
        "articulo": "articulo",
        "cantidad": "cantidad_total",  # Usamos cantidad_total normalizada
        "fase": "fase",
    }
}


# ============================================
# PASO 1: PRE-PROCESAMIENTO (_prepare_context)
# ============================================

def _prepare_context(data_store: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """
    Convierte DataFrames a estructuras O(1) optimizadas.
    Version V2.0 con soporte para WIP faseado.
    """
    cols = COLUMN_MAPPINGS
    
    # 1. Stock Dict: { articulo_id: cantidad_disponible }
    stock_df = data_store.get("stock", pd.DataFrame())
    stock_dict = {}
    if not stock_df.empty:
        art_col = cols["stock"]["articulo"]
        stk_col = cols["stock"]["stock"]
        if art_col in stock_df.columns:
            for _, row in stock_df.iterrows():
                art = str(row[art_col])
                stock_dict[art] = float(row.get(stk_col, 0) or 0)
    
    # 2. Rutas Dict: { articulo_id: sorted_list_of_phases }
    # IMPORTANTE: Ordenamos por fase para el calculo
    rutas_df = data_store.get("rutas_ops", pd.DataFrame())
    rutas_dict = defaultdict(list)
    if not rutas_df.empty:
        for _, row in rutas_df.iterrows():
            art = str(row.get(cols["rutas_ops"]["articulo"], ""))
            if art:
                rutas_dict[art].append({
                    "centro": str(row.get(cols["rutas_ops"]["centro"], "")),
                    "fase": int(row.get(cols["rutas_ops"]["fase"], 0) or 0),
                    "t_prep": float(row.get(cols["rutas_ops"]["t_prep"], 0) or 0),
                    "prod_horaria": float(row.get(cols["rutas_ops"]["prod_horaria"], 0) or 0),
                })
    
    # Ordenar rutas por fase ascendente (10, 20, 30...)
    for art in rutas_dict:
        rutas_dict[art].sort(key=lambda x: x["fase"])

    # 3. Lotes Dict
    puntos_df = data_store.get("puntos_lotes", pd.DataFrame())
    lotes_dict = {}
    if not puntos_df.empty:
        for _, row in puntos_df.iterrows():
            art = str(row.get(cols["puntos_lotes"]["articulo"], ""))
            if art:
                lotes_dict[art] = {
                    "lote": float(row.get(cols["puntos_lotes"]["lote"], 0) or 0),
                    "punto_pedido": float(row.get(cols["puntos_lotes"]["punto_pedido"], 0) or 0),
                    "mp": str(row.get(cols["puntos_lotes"]["mp"], ""))
                }
    
    # 4. Capacidad
    cap_df = data_store.get("capacidad_centros", pd.DataFrame())
    capacidad_dict = {}
    if not cap_df.empty:
        for _, row in cap_df.iterrows():
            centro = str(row.get(cols["capacidad"]["centro"], ""))
            if centro:
                capacidad_dict[centro] = {
                    "horas": float(row.get(cols["capacidad"]["capacidad_horas"], 8) or 8),
                    "turnos": int(row.get(cols["capacidad"]["turnos"], 1) or 1),
                }
    
    # 5. WIP Dict Faseado: { articulo: { fase: cantidad } }
    # CLAVE V2.0: WIP estructurado por fase para Backward Pass
    wip_df = data_store.get("wip", pd.DataFrame())
    wip_dict = defaultdict(lambda: defaultdict(float))
    if not wip_df.empty:
        for _, row in wip_df.iterrows():
            art = str(row.get(cols["wip"]["articulo"], ""))
            fase = int(row.get(cols["wip"]["fase"], 0) or 0)
            cant = float(row.get(cols["wip"]["cantidad"], 0) or 0)
            wip_dict[art][fase] += cant
            
    # Convertir defaultdict a dict normal para pickling seguro
    final_wip = {k: dict(v) for k, v in wip_dict.items()}
    
    print(f"[MRP V2] Contexto preparado: {len(stock_dict)} stocks, {len(rutas_dict)} rutas, {len(lotes_dict)} lotes, {len(final_wip)} WIP")
    
    return {
        "stock": stock_dict,
        "rutas": dict(rutas_dict),
        "lotes": lotes_dict,
        "capacidad": capacidad_dict,
        "wip": final_wip,
    }


# ============================================
# PASO 2: WORKER ARTICULO (_calculate_article_mrp)
# ============================================

def _calculate_article_mrp(args: Tuple[str, List[Dict], Dict]) -> Dict[str, Any]:
    """
    Calcula MRP para un articulo completo (agrupando demandas).
    Logica Fase a Fase con Backward Scheduling.
    
    Args:
        args: (articulo_id, lista_demandas, context)
    """
    articulo, demandas, context = args
    
    ordenes = []
    carga_maquina = defaultdict(float)
    
    # 1. Agrupar Demanda Total
    total_demanda = sum(d["cantidad"] for d in demandas)
    if total_demanda <= 0:
        return {"ordenes": [], "carga": {}}
    
    # Fecha entrega objetivo (tomamos la minima de las demandas como referencia critica)
    fechas_validas = [d["fecha_entrega"] for d in demandas if d["fecha_entrega"] is not None]
    fecha_objetivo = min(fechas_validas) if fechas_validas else datetime.now() + timedelta(days=30)
    
    # 2. Obtener Datos del Articulo
    stock_fg = context["stock"].get(articulo, 0)
    rutas = context["rutas"].get(articulo, [])
    wip_per_fase = context["wip"].get(articulo, {})
    lote_info = context["lotes"].get(articulo, {})
    
    lote_std = lote_info.get("lote", 0)
    punto_pedido = lote_info.get("punto_pedido", 0)
    
    # 3. Calculo Necesidad Neta Global (vs Stock FG)
    # Si (Stock - Demanda) < 0, hay necesidad neta
    stock_proyectado = stock_fg - total_demanda
    necesidad_neta_fg = 0
    
    if stock_proyectado < punto_pedido:
        # Necesitamos cubrir la demanda 
        necesidad_neta_fg = abs(min(0, stock_proyectado))
        if necesidad_neta_fg <= 0:
            necesidad_neta_fg = total_demanda - stock_fg if stock_fg < total_demanda else 0
    
    if necesidad_neta_fg <= 0:
        return {"ordenes": [], "carga": {}}

    # 4. BACKWARD PASS (Fase N -> Fase 10)
    # Calculamos cuanto hay que lanzar en Cabecera descontando WIP en el camino
    
    necesidad_arrastre = necesidad_neta_fg
    
    # Iteramos fases de atras hacia adelante (ej: 30, 20, 10)
    rutas_reversed = sorted(rutas, key=lambda x: x["fase"], reverse=True)
    
    if not rutas:
        # Sin ruta, generamos una orden generica
        return _orden_generica(articulo, necesidad_neta_fg, fecha_objetivo)
        
    for op in rutas_reversed:
        fase = op["fase"]
        wip_en_fase = wip_per_fase.get(fase, 0)
        
        # La necesidad de entrada a esta fase es lo que me piden - lo que ya tengo aqui
        necesidad_entrada = max(0, necesidad_arrastre - wip_en_fase)
        
        # Pasamos la necesidad a la fase anterior
        necesidad_arrastre = necesidad_entrada
    
    # Al salir del bucle, necesidad_arrastre es lo que falta en Fase 10 (Cabecera)
    necesidad_cabecera = necesidad_arrastre
    
    if necesidad_cabecera <= 0:
        # El WIP en curso cubre toda la demanda
        return {"ordenes": [], "carga": {}}
        
    # 5. LOTEO EN CABECERA
    cantidad_lanzamiento = necesidad_cabecera
    if lote_std > 0:
        # Redondeo al lote superior
        cantidad_lanzamiento = math.ceil(necesidad_cabecera / lote_std) * lote_std
        
    # 6. FORWARD PASS (Explosion)
    # Generamos ordenes para la cantidad de lanzamiento a traves de la ruta
    
    flujo_cantidad = cantidad_lanzamiento
    rutas_asc = sorted(rutas, key=lambda x: x["fase"])
    
    ahora = datetime.now()
    dias_restantes = (fecha_objetivo - ahora).days if isinstance(fecha_objetivo, datetime) else 30
    estado_orden = "URGENTE" if dias_restantes < 7 else "NORMAL"
    
    for op in rutas_asc:
        centro = op["centro"]
        fase = op["fase"]
        t_prep = op["t_prep"]
        prod_horaria = op["prod_horaria"]
        
        if flujo_cantidad > 0:
            # Calculo tiempos
            t_ejecucion = (flujo_cantidad / prod_horaria * 60) if prod_horaria > 0 else 0
            carga_horas = (t_prep + t_ejecucion) / 60
            
            ordenes.append({
                "numero_of": f"OF-SIM-{articulo}-{fase}",
                "articulo": articulo,
                "centro": centro,
                "fase": fase,
                "cantidad": flujo_cantidad,
                "fecha_entrega": fecha_objetivo.isoformat() if hasattr(fecha_objetivo, 'isoformat') else str(fecha_objetivo),
                "estado": estado_orden,
                "dias_restantes": dias_restantes,
                "carga_horas": round(carga_horas, 2),
                "mp": lote_info.get("mp", "")
            })
            
            # Acumular carga
            if centro:
                carga_maquina[centro] += carga_horas

    return {
        "ordenes": ordenes,
        "carga": dict(carga_maquina)
    }


def _orden_generica(articulo, cantidad, fecha):
    """Fallback si no hay ruta definida."""
    return {
        "ordenes": [{
            "numero_of": f"OF-ERR-{articulo}",
            "articulo": articulo,
            "centro": "SIN_RUTA",
            "fase": 0,
            "cantidad": cantidad,
            "estado": "ERROR_RUTA",
            "carga_horas": 0,
            "dias_restantes": 0
        }],
        "carga": {}
    }


# ============================================
# PASO 3: ORQUESTADOR
# ============================================

def calculate_scenarios(params: Dict[str, Any], horizonte_dias: int = 30) -> Dict[str, Any]:
    """
    Funcion principal MRP V2.0 - Enfoque Articulo-Centrico.
    """
    from data_loader import get_data_store
    
    print(f"[MRP V2] Iniciando calculo (Articulo-Centrico)...")
    start_time = datetime.now()
    
    data_store = get_data_store()
    factor_saturacion = params.get("factor_saturacion", 1.0)
    turno_extra = params.get("turno_extra", False)
    
    # 1. Pre-procesar contexto
    context = _prepare_context(data_store)
    
    # 2. Agrupar Pedidos por Articulo
    pedidos_df = data_store.get("pedidos", pd.DataFrame())
    if pedidos_df.empty:
        print("[MRP V2] Sin pedidos - retornando vacio")
        return _empty_result()
    
    cols = COLUMN_MAPPINGS["pedidos"]
    demandas_por_articulo = defaultdict(list)
    
    for _, row in pedidos_df.iterrows():
        art = str(row.get(cols["articulo"], ""))
        if not art:
            continue
        
        # Parse fecha
        fecha = row.get(cols["fecha_entrega"])
        if isinstance(fecha, str):
            try:
                fecha = datetime.fromisoformat(fecha.replace("Z", ""))
            except:
                fecha = datetime.now() + timedelta(days=30)
        elif not isinstance(fecha, datetime):
            fecha = datetime.now() + timedelta(days=30)
            
        demandas_por_articulo[art].append({
            "cantidad": float(row.get(cols["cantidad"], 0) or 0) * factor_saturacion,
            "fecha_entrega": fecha,
            "pedido": str(row.get(cols["pedido"], ""))
        })
    
    articulos_a_procesar = list(demandas_por_articulo.keys())
    print(f"[MRP V2] Procesando {len(articulos_a_procesar)} articulos unicos...")
    
    # 3. Procesar con Paralelismo
    all_ordenes = []
    carga_total = defaultdict(float)
    
    worker_args = [(art, demandas_por_articulo[art], context) for art in articulos_a_procesar]
    
    try:
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = executor.map(_calculate_article_mrp, worker_args, chunksize=50)
            for result in futures:
                all_ordenes.extend(result.get("ordenes", []))
                for c, h in result.get("carga", {}).items():
                    carga_total[c] += h
    except Exception as e:
        print(f"[MRP V2] Error Paralelo: {e}. Fallback secuencial.")
        for args in worker_args:
            res = _calculate_article_mrp(args)
            all_ordenes.extend(res.get("ordenes", []))
            for c, h in res.get("carga", {}).items():
                carga_total[c] += h

    # 4. Calcular Saturacion
    saturacion_list = []
    cap_dict = context["capacidad"]
    
    for centro, horas_req in carga_total.items():
        cap = cap_dict.get(centro, {"horas": 8, "turnos": 1})
        turnos = cap["turnos"] + (1 if turno_extra else 0)
        cap_disp = cap["horas"] * turnos * horizonte_dias
        
        sat_pct = (horas_req / cap_disp * 100) if cap_disp > 0 else 0
        saturacion_list.append({
            "centro": centro,
            "horas_requeridas": round(horas_req, 1),
            "capacidad_disponible": round(cap_disp, 1),
            "saturacion_pct": round(sat_pct, 1),
            "es_cuello_botella": sat_pct > 100
        })
    
    # Ordenar saturacion (mayor primero) y ordenes (urgentes primero)
    saturacion_list.sort(key=lambda x: x["saturacion_pct"], reverse=True)
    all_ordenes.sort(key=lambda x: (x.get("estado") == "NORMAL", x.get("dias_restantes", 999)))
    
    # Asignar secuencia visual
    for i, o in enumerate(all_ordenes):
        o["orden"] = i + 1

    # 5. Calcular KPIs
    urgentes = len([o for o in all_ordenes if o.get("estado") == "URGENTE"])
    cuellos = [s for s in saturacion_list if s["es_cuello_botella"]]
    sat_promedio = np.mean([s["saturacion_pct"] for s in saturacion_list]) if saturacion_list else 0
    
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"[MRP V2] Fin calculo en {elapsed:.2f}s - {len(all_ordenes)} ordenes generadas")
    
    return {
        "secuencia": all_ordenes,
        "saturacion": saturacion_list,
        "kpis": {
            "articulos_urgentes": urgentes,
            "total_articulos": len(all_ordenes),
            "saturacion_promedio": round(sat_promedio, 1),
            "cuellos_botella_count": len(cuellos),
            "horas_totales": round(sum(carga_total.values()), 1),
            "centros_activos": len(carga_total)
        },
        "cuellos_botella": cuellos
    }


def _empty_result():
    """Resultado vacio para casos sin datos."""
    return {
        "secuencia": [],
        "saturacion": [],
        "kpis": {
            "articulos_urgentes": 0,
            "total_articulos": 0,
            "saturacion_promedio": 0,
            "cuellos_botella_count": 0,
            "horas_totales": 0,
            "centros_activos": 0
        },
        "cuellos_botella": []
    }


# ============================================
# COMPATIBILIDAD (Wrappers para engine.py)
# ============================================

def calcular_secuencia():
    """Wrapper de compatibilidad."""
    result = calculate_scenarios({})
    return pd.DataFrame(result["secuencia"])


def calcular_saturacion(secuencia=None, horizonte_dias=30):
    """Wrapper de compatibilidad."""
    result = calculate_scenarios({}, horizonte_dias)
    return pd.DataFrame(result["saturacion"])


def calcular_kpis(secuencia=None, saturacion=None):
    """Wrapper de compatibilidad."""
    return calculate_scenarios({})["kpis"]


def identificar_cuellos_botella(saturacion=None):
    """Wrapper de compatibilidad."""
    result = calculate_scenarios({})
    df = pd.DataFrame(result["saturacion"])
    return df[df["saturacion_pct"] > 100] if not df.empty else pd.DataFrame()


def simular_escenario(factor_saturacion=1.0, turno_extra=False, horizonte=30):
    """Wrapper de compatibilidad para engine.py."""
    return calculate_scenarios({
        "factor_saturacion": factor_saturacion,
        "turno_extra": turno_extra
    }, horizonte)
