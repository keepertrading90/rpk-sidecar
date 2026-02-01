/**
 * main.js - Entry Point de Electron
 * RPK Producción - Arquitectura Sidecar
 * 
 * Funcionalidades:
 * - Spawns del proceso Python al iniciar
 * - Captura del puerto del backend vía stdout
 * - Cleanup del proceso Python al cerrar
 */

// Electron's built-in modules are available when running inside Electron
// The npm 'electron' package just exports the path to the executable
const { app, BrowserWindow, Menu, ipcMain } = require('electron');

const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// Variables globales
let mainWindow = null;
let pyProc = null;
let apiPort = null;
let isQuitting = false;

// ============================================
// GESTIÓN DEL PROCESO PYTHON
// ============================================

function findPythonPath() {
    // Buscar Python en orden de prioridad:
    // 1. runtime/python (Python embebido en rpk-sidecar)
    const embeddedPython = path.join(__dirname, 'runtime', 'python', 'python.exe');
    if (fs.existsSync(embeddedPython)) {
        return embeddedPython;
    }

    // 2. Python en PATH del sistema
    return 'python';
}

function startPythonBackend() {
    return new Promise((resolve, reject) => {
        const backendPath = path.join(__dirname, 'src', 'backend', 'engine.py');
        const pythonPath = findPythonPath();

        console.log('🚀 Iniciando backend Python...');
        console.log(`   Python: ${pythonPath}`);
        console.log(`   Script: ${backendPath}`);

        // Spawn del proceso Python
        pyProc = spawn(pythonPath, [backendPath], {
            cwd: path.join(__dirname, 'src', 'backend'),
            stdio: ['pipe', 'pipe', 'pipe']
        });

        let portFound = false;

        // Escuchar stdout para capturar el puerto
        pyProc.stdout.on('data', (data) => {
            const output = data.toString();
            console.log(`[Python] ${output}`);

            // Buscar el mensaje BACKEND_READY|PORT=XXXX
            const match = output.match(/BACKEND_READY\|PORT=(\d+)/);
            if (match && !portFound) {
                portFound = true;
                apiPort = parseInt(match[1]);
                console.log(`✅ Backend listo en puerto: ${apiPort}`);
                resolve(apiPort);
            }
        });

        // Escuchar stderr
        pyProc.stderr.on('data', (data) => {
            const output = data.toString();
            // Uvicorn escribe info en stderr
            console.log(`[Python stderr] ${output}`);
        });

        // Manejar errores
        pyProc.on('error', (err) => {
            console.error('❌ Error al iniciar Python:', err);
            reject(err);
        });

        // Manejar cierre inesperado
        pyProc.on('close', (code) => {
            if (!isQuitting) {
                console.log(`⚠️ Proceso Python cerrado con código: ${code}`);
                pyProc = null;
            }
        });

        // Timeout si el backend no responde
        setTimeout(() => {
            if (!portFound) {
                reject(new Error('Timeout esperando al backend Python. Ejecute instalar_python.bat primero.'));
            }
        }, 30000); // 30 segundos de timeout
    });
}

function stopPythonBackend() {
    if (pyProc) {
        console.log('🛑 Deteniendo backend Python...');
        isQuitting = true;

        // En Windows, tree-kill para asegurar que mueren todos los procesos hijos
        if (process.platform === 'win32') {
            spawn('taskkill', ['/pid', pyProc.pid.toString(), '/f', '/t']);
        } else {
            pyProc.kill('SIGTERM');
        }

        pyProc = null;
        console.log('✅ Backend Python detenido');
    }
}

// ============================================
// VENTANA PRINCIPAL
// ============================================

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        icon: path.join(__dirname, 'assets', 'icon_v1.png'),
        backgroundColor: '#F7F7F7',
        webPreferences: {
            preload: path.join(__dirname, 'src', 'electron', 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true
        },
        show: false
    });

    // Cargar la interfaz
    mainWindow.loadFile(path.join(__dirname, 'src', 'frontend', 'index.html'));

    // Mostrar cuando esté lista
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        console.log('🖥️ Ventana principal mostrada');
    });

    // Crear menú
    createMenu();

    // Manejar cierre
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function createMenu() {
    const template = [
        {
            label: 'Archivo',
            submenu: [
                {
                    label: 'Recargar Datos',
                    accelerator: 'CmdOrCtrl+R',
                    click: () => {
                        mainWindow.webContents.send('reload-data');
                    }
                },
                { type: 'separator' },
                {
                    label: 'Salir',
                    accelerator: 'CmdOrCtrl+Q',
                    click: () => {
                        app.quit();
                    }
                }
            ]
        },
        {
            label: 'Ver',
            submenu: [
                {
                    label: 'Actualizar Pantalla',
                    accelerator: 'F5',
                    click: () => {
                        mainWindow.reload();
                    }
                },
                {
                    label: 'Pantalla Completa',
                    accelerator: 'F11',
                    click: () => {
                        mainWindow.setFullScreen(!mainWindow.isFullScreen());
                    }
                },
                { type: 'separator' },
                {
                    label: 'DevTools',
                    accelerator: 'CmdOrCtrl+Shift+I',
                    click: () => {
                        mainWindow.webContents.toggleDevTools();
                    }
                }
            ]
        },
        {
            label: 'Ayuda',
            submenu: [
                {
                    label: 'Acerca de',
                    click: () => {
                        const { dialog } = require('electron');
                        dialog.showMessageBox(mainWindow, {
                            type: 'info',
                            title: 'Acerca de RPK Producción',
                            message: 'RPK Producción v1.0.0',
                            detail: 'Sistema de Secuenciación de Producción\nArquitectura Sidecar\n\n© 2026 RPK S COOP'
                        });
                    }
                }
            ]
        }
    ];

    const menu = Menu.buildFromTemplate(template);
    Menu.setApplicationMenu(menu);
}

// ============================================
// IPC HANDLERS
// ============================================

function setupIPC() {
    // Obtener la URL de la API
    ipcMain.handle('get-api-url', () => {
        return `http://localhost:${apiPort}`;
    });

    // Obtener la ruta de datos por defecto
    ipcMain.handle('get-default-data-path', () => {
        // Ruta a la carpeta de datos del proyecto RPK_APS existente
        return path.join(
            'C:', 'Users', 'ismael.rodriguez',
            'OneDrive - RPK S COOP', 'PRODUCCION', 'SALIDA',
            'RPK_APS', 'app', 'data'
        );
    });

    // Verificar si el backend está activo
    ipcMain.handle('is-backend-ready', () => {
        return pyProc !== null && apiPort !== null;
    });
}

// ============================================
// CICLO DE VIDA DE LA APP
// ============================================

app.whenReady().then(async () => {
    console.log('📱 Aplicación Electron iniciando...');

    setupIPC();

    try {
        // Iniciar backend Python primero
        await startPythonBackend();

        // Luego crear la ventana
        createWindow();

    } catch (error) {
        console.error('❌ Error al iniciar:', error);

        const { dialog } = require('electron');
        dialog.showErrorBox(
            'Error de Inicio',
            `No se pudo iniciar el backend Python.\n\nError: ${error.message}\n\nEjecute instalar_python.bat para instalar Python.`
        );

        app.quit();
    }
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('will-quit', () => {
    // Asegurar que el proceso Python se detenga
    stopPythonBackend();
});

app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    }
});

// Manejar errores no capturados
process.on('uncaughtException', (error) => {
    console.error('Error no capturado:', error);
    stopPythonBackend();
});
