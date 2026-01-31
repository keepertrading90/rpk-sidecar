# RPK Sidecar - Documentación Técnica Completa

## Índice
1. [Arquitectura General](#arquitectura-general)
2. [Backend Python (FastAPI)](#backend-python)
3. [Motor MRP Paralelo](#motor-mrp)
4. [Frontend Electron](#frontend-electron)
5. [API Endpoints](#api-endpoints)
6. [Guía de Iteración](#guia-iteracion)

---

## 1. Arquitectura General <a name="arquitectura-general"></a>

```
┌─────────────────────────────────────────────────────────────────┐
│                        ELECTRON (main.js)                        │
│  - Spawn proceso Python                                          │
│  - Captura puerto vía stdout                                     │
│  - Gestión ciclo de vida                                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │ IPC (preload.js)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND (index.html + app.js)                │
│  - Dashboard KPIs                                                │
│  - Controles simulación                                          │
│  - Tabla secuencia                                               │
│  - Gráficos saturación                                           │
└─────────────────────┬───────────────────────────────────────────┘
                      │ REST API (fetch)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND PYTHON (FastAPI)                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ engine.py    │  │data_loader.py│  │ calculator.py        │   │
│  │ (API REST)   │──│ (Excel→RAM)  │──│ (MRP Paralelo)       │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                           │                    │                 │
│                    ┌──────▼────────────────────▼──────┐          │
│                    │     DATA_STORE (Memoria RAM)     │          │
│                    │  - pedidos: DataFrame            │          │
│                    │  - rutas_ops: DataFrame          │          │
│                    │  - stock: DataFrame              │          │
│                    │  - wip: DataFrame                │          │
│                    │  - puntos_lotes: DataFrame       │          │
│                    │  - capacidad_centros: DataFrame  │          │
│                    └──────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend Python <a name="backend-python"></a>

### 2.1 data_loader.py - Cargador de Datos

**Propósito:** Leer archivos Excel V5/V4 y almacenar DataFrames en memoria.

#### Funciones Principales

| Función | Descripción |
|---------|-------------|
| `load_excel_folder(path, force_reload)` | Carga todos los Excel de una carpeta |
| `parse_programacion_excel(file)` | Parsea el archivo principal V5 |
| `get_dataframe(name)` | Obtiene un DataFrame del store |
| `get_data_store()` | Retorna el store completo |
| `is_data_loaded()` | Verifica si hay datos cargados |

#### Estructura DATA_STORE

```python
DATA_STORE = {
    "pedidos": pd.DataFrame(),        # Pedidos pendientes de clientes
    "rutas_ops": pd.DataFrame(),      # Rutas de fabricación por artículo
    "stock": pd.DataFrame(),          # Stock disponible por artículo
    "wip": pd.DataFrame(),            # Work In Progress (órdenes en curso)
    "puntos_lotes": pd.DataFrame(),   # Puntos de pedido y lotes de producción
    "capacidad_centros": pd.DataFrame(), # Capacidad por centro de trabajo
    "last_modified": {},              # Timestamps de archivos
    "stats": {},                      # Estadísticas de carga
    "is_loaded": False,
    "load_time": None
}
```

#### Mapeo de Columnas (Hojas Excel → DataFrame)

| Hoja Excel | Columnas Origen | Columnas Normalizadas |
|------------|-----------------|----------------------|
| `Pedidos` | Artículo, Cantidad, Fecha Entrega | articulo, cantidad, fecha_entrega |
| `RutasOps` | MAQUINA, Fase, Prod.Horaria | centro, fase, prod_horaria |
| `StockSKU` | Artículo, Stock | articulo, stock |
| `WIP_Unidades` | O.F, Cantidad disponible | of, cantidad_disponible |
| `puntos` | ARTÍCULO, LOTE DE PRODUCCIÓN | articulo, lote_produccion |
| `Param_CapacidadCentro` | Centro, CapacidadHoras | centro, capacidad_horas |

---

### 2.2 calculator.py - Motor MRP Paralelo

**Propósito:** Calcular necesidades de material y carga de máquinas usando multiprocessing.

#### Arquitectura del Motor

```
┌─────────────────────────────────────────────────────────────────┐
│                    calculate_scenarios()                         │
│                    (Orquestador Principal)                       │
└─────────────────────┬───────────────────────────────────────────┘
                      │
           ┌──────────▼──────────┐
           │ _prepare_context()   │  ← Conversión DataFrames → Dicts O(1)
           └──────────┬──────────┘
                      │
           ┌──────────▼──────────┐
           │ ProcessPoolExecutor │  ← 4 workers paralelos
           │      (Pool)         │
           └──────────┬──────────┘
                      │
    ┌─────────────────┼─────────────────┐
    ▼                 ▼                 ▼
┌───────┐        ┌───────┐        ┌───────┐
│Worker1│        │Worker2│        │Worker3│  ...
│ MRP   │        │ MRP   │        │ MRP   │
└───────┘        └───────┘        └───────┘
    │                 │                 │
    └─────────────────┼─────────────────┘
                      ▼
              ┌──────────────┐
              │ Agregación   │  ← Suma cargas, ordena secuencia
              │ y KPIs       │
              └──────────────┘
```

#### Funciones del Motor

| Función | Descripción |
|---------|-------------|
| `_prepare_context(data_store)` | Convierte DataFrames a diccionarios de acceso O(1) |
| `_calculate_single_item_mrp(args)` | Worker aislado que calcula MRP de un pedido |
| `calculate_scenarios(params, horizonte)` | Orquestador principal del cálculo paralelo |

#### Lógica MRP por Pedido

```python
# Pseudocódigo del worker
def _calculate_single_item_mrp(pedido, contexto):
    # 1. Calcular Necesidad Neta
    necesidad = pedido.cantidad - stock[articulo] - wip[articulo]
    
    # 2. Si hay necesidad > 0
    if necesidad > 0:
        # Ajustar a lote de producción
        cantidad_fabricar = redondear_lote(necesidad, lotes[articulo])
        
        # 3. Para cada fase/centro del artículo
        for ruta in rutas[articulo]:
            # Calcular carga
            carga = t_prep + (cantidad / prod_horaria * 60)
            
            # Crear orden de fabricación
            ordenes.append({...})
            carga_centro[ruta.centro] += carga
    
    return ordenes, carga_centro
```

#### Configuración de Columnas (COLUMN_MAPPINGS)

```python
COLUMN_MAPPINGS = {
    "pedidos": {
        "articulo": "articulo",
        "cantidad": "cantidad",
        "fecha_entrega": "fecha_entrega",
    },
    "stock": {
        "articulo": "articulo",
        "stock": "stock",
    },
    # ... etc
}
```

**Para cambiar nombres de columnas:** Modificar solo este diccionario.

---

### 2.3 engine.py - Servidor FastAPI

**Propósito:** Exponer endpoints REST para el frontend.

#### Endpoints Disponibles

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servidor |
| POST | `/init-load` | Cargar archivos Excel |
| POST | `/simulate` | Ejecutar simulación MRP |
| GET | `/data/secuencia` | Obtener secuencia calculada |
| GET | `/data/saturacion` | Obtener saturación por centro |
| GET | `/data/kpis` | Obtener KPIs |
| GET | `/data/cuellos-botella` | Centros con saturación >100% |
| GET | `/data/stats` | Estadísticas de datos cargados |
| GET | `/data/raw/{tabla}` | Datos crudos de una tabla |

#### Modelos Pydantic

```python
class InitLoadRequest:
    path: str           # Ruta a carpeta de Excel
    force_reload: bool  # Forzar recarga aunque no haya cambios

class SimulateRequest:
    factor_saturacion: float  # 1.0 = normal, 1.2 = +20%
    turno_extra: bool         # Añadir turno extra
    horizonte: int            # Días de horizonte
```

---

## 3. Motor MRP - Flujo de Datos <a name="motor-mrp"></a>

```
ENTRADA                          PROCESO                         SALIDA
────────────────────────────────────────────────────────────────────────
                                    
Pedidos (2860)  ──┐              ┌─────────────────┐
                  │              │                 │
Stock (284)     ──┼──────────────▶  MRP PARALELO   │
                  │              │                 │
WIP (182)       ──┤              │  4 Workers      │──────▶ Órdenes (3660)
                  │              │  0.9 segundos   │
RutasOps (1173) ──┤              │                 │──────▶ Saturación (63)
                  │              └─────────────────┘
PuntosLotes (234)─┤                                │──────▶ KPIs
                  │                                │
Capacidad (109) ──┘                                └──────▶ Cuellos Botella

```

---

## 4. Frontend Electron <a name="frontend-electron"></a>

### 4.1 Estructura de Archivos

```
src/frontend/
├── index.html      # Estructura HTML del dashboard
├── css/
│   └── styles.css  # Estilos tema oscuro RPK
└── js/
    └── app.js      # Lógica cliente API
```

### 4.2 Elementos de UI (index.html)

#### Panel de Control (sidebar izquierdo)

| ID | Tipo | Función |
|----|------|---------|
| `btn-load-data` | Botón | Recargar datos manualmente |
| `data-stats` | Div | Muestra conteo de registros cargados |
| `slider-saturacion` | Range | Factor de saturación (0.5x - 2.0x) |
| `check-turno-extra` | Checkbox | Activar turno extra |
| `input-horizonte` | Number | Días de horizonte (7-90) |
| `btn-simulate` | Botón | Ejecutar simulación |

#### Dashboard (área principal)

| ID | Tipo | Contenido |
|----|------|-----------|
| `kpi-urgentes` | Span | Número de artículos urgentes |
| `kpi-total` | Span | Total de órdenes |
| `kpi-saturacion` | Span | Saturación media (%) |
| `kpi-cuellos` | Span | Cantidad de cuellos de botella |
| `kpi-horas` | Span | Horas totales requeridas |
| `kpi-centros` | Span | Centros de trabajo activos |
| `saturacion-chart` | Div | Gráfico de barras de saturación |
| `secuencia-tbody` | Tbody | Tabla de secuencia de producción |

### 4.3 Funciones JavaScript (app.js)

#### Conexión con Backend

| Función | Descripción |
|---------|-------------|
| `checkConnection()` | Verifica conexión con `/health` |
| `loadData()` | Llama a `/init-load` para cargar Excel |
| `runSimulation()` | Llama a `/simulate` con parámetros del UI |
| `loadDashboard()` | Carga KPIs, saturación y secuencia |

#### Actualización de UI

| Función | Descripción |
|---------|-------------|
| `updateKPIs(kpis)` | Actualiza los 6 indicadores KPI |
| `updateSaturacionChart(data)` | Genera barras de saturación por centro |
| `updateSecuenciaTable(data)` | Rellena tabla de secuencia |
| `updateDataStats(stats)` | Muestra estadísticas de carga |

#### Flujo de Eventos

```javascript
// 1. Al cargar la página
document.addEventListener('DOMContentLoaded', async () => {
    API_BASE = await window.electronAPI.getApiUrl();
    await checkConnection();  // Verificar backend
    await loadData();         // Carga automática
});

// 2. Al hacer clic en "Simular"
btn-simulate.onclick = () => {
    const params = {
        factor_saturacion: slider.value,
        turno_extra: checkbox.checked,
        horizonte: input.value
    };
    fetch('/simulate', { body: JSON.stringify(params) });
};
```

---

## 5. API Endpoints - Detalle <a name="api-endpoints"></a>

### POST /init-load

**Request:**
```json
{
  "path": "C:/ruta/a/carpeta/data",
  "force_reload": false
}
```

**Response:**
```json
{
  "status": "ok",
  "message": "Datos cargados correctamente",
  "stats": {
    "pedidos": 2860,
    "rutas_ops": 1173,
    "stock": 284,
    "wip": 182,
    "puntos_lotes": 234,
    "capacidad_centros": 109
  }
}
```

### POST /simulate

**Request:**
```json
{
  "factor_saturacion": 1.2,
  "turno_extra": true,
  "horizonte": 30
}
```

**Response:**
```json
{
  "parametros": {...},
  "secuencia": [
    {
      "orden": 1,
      "numero_of": "OF-2026-12345-20",
      "articulo": "453713",
      "centro": "910",
      "cantidad": 3000,
      "estado": "URGENTE",
      "dias_restantes": 5,
      "carga_horas": 2.5
    }
  ],
  "saturacion": [
    {
      "centro": "910",
      "horas_requeridas": 240.5,
      "capacidad_disponible": 200,
      "saturacion_pct": 120.2,
      "es_cuello_botella": true
    }
  ],
  "kpis": {
    "articulos_urgentes": 91,
    "total_articulos": 3660,
    "saturacion_promedio": 230.4,
    "cuellos_botella_count": 19,
    "horas_totales": 69145.2,
    "centros_activos": 63
  },
  "cuellos_botella": [...]
}
```

---

## 6. Guía de Iteración <a name="guia-iteracion"></a>

### 6.1 Añadir Nuevo KPI

1. **Backend (calculator.py):** Añadir cálculo en `calculate_scenarios()`:
```python
kpis["nuevo_kpi"] = calcular_nuevo_valor()
```

2. **Frontend (index.html):** Añadir card:
```html
<div class="kpi-card">
    <span class="kpi-value" id="kpi-nuevo">0</span>
    <span class="kpi-label">Nuevo KPI</span>
</div>
```

3. **Frontend (app.js):** Actualizar en `updateKPIs()`:
```javascript
document.getElementById('kpi-nuevo').textContent = kpis.nuevo_kpi;
```

### 6.2 Añadir Nuevo Control de Simulación

1. **Frontend (index.html):** Añadir control:
```html
<input type="number" id="input-nuevo-param" value="10">
```

2. **Frontend (app.js):** Capturar en `runSimulation()`:
```javascript
const nuevoParam = parseInt(document.getElementById('input-nuevo-param').value);
body: JSON.stringify({
    ...params,
    nuevo_param: nuevoParam
})
```

3. **Backend (calculator.py):** Usar en `calculate_scenarios()`:
```python
nuevo_param = params.get("nuevo_param", 10)
```

### 6.3 Añadir Nueva Vista/Página

1. Crear `nueva_vista.html` en `src/frontend/`
2. Añadir entrada en menú (`main.js`):
```javascript
{
    label: 'Nueva Vista',
    click: () => mainWindow.loadFile('src/frontend/nueva_vista.html')
}
```

### 6.4 Modificar Mapeo de Columnas Excel

Editar `COLUMN_MAPPINGS` en `calculator.py`:
```python
COLUMN_MAPPINGS = {
    "pedidos": {
        "articulo": "NuevoNombreColumna",  # Cambiar aquí
        ...
    }
}
```

### 6.5 Escalado de Workers

Modificar en `calculator.py`:
```python
MAX_WORKERS = 8  # Ajustar según CPUs disponibles
```

---

## Archivos Clave para Edición

| Archivo | Qué modificar |
|---------|---------------|
| `calculator.py` | Lógica MRP, KPIs, columnas |
| `data_loader.py` | Parseo de Excel, nuevas hojas |
| `engine.py` | Nuevos endpoints API |
| `app.js` | Lógica frontend, llamadas API |
| `index.html` | Estructura UI, nuevos controles |
| `styles.css` | Estilos, colores, layout |
