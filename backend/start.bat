@echo off
title Prekikoeru Backend
echo ========================================
echo Prekikoeru Backend Server
echo ========================================
echo.
echo Starting backend server...
echo URL: http://localhost:8000
echo Docs: http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop
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

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Existing virtual environment is invalid, recreating...
        rmdir /s /q venv
    )
)
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
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

venv\Scripts\python.exe -m app.main

echo.
echo Server stopped
echo.
pause
