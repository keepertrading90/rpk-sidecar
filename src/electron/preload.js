/**
 * preload.js - Context Bridge para Electron
 * RPK Producción - Arquitectura Sidecar
 * 
 * Expone APIs seguras al renderer process
 */

const { contextBridge, ipcRenderer } = require('electron');

// Exponer APIs al renderer
contextBridge.exposeInMainWorld('electronAPI', {
    // Obtener la URL de la API del backend
    getApiUrl: () => ipcRenderer.invoke('get-api-url'),

    // Obtener la ruta de datos por defecto
    getDefaultDataPath: () => ipcRenderer.invoke('get-default-data-path'),

    // Verificar si el backend está listo
    isBackendReady: () => ipcRenderer.invoke('is-backend-ready'),

    // Escuchar eventos del main process
    onReloadData: (callback) => ipcRenderer.on('reload-data', callback)
});

// Indicar que preload se ejecutó correctamente
console.log('✅ Preload script cargado');
