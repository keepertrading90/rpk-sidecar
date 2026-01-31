/**
 * app.js - Cliente API y Lógica de UI
 * RPK Producción - Arquitectura Sidecar
 * 
 * Funcionalidades:
 * - Conexión con backend Python vía fetch
 * - Actualización dinámica del dashboard
 * - Control de simulación
 */

// ============================================
// ESTADO GLOBAL DE LA APLICACIÓN
// ============================================

const AppState = {
    // Configuración de conexión
    apiUrl: 'http://localhost:8000',
    isConnected: false,
    defaultDataPath: '',

    // Parámetros del escenario actual (What-If)
    currentScenario: {
        factor_saturacion: 1.0,
        turno_extra: false,
        horizonte: 30
    },

    // Datos calculados (cache del backend)
    data: {
        secuencia: [],
        saturacion: [],
        kpis: {},
        cuellos_botella: []
    }
};

// ============================================
// UTILIDAD: DEBOUNCE
// ============================================

/**
 * Debounce: Retrasa la ejecución hasta que el usuario deje de interactuar.
 * Evita llamadas excesivas al backend mientras se mueve el slider.
 */
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// ============================================
// INICIALIZACIÓN
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('🚀 Inicializando aplicación...');

    // Obtener URL de la API desde Electron
    if (window.electronAPI) {
        try {
            AppState.apiUrl = await window.electronAPI.getApiUrl();
            AppState.defaultDataPath = await window.electronAPI.getDefaultDataPath();
            console.log(`📡 API URL: ${AppState.apiUrl}`);
            console.log(`📂 Datos: ${AppState.defaultDataPath}`);
        } catch (e) {
            console.warn('No se pudo obtener config de Electron:', e);
        }
    }

    // Configurar eventos
    setupEventListeners();

    // Verificar conexión con el backend
    const connected = await checkConnection();

    // CARGA AUTOMÁTICA: Si hay conexión, cargar datos automáticamente
    if (connected) {
        await loadData();
    } else {
        hideLoading();
    }
});

// ============================================
// CONEXIÓN CON BACKEND
// ============================================

async function checkConnection() {
    updateLoadingText('Verificando conexión con backend...');

    try {
        const response = await fetch(`${AppState.apiUrl}/health`, {
            method: 'GET',
            timeout: 5000
        });

        if (response.ok) {
            const data = await response.json();
            console.log('✅ Backend conectado:', data);
            setConnectionStatus(true);

            // Si ya hay datos cargados, mostrar stats
            if (data.loaded) {
                await loadStats();
            }

            return true;
        }
    } catch (error) {
        console.error('❌ Error de conexión:', error);
        setConnectionStatus(false);
    }

    return false;
}

function setConnectionStatus(connected) {
    AppState.isConnected = connected;
    const statusEl = document.getElementById('backend-status');

    if (connected) {
        statusEl.textContent = '● Motor Python Conectado';
        statusEl.className = 'status-indicator online';
    } else {
        statusEl.textContent = '● Desconectado';
        statusEl.className = 'status-indicator offline';
    }
}

// ============================================
// CARGA DE DATOS
// ============================================

