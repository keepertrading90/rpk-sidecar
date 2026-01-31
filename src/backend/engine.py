"""
engine.py - Servidor FastAPI
RPK Producción - Arquitectura Sidecar

Este módulo implementa:
- Servidor FastAPI con endpoints REST
- Auto-detección de puerto libre
- CORS para localhost
- Endpoints: /init-load, /simulate, /health, /data/*
"""

import sys
import os
import socket
from contextlib import closing
from typing import Optional
from datetime import datetime

# Añadir directorio actual al path para imports locales
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Importar módulos locales
from data_loader import load_excel_folder, get_stats, is_data_loaded, get_dataframe
from calculator import (
    calcular_secuencia, 
    calcular_saturacion, 
    calcular_kpis, 
    identificar_cuellos_botella,
    simular_escenario
)


# ============================================
# CONFIGURACIÓN DE LA APP
# ============================================

app = FastAPI(
    title="RPK Producción API",
    description="API Sidecar para procesamiento de datos de producción",
    version="1.0.0"
)

# Configurar CORS para permitir peticiones desde Electron
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir a localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# MODELOS DE DATOS (Pydantic)
# ============================================

class InitLoadRequest(BaseModel):
    path: str
    force_reload: bool = False


class InitLoadResponse(BaseModel):
    status: str
    message: str
    stats: dict


class SimulateRequest(BaseModel):
    factor_saturacion: float = 1.0
    turno_extra: bool = False
    horizonte: int = 30


class HealthResponse(BaseModel):
    status: str
    port: int
    loaded: bool
    timestamp: str


# ============================================
# ENDPOINTS
# ============================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Verificar el estado del servidor.
    Útil para que Electron sepa que el backend está listo.
    """
    return HealthResponse(
        status="ok",
        port=RUNNING_PORT,
        loaded=is_data_loaded(),
        timestamp=datetime.now().isoformat()
    )


@app.post("/init-load", response_model=InitLoadResponse)
async def init_load(request: InitLoadRequest):
    """
    Cargar archivos Excel en memoria.
    
    - **path**: Ruta a la carpeta con los archivos Excel
    - **force_reload**: Si True, recarga aunque no haya cambios
    """
    try:
        result = load_excel_folder(request.path, request.force_reload)
        return InitLoadResponse(
            status=result.get("status", "ok"),
            message=result.get("message", "Datos cargados"),
            stats=result.get("stats", {})
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar datos: {str(e)}")


@app.post("/simulate")
async def simulate(request: SimulateRequest):
    """
    Ejecutar simulación de escenario.
    
    - **factor_saturacion**: Multiplicador de carga (1.0 = normal, 1.2 = +20%)
    - **turno_extra**: Añadir turno extra a la capacidad
    - **horizonte**: Días de horizonte para cálculos
    """
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados. Ejecutar /init-load primero.")
    
    try:
        result = simular_escenario(
            factor_saturacion=request.factor_saturacion,
            turno_extra=request.turno_extra,
            horizonte=request.horizonte
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en simulación: {str(e)}")


@app.get("/data/secuencia")
async def get_secuencia():
    """
    Obtener la secuencia de producción calculada.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados. Ejecutar /init-load primero.")
    
    try:
        secuencia = calcular_secuencia()
        return {
            "count": len(secuencia),
            "data": secuencia.to_dict(orient="records") if not secuencia.empty else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al calcular secuencia: {str(e)}")


@app.get("/data/saturacion")
async def get_saturacion():
    """
    Obtener la saturación por centro de trabajo.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados. Ejecutar /init-load primero.")
    
    try:
        saturacion = calcular_saturacion()
        return {
            "count": len(saturacion),
            "data": saturacion.to_dict(orient="records") if not saturacion.empty else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al calcular saturación: {str(e)}")


@app.get("/data/kpis")
async def get_kpis():
    """
    Obtener los KPIs del sistema.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados. Ejecutar /init-load primero.")
    
    try:
        kpis = calcular_kpis()
        return kpis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al calcular KPIs: {str(e)}")


@app.get("/data/cuellos-botella")
async def get_cuellos_botella():
    """
    Obtener los centros cuello de botella (saturación > 100%).
    """
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados. Ejecutar /init-load primero.")
    
    try:
        cuellos = identificar_cuellos_botella()
        return {
            "count": len(cuellos),
            "data": cuellos.to_dict(orient="records") if not cuellos.empty else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/data/stats")
async def get_data_stats():
    """
    Obtener estadísticas de los datos cargados.
    """
    stats = get_stats()
    return {
        "loaded": is_data_loaded(),
        "stats": stats
    }


@app.get("/data/raw/{table_name}")
async def get_raw_data(table_name: str):
    """
    Obtener datos crudos de una tabla específica.
    
    Tablas disponibles: pedidos, rutas_ops, stock, wip, puntos_lotes, capacidad_centros
    """
    valid_tables = ["pedidos", "rutas_ops", "stock", "wip", "puntos_lotes", "capacidad_centros"]
    
    if table_name not in valid_tables:
        raise HTTPException(status_code=400, detail=f"Tabla inválida. Usar: {valid_tables}")
    
    if not is_data_loaded():
        raise HTTPException(status_code=400, detail="Datos no cargados")
    
    df = get_dataframe(table_name)
    return {
        "table": table_name,
        "count": len(df),
        "data": df.head(1000).to_dict(orient="records")  # Limitar a 1000 registros
    }


# ============================================
# UTILIDADES
# ============================================

def find_free_port(start_port: int = 8000, end_port: int = 8100) -> int:
    """
    Busca un puerto libre en el rango especificado.
    """
    for port in range(start_port, end_port):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                sock.bind(('localhost', port))
                return port
            except socket.error:
                continue
    raise RuntimeError(f"No se encontró puerto libre entre {start_port} y {end_port}")


# Variable global para almacenar el puerto en uso
RUNNING_PORT: int = 8000


# ============================================
# PUNTO DE ENTRADA
# ============================================

if __name__ == "__main__":
    # Buscar puerto disponible
    port = find_free_port()
    RUNNING_PORT = port
    
    # Imprimir mensaje para que Electron pueda capturarlo
    print(f"BACKEND_READY|PORT={port}", flush=True)
    print(f"[API] Servidor FastAPI iniciando en http://localhost:{port}")
    print(f"[API] Documentacion disponible en http://localhost:{port}/docs")
    
    # Iniciar servidor
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=port,
        log_level="info"
    )
