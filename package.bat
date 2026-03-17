@echo off
set ICON_PATH=D:\Tool\0edba671-6c04-463c-9b4f-7f1cec565830.ico
set PROJECT_NAME=kikoeruTool

echo ========================================
echo   Kikoeru Tool 打包脚本
echo ========================================

echo [1/4] 正在构建前端 (Vue)...
cd frontend
call npm install
call npm run build
if %errorlevel% neq 0 (
    echo 前端构建失败!
    pause
    exit /b %errorlevel%
)
cd ..

echo [2/4] 正在准备静态文件...
if exist static rd /s /q static
mkdir static
xcopy /e /y frontend\dist\* static\

echo [3/4] 正在复制图标...
copy /y "%ICON_PATH%" app_icon.ico

echo [4/4] 正在使用 PyInstaller 打包为单 EXE...
echo 这可能需要几分钟，请稍候...

rem 确保安装了必要的打包工具和运行依赖
pip install pyinstaller pystray Pillow uvicorn fastapi sqlalchemy pydantic-settings pyyaml watchdog filetype requests httpx python-multipart aiofiles websockets apscheduler aiohttp opencc-python-reimplemented croniter

pyinstaller --onefile --noconsole ^
    --icon="%ICON_PATH%" ^
    --add-data "static;static" ^
    --add-data "app_icon.ico;." ^
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
echo   可执行文件位于: dist\%PROJECT_NAME%.exe
echo ========================================
pause
