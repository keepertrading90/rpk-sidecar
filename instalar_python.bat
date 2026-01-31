@echo off
chcp 65001 > nul
title Instalación de Python Embebido
echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║         Instalación de Python Embebido                    ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%runtime\python"
set "PYTHON_VERSION=3.11.7"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "PIP_URL=https://bootstrap.pypa.io/get-pip.py"

REM Crear directorio runtime/python
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"

REM Verificar si ya está instalado
if exist "%PYTHON_DIR%\python.exe" (
    echo [INFO] Python ya está instalado en: %PYTHON_DIR%
    "%PYTHON_DIR%\python.exe" --version
    goto :instalar_deps
)

echo [INFO] Descargando Python %PYTHON_VERSION% embebido...
echo [INFO] URL: %PYTHON_URL%

REM Descargar Python embebido usando PowerShell
powershell -Command "& {Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%TEMP%\python-embed.zip'}"
if errorlevel 1 (
    echo [ERROR] Error al descargar Python
    pause
    exit /b 1
)

echo [INFO] Extrayendo Python...
powershell -Command "& {Expand-Archive -Path '%TEMP%\python-embed.zip' -DestinationPath '%PYTHON_DIR%' -Force}"
if errorlevel 1 (
    echo [ERROR] Error al extraer Python
    pause
    exit /b 1
)

REM Habilitar pip en Python embebido
echo [INFO] Configurando Python embebido para pip...
echo import site >> "%PYTHON_DIR%\python311._pth"

REM Descargar e instalar pip
echo [INFO] Instalando pip...
powershell -Command "& {Invoke-WebRequest -Uri '%PIP_URL%' -OutFile '%TEMP%\get-pip.py'}"
"%PYTHON_DIR%\python.exe" "%TEMP%\get-pip.py" --no-warn-script-location

:instalar_deps
echo.
echo [INFO] Instalando dependencias del proyecto...
cd /d "%SCRIPT_DIR%src\backend"
"%PYTHON_DIR%\python.exe" -m pip install -r requirements.txt --no-warn-script-location

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║              Instalación Completada                        ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
echo Python instalado en: %PYTHON_DIR%
"%PYTHON_DIR%\python.exe" --version
echo.
echo Ahora puede ejecutar: iniciar_app.bat
echo.

pause
