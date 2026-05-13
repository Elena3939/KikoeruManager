@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
set "ROOT=%cd%"
set "PROJECT_NAME=KikoeruManager"

REM ========================================
REM 应用程序图标路径配置
REM 可自定义图标路径
REM ========================================
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "ICON_PNG=%FRONTEND%\src\assets\icon\appIcon.png"
set "ICON_ICO=%BACKEND%\build\appIcon.ico"
set "PYTHON_EXE=%BACKEND%\venv\Scripts\python.exe"
set "DIST_EXE=%BACKEND%\dist\%PROJECT_NAME%.exe"
set "TARGET_EXE=%ROOT%\..\%PROJECT_NAME%.exe"

if not exist "%PYTHON_EXE%" (
  echo 未找到后端虚拟环境: %PYTHON_EXE%
  echo 请先运行 setup.bat 安装依赖
  exit /b 1
)

if not exist "%ICON_PNG%" (
  echo 未找到图标文件: %ICON_PNG%
  exit /b 1
)

pushd "%FRONTEND%"
if not exist "node_modules" (
  call npm.cmd install
  if errorlevel 1 (
    popd
    echo 前端依赖安装失败
    exit /b 1
  )
)
call npm.cmd run build
if errorlevel 1 (
  popd
  echo 前端构建失败
  exit /b 1
)
popd

pushd "%BACKEND%"
call "%PYTHON_EXE%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  popd
  echo 后端依赖安装失败
  exit /b 1
)

call "%PYTHON_EXE%" -m pip install pyinstaller --disable-pip-version-check
if errorlevel 1 (
  popd
  echo PyInstaller 安装失败
  exit /b 1
)

call "%PYTHON_EXE%" -c "import pystray, PIL, qrcode; print('pystray/qrcode ok')"
if errorlevel 1 (
  popd
  echo 依赖校验失败: pystray/Pillow/qrcode 未正确安装
  exit /b 1
)

if not exist "build" mkdir build
call "%PYTHON_EXE%" -c "from PIL import Image; img=Image.open(r'%ICON_PNG%').convert('RGBA'); sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]; img.save(r'%ICON_ICO%', format='ICO', sizes=sizes)"
if errorlevel 1 (
  popd
  echo 图标转换失败: %ICON_PNG%
  exit /b 1
)

call "%PYTHON_EXE%" -m PyInstaller --onefile --noconsole --clean --name "%PROJECT_NAME%" --icon "%ICON_ICO%" --distpath "dist" --workpath "build" --specpath "." --paths "%ROOT%" --hidden-import pystray --hidden-import PIL --hidden-import PIL.Image --hidden-import qrcode --hidden-import qrcode.image.pil --hidden-import orjson --add-data "..\frontend\dist;frontend/dist" --add-data "config;backend/config" --add-data "%ICON_PNG%;backend/appIcon.png" ..\desktop_app.py
if errorlevel 1 (
  popd
  echo 打包失败
  exit /b 1
)
popd

copy /Y "%DIST_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 (
  echo 打包完成，但复制到父目录失败
  echo 已生成: %DIST_EXE%
  echo 请手动复制到: %TARGET_EXE%
  exit /b 0
)

echo 打包完成: %TARGET_EXE%
exit /b 0
