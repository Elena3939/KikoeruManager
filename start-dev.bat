@echo off
chcp 65001 >nul
title Prekikoeru 开发服务器

echo ========================================
echo    Prekikoeru Local Dev Server
echo ========================================
echo.

REM Check Python
set "PYTHON_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)
echo [OK] Python found

REM Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+
    pause
    exit /b 1
)
echo [OK] Node.js found

REM Check 7z
where 7z >nul 2>&1
if errorlevel 1 (
    echo [WARNING] 7-Zip not found. Extraction may not work properly.
) else (
    echo [OK] 7-Zip found
)

REM Create directories
if not exist "test_data\input" mkdir test_data\input
if not exist "test_data\library" mkdir test_data\library
if not exist "test_data\temp" mkdir test_data\temp
if not exist "data" mkdir data
echo [OK] Directories created

echo.
echo [0/4] Cleaning old processes on required ports...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 8000: %%P
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 5173: %%P
    taskkill /PID %%P /F >nul 2>&1
)
echo [OK] Ports cleaned

echo.
echo [1/4] Setting up Python environment...
cd backend
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Existing virtual environment is invalid, recreating...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
)
venv\Scripts\python.exe -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to initialize pip in virtual environment
    pause
    exit /b 1
)
venv\Scripts\python.exe -c "import click,uvicorn,fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Backend dependencies incomplete, repairing...
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install backend dependencies
        pause
        exit /b 1
    )
)
cd ..
echo [OK] Backend ready

echo.
echo [2/4] Checking frontend dependencies...
cd frontend
if not exist "node_modules" (
    echo Installing npm packages...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies
        pause
        exit /b 1
    )
)
cd ..
echo [OK] Frontend ready

echo.
echo [3/4] Starting services...
echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo API Docs: http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop
echo.

REM Start backend in new window
start "Prekikoeru Backend" cmd /k "cd %CD%\backend && venv\Scripts\python.exe -m app.main"

REM Wait for backend
timeout /t 3 /nobreak >nul

REM Start frontend
cd frontend
npm run dev

echo.
echo Stopping services...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1

echo.
echo Services stopped
echo.
pause
