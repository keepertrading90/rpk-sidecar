# RPK Producción - Sidecar Pattern

Sistema de Secuenciación de Producción con arquitectura Sidecar.

## Descripción

Esta aplicación implementa el patrón "Sidecar" donde:
- **Frontend**: Electron + HTML/JS para la interfaz de usuario
- **Backend**: Python + FastAPI para procesamiento de datos masivos

## Requisitos Previos

### Python 3.8+
1. Descargar desde: https://www.python.org/downloads/
2. Durante la instalación, marcar "Add Python to PATH"
3. Verificar instalación: `python --version`

### Node.js 18+
1. Descargar desde: https://nodejs.org/
2. Verificar instalación: `node --version`

## Instalación

### 1. Instalar dependencias de Python
```bash
cd src/backend
pip install -r requirements.txt
```

### 2. Instalar dependencias de Node.js
```bash
npm install
```

## Ejecución

### Opción 1: Script Automático (Recomendado)
Ejecutar `iniciar_app.bat` haciendo doble clic.

### Opción 2: Manual
```bash
# Terminal 1 - Backend Python
cd src/backend
python engine.py

# Terminal 2 - Frontend Electron
npm run electron:dev
```

## Estructura del Proyecto

```
rpk-sidecar/
├── src/
│   ├── backend/           # Servidor Python FastAPI
│   │   ├── engine.py      # Endpoints REST
│   │   ├── data_loader.py # Carga de Excel
│   │   └── calculator.py  # Lógica de cálculo
│   ├── frontend/          # Interfaz Electron
│   │   ├── index.html
│   │   ├── css/
│   │   └── js/
│   └── electron/          # Código Electron
│       ├── main.js
│       └── preload.js
├── package.json
└── iniciar_app.bat
```

## Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/init-load` | Carga archivos Excel en memoria |
| POST | `/simulate` | Ejecuta simulación de escenario |
| GET | `/health` | Verificar estado del servidor |
| GET | `/data/secuencia` | Obtener secuencia calculada |
| GET | `/data/saturacion` | Obtener saturación por centro |
| GET | `/data/kpis` | Obtener KPIs |

## Licencia

© 2026 RPK S COOP - Todos los derechos reservados
