@echo off
setlocal
title Prekikoeru Setup
set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "CONDA_PREFIX="
set "CONDA_DEFAULT_ENV="
set "NPM_CONFIG_PREFIX="
set "npm_config_prefix="
echo ========================================
echo Prekikoeru Setup Wizard
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
echo [OK] Python found

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found!
    echo Please install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

set "NPM_CMD="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do (
    if not defined NPM_CMD set "NPM_CMD=%%~fP"
)
if not defined NPM_CMD if exist "C:\Program Files\nodejs\npm.cmd" set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"
if not defined NPM_CMD if exist "%APPDATA%\npm\npm.cmd" set "NPM_CMD=%APPDATA%\npm\npm.cmd"
if not defined NPM_CMD (
    echo [ERROR] npm.cmd not found!
    echo Please reinstall Node.js and ensure npm is available.
    pause
    exit /b 1
)
call "%NPM_CMD%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm check failed: %NPM_CMD%
    pause
    exit /b 1
)

echo.
echo [1/4] Creating directories...
if not exist "test_data\input" mkdir test_data\input
if not exist "test_data\library" mkdir test_data\library
if not exist "test_data\temp" mkdir test_data\temp
if not exist "data" mkdir data
echo [OK] Directories created

echo.
echo [2/4] Installing backend dependencies...
cd backend
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment is invalid, recreating...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
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
echo Installing Python packages...
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend install failed
    pause
    exit /b 1
)
venv\Scripts\python.exe -c "import click,uvicorn,fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Backend dependencies incomplete, retrying installation...
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Backend dependency repair failed
        pause
        exit /b 1
    )
)
cd ..
echo [OK] Backend installed

echo.
echo [3/4] Installing frontend dependencies...
cd frontend
if not exist "node_modules" (
    echo Installing npm packages...
    call "%NPM_CMD%" install
    if errorlevel 1 (
        echo [ERROR] Frontend install failed
        pause
        exit /b 1
    )
)
cd ..
echo [OK] Frontend installed

echo.
echo [4/4] Checking configuration...
echo [OK] Configuration checked

echo.
echo ========================================
echo Setup complete!
echo ========================================
echo.
echo To start:
echo   1. Double-click start-all.bat (Recommended)
echo   2. Or use backend\start.bat + frontend\start.bat
echo.
echo Access:
echo   Frontend: http://localhost:5556
echo   Backend:  http://localhost:5555
echo   API Docs: http://localhost:5555/docs
echo.
popd
pause
