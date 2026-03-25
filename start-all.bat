@echo off
setlocal
chcp 65001 >nul
title Prekikoeru Launcher
echo ========================================
echo Prekikoeru All-in-One Launcher
echo ========================================
echo.

set "PYTHON_CMD="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PYTHON_CMD (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -%%V"
    )
)
if not defined PYTHON_CMD (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
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

start "Prekikoeru Backend" cmd /k "chcp 65001 >nul && set ""PYTHONUTF8=1"" && set ""PYTHONIOENCODING=utf-8"" && cd /d %~dp0backend && venv\Scripts\python.exe -m app.main"

timeout /t 3 /nobreak >nul

set "NPM_CMD="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do (
    if not defined NPM_CMD set "NPM_CMD=%%~fP"
)
if not defined NPM_CMD if exist "C:\Program Files\nodejs\npm.cmd" set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"
if not defined NPM_CMD if exist "%APPDATA%\npm\npm.cmd" set "NPM_CMD=%APPDATA%\npm\npm.cmd"
if not defined NPM_CMD if exist "%APPDATA%\JetBrains\PyCharm2025.3\node\versions\24.14.0\npm.cmd" set "NPM_CMD=%APPDATA%\JetBrains\PyCharm2025.3\node\versions\24.14.0\npm.cmd"
if not defined NPM_CMD (
    echo [ERROR] npm.cmd not found!
    echo Please reinstall Node.js and ensure npm is available.
    pause
    exit /b 1
)
for %%P in ("%NPM_CMD%") do set "NPM_DIR=%%~dpP"
set "PATH=%NPM_DIR%;%PATH%"
call "%NPM_CMD%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm check failed: %NPM_CMD%
    pause
    exit /b 1
)

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
