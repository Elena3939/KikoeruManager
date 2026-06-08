@echo off
setlocal
chcp 65001 >nul
title KikoeruManager Launcher
echo ========================================
echo KikoeruManager All-in-One Launcher
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
venv\Scripts\python.exe -c "import click,uvicorn,fastapi,orjson,qrcode,litellm,socksio" >nul 2>&1
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

set "RUN_DIR=%~dp0data\run"
set "BACKEND_PID_FILE=%RUN_DIR%\backend-terminal.pid"
set "FRONTEND_PID_FILE=%RUN_DIR%\frontend-terminal.pid"
if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"

echo [INFO] Closing existing KikoeruManager service terminals...
if exist "%BACKEND_PID_FILE%" (
    for /f "usebackq delims=" %%P in ("%BACKEND_PID_FILE%") do (
        echo [INFO] Close previous backend terminal tree: %%P
        taskkill /PID %%P /T /F >nul 2>&1
    )
    del /q "%BACKEND_PID_FILE%" >nul 2>&1
)
if exist "%FRONTEND_PID_FILE%" (
    for /f "usebackq delims=" %%P in ("%FRONTEND_PID_FILE%") do (
        echo [INFO] Close previous frontend terminal tree: %%P
        taskkill /PID %%P /T /F >nul 2>&1
    )
    del /q "%FRONTEND_PID_FILE%" >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$currentPid = $PID; $root = '%~dp0'.TrimEnd('\'); $backend = Join-Path $root 'backend'; $frontend = Join-Path $root 'frontend'; $targets = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $currentPid -and $_.ParentProcessId -ne $currentPid -and $_.Name -in @('cmd.exe','powershell.exe','pwsh.exe') -and ($_.CommandLine -like '*KikoeruManager Backend*' -or $_.CommandLine -like '*KikoeruManager Frontend*' -or ($_.CommandLine -like ('*' + $backend + '*') -and $_.CommandLine -like '*venv\Scripts\python.exe -m app.main*') -or ($_.CommandLine -like ('*' + $frontend + '*') -and $_.CommandLine -like '*npm run dev*')) }; foreach ($target in $targets) { Write-Host ('[INFO] Close terminal tree: PID ' + $target.ProcessId + ' ' + $target.Name); taskkill /PID $($target.ProcessId) /T /F | Out-Null }"
timeout /t 1 /nobreak >nul

set "BAIDUPCS_GO_DIR=%~dp0tools\baidupcs-go"
set "BAIDUPCS_GO_EXE=%BAIDUPCS_GO_DIR%\BaiduPCS-Go.exe"
if exist "%BAIDUPCS_GO_EXE%" (
    set "PATH=%BAIDUPCS_GO_DIR%;%PATH%"
    set "BAIDUPCS_GO_PATH=%BAIDUPCS_GO_EXE%"
    echo [OK] BaiduPCS-Go found: %BAIDUPCS_GO_EXE%
) else (
    echo [INFO] BaiduPCS-Go not found in tools\baidupcs-go
    echo [INFO] Run: powershell -ExecutionPolicy Bypass -File scripts\install-baidupcs-go.ps1
)

if not exist "data\config" mkdir "data\config"
set "CONFIG_PATH=%~dp0data\config\config.yaml"
if not exist "%CONFIG_PATH%" (
    if exist "%~dp0backend\config\config.yaml" copy /Y "%~dp0backend\config\config.yaml" "%CONFIG_PATH%" >nul
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5555" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 5555: %%P
    taskkill /PID %%P /T /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5556" ^| findstr "LISTENING"') do (
    echo [INFO] Stop process on 5556: %%P
    taskkill /PID %%P /T /F >nul 2>&1
)

set "BACKEND_CMD=title KikoeruManager Backend && chcp 65001 >nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && set CONFIG_PATH=%CONFIG_PATH% && set DATA_PATH=%~dp0data && set BAIDUPCS_GO_PATH=%BAIDUPCS_GO_PATH% && set PATH=%BAIDUPCS_GO_DIR%;%PATH% && cd /d "%~dp0backend" && venv\Scripts\python.exe -m app.main"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $env:BACKEND_CMD -PassThru; Set-Content -LiteralPath $env:BACKEND_PID_FILE -Value $p.Id -Encoding ASCII"

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

set "FRONTEND_CMD=title KikoeruManager Frontend && cd /d "%~dp0frontend" && npm run dev"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $env:FRONTEND_CMD -PassThru; Set-Content -LiteralPath $env:FRONTEND_PID_FILE -Value $p.Id -Encoding ASCII"

echo ========================================
echo Services started!
echo ========================================
echo.
echo Backend:  http://localhost:5555
echo Frontend: http://localhost:5556
echo Docs:     http://localhost:5555/docs
echo.
echo Close the popup windows to stop services
echo.
pause
