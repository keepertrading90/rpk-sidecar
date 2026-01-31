@echo off
chcp 65001 > nul
title RPK Producción - Sidecar
echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║       RPK Producción - Sistema de Secuenciación           ║
echo ║                   Arquitectura Sidecar V2.0               ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM Configurar rutas
set "SCRIPT_DIR=%~dp0"
set "RUNTIME_DIR=%SCRIPT_DIR%runtime"
set "PYTHON_DIR=%SCRIPT_DIR%runtime\python"
set "RPK_APS_DIR=C:\Users\ismael.rodriguez\OneDrive - RPK S COOP\PRODUCCION\SALIDA\RPK_APS"
set "ELECTRON_PATH=%RPK_APS_DIR%\node_modules\electron\dist\electron.exe"

REM Añadir runtime al PATH
set "PATH=%RUNTIME_DIR%;%PYTHON_DIR%;%PATH%"

REM Verificar Node.js
echo [INFO] Verificando Node.js...
if exist "%RUNTIME_DIR%\node.exe" (
    echo [OK] Node.js encontrado en runtime
) else (
    echo [ERROR] Node.js no encontrado
    pause
    exit /b 1
)

REM Verificar Python
echo [INFO] Verificando Python...
if exist "%PYTHON_DIR%\python.exe" (
    echo [OK] Python encontrado en runtime/python
) else (
    echo [AVISO] Python no encontrado en runtime
)

REM Cambiar al directorio de RPK_APS para que Node encuentre el módulo electron correcto
cd /d "%RPK_APS_DIR%"

REM Verificar Electron
echo [INFO] Verificando Electron...
if exist "%ELECTRON_PATH%" (
    echo [OK] Electron encontrado
) else (
    echo [ERROR] Electron no encontrado en RPK_APS
    pause
    exit /b 1
)

REM Iniciar la aplicación pasando la ruta completa a nuestro main.js
echo.
echo [INFO] Iniciando la aplicación...
echo.

"%ELECTRON_PATH%" "%SCRIPT_DIR%main.js"

pause
