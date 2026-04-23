@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
set "ROOT=%cd%"
set "PROJECT_NAME=Prekikoeru"

REM ========================================
REM 应用程序图标路径配置
REM 可自定义图标路径
REM ========================================
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "ICON=%BACKEND%\app.ico"
set "PYTHON_EXE=%BACKEND%\venv\Scripts\python.exe"
set "DIST_EXE=%BACKEND%\dist\%PROJECT_NAME%.exe"
set "TARGET_EXE=%ROOT%\..\%PROJECT_NAME%.exe"

if not exist "%PYTHON_EXE%" (
  echo 未找到后端虚拟环境: %PYTHON_EXE%
  echo 请先运行 setup.bat 安装依赖
  exit /b 1
)

if not exist "%ICON%" (
  echo 未找到图标文件: %ICON%
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

call "%PYTHON_EXE%" -c "import pystray, PIL; print('pystray ok')"
if errorlevel 1 (
  popd
  echo 依赖校验失败: pystray/Pillow 未正确安装
  exit /b 1
)

call "%PYTHON_EXE%" -m PyInstaller --onefile --noconsole --clean --name "%PROJECT_NAME%" --icon "%ICON%" --distpath "dist" --workpath "build" --specpath "." --paths "%ROOT%" --hidden-import pystray --hidden-import PIL --hidden-import PIL.Image --hidden-import orjson --add-data "..\frontend\dist;frontend/dist" --add-data "config;backend/config" --add-data "app.ico;backend" ..\desktop_app.py
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