async function loadData() {
    if (!AppState.isConnected) {
        alert('No hay conexión con el backend');
        return;
    }

    const btn = document.getElementById('btn-load-data');
    btn.disabled = true;
    btn.textContent = 'Cargando...';

    showLoading();
    updateLoadingText('Cargando archivos Excel...');

    try {
        const response = await fetch(`${AppState.apiUrl}/init-load`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: AppState.defaultDataPath,
                force_reload: false
            })
        });

        if (!response.ok) {
            throw new Error(`Error ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('✅ Datos cargados:', data);

        // Mostrar estadísticas
        updateDataStats(data.stats);

        // Cargar dashboard
        updateLoadingText('Calculando secuencia...');
        await loadDashboard();

    } catch (error) {
        console.error('Error al cargar datos:', error);
        alert(`Error al cargar datos: ${error.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Cargar Datos';
        hideLoading();
    }
}

async function loadStats() {
    try {
        const response = await fetch(`${AppState.apiUrl}/data/stats`);
        if (response.ok) {
            const data = await response.json();
            if (data.loaded) {
                updateDataStats(data.stats);
            }
        }
    } catch (error) {
        console.error('Error al cargar stats:', error);
    }
}

function updateDataStats(stats) {
    document.getElementById('stat-pedidos').textContent = stats.pedidos || 0;
    document.getElementById('stat-rutas').textContent = stats.rutas_ops || 0;
    document.getElementById('stat-stock').textContent = stats.stock || 0;
    document.getElementById('stat-wip').textContent = stats.wip || 0;

    document.getElementById('data-stats').classList.remove('hidden');
}

// ============================================
// DASHBOARD
// ============================================

async function loadDashboard() {
    try {
        // Cargar KPIs
        const kpisRes = await fetch(`${AppState.apiUrl}/data/kpis`);
        if (kpisRes.ok) {
            const kpis = await kpisRes.json();
            updateKPIs(kpis);
        }

        // Cargar saturación
        const satRes = await fetch(`${AppState.apiUrl}/data/saturacion`);
        if (satRes.ok) {
            const sat = await satRes.json();
            updateSaturacionChart(sat.data);
        }

        // Cargar secuencia
        const seqRes = await fetch(`${AppState.apiUrl}/data/secuencia`);
        if (seqRes.ok) {
            const seq = await seqRes.json();
            updateSecuenciaTable(seq.data);
        }

    } catch (error) {
        console.error('Error al cargar dashboard:', error);
    }
}

function updateKPIs(kpis) {
    document.getElementById('kpi-urgentes').textContent = kpis.articulos_urgentes || 0;
    document.getElementById('kpi-total').textContent = kpis.total_articulos || 0;
    document.getElementById('kpi-saturacion').textContent = `${kpis.saturacion_promedio || 0}%`;
    document.getElementById('kpi-cuellos').textContent = kpis.cuellos_botella_count || 0;
    document.getElementById('kpi-horas').textContent = `${kpis.horas_totales || 0}h`;
    document.getElementById('kpi-centros').textContent = kpis.centros_activos || 0;
}

function updateSaturacionChart(data) {
    const container = document.getElementById('chart-saturacion-container');

    if (!data || data.length === 0) {
        container.innerHTML = '<p class="placeholder-text">No hay datos de saturación</p>';
        return;
    }

    // Limitar a los primeros 10 centros
    const topCentros = data.slice(0, 10);

    let html = '<div class="saturacion-bars">';

    for (const item of topCentros) {
        const pct = Math.min(150, item.saturacion_pct || 0);
        const displayPct = Math.min(100, pct);

        let barClass = 'ok';
        if (pct > 100) barClass = 'danger';
        else if (pct > 80) barClass = 'warning';

        html += `
            <div class="saturacion-bar">
                <div class="saturacion-bar-header">
                    <span class="saturacion-bar-label">${item.centro}</span>
                    <span class="saturacion-bar-value">${item.saturacion_pct.toFixed(1)}%</span>
                </div>
                <div class="saturacion-bar-track">
                    <div class="saturacion-bar-fill ${barClass}" style="width: ${displayPct}%"></div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

/**
 * Renderiza los cuellos de botella (centros con saturación > 100%)
 * Phase 3: Visualización de alertas críticas
 */
function updateCuellosBotella(data) {
    const container = document.getElementById('cuellos-container');
    if (!container) {
        console.warn('⚠️ Contenedor #cuellos-container no encontrado');
        return;
    }

    // Guardar en estado
    AppState.data.cuellos_botella = data || [];

    if (!data || data.length === 0) {
        container.innerHTML = `
            <div class="cuellos-status success">
                <span class="cuellos-icon">✅</span>
                <span class="cuellos-text">Sin cuellos de botella detectados</span>
            </div>
        `;
        return;
    }

    // Ordenar por saturación descendente
    const sorted = [...data].sort((a, b) => (b.saturacion_pct || 0) - (a.saturacion_pct || 0));

    let html = `
        <div class="cuellos-status danger">
            <span class="cuellos-icon">⚠️</span>
            <span class="cuellos-text">${sorted.length} cuello(s) de botella detectado(s)</span>
        </div>
        <ul class="cuellos-list">
    `;

    for (const cuello of sorted) {
        const pct = cuello.saturacion_pct?.toFixed(1) || '100+';
        const severity = cuello.saturacion_pct > 120 ? 'critical' : 'warning';

        html += `
            <li class="cuello-item ${severity}">
                <span class="cuello-centro">${cuello.centro}</span>
                <span class="cuello-pct">${pct}%</span>
            </li>
        `;
    }

    html += '</ul>';
    container.innerHTML = html;
}

function updateSecuenciaTable(data) {
    const tbody = document.getElementById('table-secuencia-body');
    if (!tbody) return;

    if (!data || data.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="placeholder-text">No hay datos de secuencia</td>
            </tr>
        `;
        return;
    }

    // Limitar a las primeras 100 filas para rendimiento
    const rows = data.slice(0, 100);

    let html = '';

    for (const item of rows) {
        // Determinar clase de badge según estado
        let badgeClass = 'badge-ok';
        if (item.estado === 'URGENTE') badgeClass = 'badge-urgente';
        else if (item.estado === 'NORMAL') badgeClass = 'badge-normal';

        // Calcular carga en horas (usar campo existente o calcular)
        const cargaHoras = item.carga_horas || item.tiempo_total || 0;

        html += `
            <tr>
                <td>${item.orden || '-'}</td>
                <td style="font-family: monospace; color: var(--text-secondary);">${item.numero_of || '-'}</td>
                <td><strong>${item.articulo || '-'}</strong></td>
                <td>${item.centro || '-'}</td>
                <td>${Math.round(item.cantidad || 0).toLocaleString()}</td>
                <td><span class="badge ${badgeClass}">${item.estado || 'N/A'}</span></td>
                <td>${typeof cargaHoras === 'number' ? cargaHoras.toFixed(2) : cargaHoras} h</td>
            </tr>
        `;
    }

    tbody.innerHTML = html;

    // Actualizar KPI de total de órdenes
    const kpiTotal = document.getElementById('kpi-total');
    if (kpiTotal) kpiTotal.textContent = data.length;
}

// ============================================
// SIMULACIÓN
// ============================================

async function runSimulation() {
    if (!AppState.isConnected) {
        alert('No hay conexión con el backend');
        return;
    }

    const btn = document.getElementById('btn-simulate');
    btn.disabled = true;
    btn.textContent = 'Simulando...';

    const factorSaturacion = parseFloat(document.getElementById('slider-saturacion').value);
    const turnoExtra = document.getElementById('check-turno-extra').checked;
    const horizonte = parseInt(document.getElementById('input-horizonte').value);

    try {
        const response = await fetch(`${AppState.apiUrl}/simulate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                factor_saturacion: factorSaturacion,
                turno_extra: turnoExtra,
                horizonte: horizonte
            })
        });

        if (!response.ok) {
            throw new Error(`Error ${response.status}`);
        }

        const result = await response.json();
        console.log('✅ Simulación completada:', result);

        // Guardar en estado global (Phase 1 pattern)
        AppState.data.kpis = result.kpis || {};
        AppState.data.saturacion = result.saturacion || [];
        AppState.data.secuencia = result.secuencia || [];
        AppState.data.cuellos_botella = result.cuellos_botella || [];

        // Actualizar dashboard con resultados
        updateKPIs(result.kpis);
        updateSaturacionChart(result.saturacion);
        updateSecuenciaTable(result.secuencia);
        updateCuellosBotella(result.cuellos_botella); // Phase 3

    } catch (error) {
        console.error('Error en simulación:', error);
        alert(`Error en simulación: ${error.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Simular';
    }
}

// ============================================
// EVENT LISTENERS
// ============================================

function setupEventListeners() {
    // Botón Recargar Datos (nuevo ID)
    const btnReload = document.getElementById('btn-reload');
    if (btnReload) {
        btnReload.addEventListener('click', loadData);
    }

    // Botón Simular (manual)
    document.getElementById('btn-simulate').addEventListener('click', runSimulation);

    // ==========================================
    // SLIDERS REACTIVOS (Phase 2)
    // ==========================================

    // Crear versión debounced de runSimulation (500ms delay)
    const debouncedSimulation = debounce(() => {
        console.log('🔄 Auto-simulación por cambio de parámetros...');
        runSimulation();
    }, 500);

    // Slider Saturación - Reactivo (nuevo ID: input-saturation)
    const sliderSat = document.getElementById('input-saturation');
    const valueSat = document.getElementById('val-saturation');
    if (sliderSat && valueSat) {
        sliderSat.addEventListener('input', () => {
            valueSat.textContent = sliderSat.value;
            AppState.currentScenario.factor_saturacion = parseFloat(sliderSat.value);
            debouncedSimulation(); // Auto-simular tras 500ms de inactividad
        });
    }

    // Checkbox Turno Extra - Reactivo (inmediato)
    const checkTurno = document.getElementById('check-turno-extra');
    checkTurno.addEventListener('change', (e) => {
        AppState.currentScenario.turno_extra = e.target.checked;
        console.log(`🔧 Turno extra: ${e.target.checked ? 'Activado' : 'Desactivado'}`);
        runSimulation(); // Inmediato al cambiar checkbox
    });

    // Input Horizonte - Reactivo
    const inputHorizonte = document.getElementById('input-horizonte');
    if (inputHorizonte) {
        inputHorizonte.addEventListener('change', (e) => {
            AppState.currentScenario.horizonte = parseInt(e.target.value) || 30;
            console.log(`📅 Horizonte: ${AppState.currentScenario.horizonte} días`);
            runSimulation();
        });
    }

    // Escuchar eventos de Electron
    if (window.electronAPI) {
        window.electronAPI.onReloadData(() => {
            console.log('♻️ Recargando datos...');
            loadData();
        });
    }
}

// ============================================
// UTILIDADES DE UI
// ============================================

function showLoading() {
    document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

function updateLoadingText(text) {
    document.getElementById('loading-text').textContent = text;
}

// ============================================
// POLLING (Reconexión automática)
// ============================================

// Verificar conexión cada 30 segundos
setInterval(async () => {
    if (!AppState.isConnected) {
        const reconnected = await checkConnection();
        if (reconnected) {
            console.log('♻️ Reconectado al backend');
        }
    }
}, 30000);
