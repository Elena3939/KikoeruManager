@echo off
set ICON_PATH=D:\Tool\0edba671-6c04-463c-9b4f-7f1cec565830.ico
set PROJECT_NAME=Prekikoeru

echo ========================================
echo   Prekikoeru 打包脚本
echo ========================================

echo [1/3] 正在构建前端 (Vue)...
cd frontend
call npm install
call npm run build
if %errorlevel% neq 0 (
    echo 前端构建失败!
    pause
    exit /b %errorlevel%
)
cd ..

echo [2/3] 确保安装必要的 Python 包...
pip install pyinstaller pystray Pillow uvicorn fastapi sqlalchemy pydantic-settings pyyaml watchdog filetype requests httpx python-multipart aiofiles websockets apscheduler aiohttp opencc-python-reimplemented croniter

echo [3/3] 正在使用 PyInstaller 打包...
echo 这可能需要几分钟，请稍候...

pyinstaller --onefile --noconsole ^
    --icon="%ICON_PATH%" ^
    --add-data "backend;backend" ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "%ICON_PATH%;." ^
    --name %PROJECT_NAME% ^
    --clean ^
    desktop_app.py

if %errorlevel% neq 0 (
    echo 打包失败!
    pause
    exit /b %errorlevel%
)

echo ========================================
echo   打包完成!
echo   可执行文件位于：dist\%PROJECT_NAME%.exe
echo ========================================
pause
