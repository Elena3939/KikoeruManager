@echo off
set ICON_PATH=backend\app.ico
set PROJECT_NAME=Prekikoeru

echo ========================================
echo   Prekikoeru build script
echo ========================================

echo [1/3] Building frontend...
cd frontend
call npm install
call npm run build
if %errorlevel% neq 0 (
    echo Frontend build failed.
    pause
    exit /b %errorlevel%
)
cd ..

echo [2/3] Installing Python packaging dependencies...
pip install pyinstaller pystray Pillow uvicorn fastapi sqlalchemy pydantic-settings pyyaml watchdog filetype requests httpx python-multipart aiofiles websockets apscheduler aiohttp opencc-python-reimplemented croniter

echo [3/3] Packaging with PyInstaller...
echo This may take a few minutes.

pyinstaller --onefile --noconsole ^
    --icon="%ICON_PATH%" ^
    --hidden-import=pystray ^
    --hidden-import=pystray._base ^
    --hidden-import=pystray._win32 ^
    --hidden-import=pystray._util ^
    --hidden-import=pystray._util.win32 ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageDraw ^
    --add-data "backend;backend" ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "%ICON_PATH%;." ^
    --name %PROJECT_NAME% ^
    --clean ^
    desktop_app.py

if %errorlevel% neq 0 (
    echo Packaging failed.
    pause
    exit /b %errorlevel%
)

echo ========================================
echo   Packaging complete
echo   Executable: dist\%PROJECT_NAME%.exe
echo ========================================
pause
