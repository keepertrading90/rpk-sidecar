@echo off
chcp 65001 > nul
title Instalación de Dependencias
echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║         Instalación de Dependencias Node.js                ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"
set "RUNTIME_DIR=%SCRIPT_DIR%..\RPK_APS\runtime"

REM Agregar runtime al PATH para esta sesión
set "PATH=%RUNTIME_DIR%;%PATH%"

echo [INFO] Usando Node.js desde: %RUNTIME_DIR%
"%RUNTIME_DIR%\node.exe" --version

echo.
echo [INFO] Instalando dependencias...
cd /d "%SCRIPT_DIR%"

REM Establecer variable de entorno para que npm encuentre node
set "NODE=%RUNTIME_DIR%\node.exe"

"%RUNTIME_DIR%\npm.cmd" install

echo.
if errorlevel 1 (
    echo [ERROR] Hubo un error durante la instalación.
) else (
    echo [OK] Dependencias instaladas correctamente.
)

pause
