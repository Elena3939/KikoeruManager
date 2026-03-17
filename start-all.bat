@echo off
title Prekikoeru Launcher
echo ========================================
echo Prekikoeru All-in-One Launcher
echo ========================================
echo.

set "PYTHON_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python not found!
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [ERROR] Frontend not installed!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

if exist "backend\venv\Scripts\python.exe" (
    backend\venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Existing backend venv is invalid, recreating...
        rmdir /s /q "backend\venv"
    )
)
if not exist "backend\venv\Scripts\python.exe" (
    echo [INFO] Creating backend virtual environment...
    pushd "backend"
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        popd
        echo [ERROR] Failed to create backend virtual environment
        pause
        exit /b 1
    )
    popd
)
pushd "backend"
venv\Scripts\python.exe -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    popd
    echo [ERROR] Failed to initialize pip in backend virtual environment
    pause
    exit /b 1
)
venv\Scripts\python.exe -c "import click,uvicorn,fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Backend dependencies incomplete, repairing...
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        popd
        echo [ERROR] Failed to install backend dependencies
        pause
        exit /b 1
    )
)
popd

echo Starting all services...
echo.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 8000: %%P
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 5173: %%P
    taskkill /PID %%P /F >nul 2>&1
)

start "Prekikoeru Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\python.exe -m app.main"

timeout /t 3 /nobreak >nul

start "Prekikoeru Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo ========================================
echo Services started!
echo ========================================
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo Docs:     http://localhost:8000/docs
echo.
echo Close the popup windows to stop services
echo.
pause
