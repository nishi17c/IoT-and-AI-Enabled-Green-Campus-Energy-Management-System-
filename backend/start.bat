@echo off
:: ============================================================
::  Green Campus Energy Management System — Windows Start Script
::  Double-click this file to start the entire backend stack.
:: ============================================================

:: Enable colour output (requires Windows 10 1511+)
chcp 65001 >nul

echo.
echo  ============================================================
echo   ____ ____  _____  _____ _   _   _____  __  __ ____
echo  / ___|  _ \| ____|/ ____| \ | | | ____||  \/  / ___|
echo | |  _| |_) |  _| | |___ |  \| | |  _|  | |\/| \___ \
echo | |_| |  _ ^<| |___|  ___^|| |\  | | |___ | |  | |___) ^|
echo  \____|_| \_\_____|\_____^||_| \_| |_____||_|  |_|____/
echo.
echo   IoT ^& AI Enabled Green Campus Energy Management System
echo  ============================================================
echo.

:: ---------------------------------------------------------------
:: Step 1 — Check and start Mosquitto MQTT broker
:: ---------------------------------------------------------------
echo  [1/3] Checking Mosquitto MQTT Broker...

sc query mosquitto >nul 2>&1
if %errorlevel% equ 0 (
    echo        Mosquitto service found.
    sc query mosquitto | find "RUNNING" >nul 2>&1
    if %errorlevel% equ 0 (
        echo  [OK]   Mosquitto is already running.
    ) else (
        echo  [>>]   Starting Mosquitto service...
        net start mosquitto >nul 2>&1
        if %errorlevel% equ 0 (
            echo  [OK]   Mosquitto started successfully.
        ) else (
            echo  [!!]   Could not start Mosquitto service. Trying direct launch...
            start /B "" "C:\Program Files\mosquitto\mosquitto.exe" -v
            timeout /t 2 /nobreak >nul
            echo  [OK]   Mosquitto launched directly. Check a new window if needed.
        )
    )
) else (
    :: Service not installed — try running the executable directly
    echo  [!!]   Mosquitto service not found. Trying direct launch...
    if exist "C:\Program Files\mosquitto\mosquitto.exe" (
        start /B "" "C:\Program Files\mosquitto\mosquitto.exe" -v
        timeout /t 2 /nobreak >nul
        echo  [OK]   Mosquitto launched from default install path.
    ) else (
        echo  [!!]   Mosquitto not found!
        echo         Please install it from https://mosquitto.org/download/
        echo         or run:  winget install EclipseFoundation.Mosquitto
        echo.
        echo         Press any key to continue anyway (API will still start).
        pause >nul
    )
)

echo.

:: ---------------------------------------------------------------
:: Step 2 — Install Python dependencies
:: ---------------------------------------------------------------
echo  [2/3] Installing Python dependencies from requirements.txt...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERR]  Python not found in PATH!
    echo         Download Python 3.8+ from https://www.python.org/downloads/
    echo         Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

cd /d "%~dp0"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

if %errorlevel% equ 0 (
    echo  [OK]   All packages installed.
) else (
    echo  [ERR]  pip install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.

:: ---------------------------------------------------------------
:: Step 3 — Start FastAPI server
:: ---------------------------------------------------------------
echo  [3/3] Starting FastAPI server...
echo.
echo  ============================================================
echo   Access points:
echo     Dashboard  : http://localhost:8000
echo     API Docs   : http://localhost:8000/docs
echo     WebSocket  : ws://localhost:8000/ws
echo  ============================================================
echo.
echo   Press Ctrl+C to stop the server.
echo.

python server.py

:: If the server exits, pause so the window doesn't close immediately
echo.
echo  Server stopped. Press any key to close this window.
pause >nul
