@echo off
title Sistema de Turnos — Somos Internet
color 0A

echo ============================================
echo   SISTEMA DE TURNOS SOPORTE TECNICO
echo   Somos Internet - Coordinacion Brayan
echo ============================================
echo.

:: Verificar si Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado.
    echo Descarga Python desde: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Crear entorno virtual si no existe
if not exist "venv" (
    echo Creando entorno virtual...
    python -m venv venv
    echo OK
)

:: Activar entorno virtual
call venv\Scripts\activate

:: Instalar dependencias si no estan instaladas
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    pip install -r requirements.txt -q
    echo OK
)

:: Configurar variables
set FLASK_ENV=development
set DATABASE_URL=sqlite:///turnos_soporte.db
set SECRET_KEY=somos-internet-turnos-2026

echo.
echo Iniciando servidor...
echo.
echo ============================================
echo   Abre tu navegador en:
echo   http://localhost:5000
echo ============================================
echo.
echo Presiona Ctrl+C para detener el servidor
echo.

:: Abrir navegador automaticamente (esperar 2 segundos)
timeout /t 2 /nobreak >nul
start http://localhost:5000

:: Iniciar Flask
python app.py

pause
