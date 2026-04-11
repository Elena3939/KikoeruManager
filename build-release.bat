@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
set "ROOT=%cd%"
for %%I in ("%ROOT%") do set "PROJECT_NAME=%%~nxI"

REM ========================================
REM 应用程序图标路径配置
REM 可自定义图标路径
REM ========================================
set "ICON=D:\Tool\0edba671-6c04-463c-9b4f-7f1cec565830.ico"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "PYTHON_EXE=%BACKEND%\venv\Scripts\python.exe"
set "DIST_EXE=%BACKEND%\dist\%PROJECT_NAME%.exe"
set "TARGET_EXE=%ROOT%\..\%PROJECT_NAME%.exe"

if not exist "%PYTHON_EXE%" (
  echo 未找到后端虚拟环境: %PYTHON_EXE%
  exit /b
if not exist "%ICON%" (
  echo 未找到图标文件: %ICON%
  exit /b 1
)

pushd "%FRONTEND%"
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

call "%PYTHON_EXE%" -m PyInstaller --onefile --noconsole --clean --name "%PROJECT_NAME%" --icon "%ICON%" --distpath "dist" --workpath "build" --specpath "." --paths "%ROOT%" --hidden-import pystray --hidden-import PIL --hidden-import PIL.Image --add-data "..\frontend\dist;frontend/dist" --add-data "config;backend/config" --add-data "%ICON%;." ..\desktop_app.py
if errorlevel 1 (
  popd
  echo 打包失败
  exit /b 1
)
popd

copy /Y "%DIST_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 (
  echo 已生成: %DIST_EXE%
  echo 复制到父目录失败，请手动复制到: %TARGET_EXE%
  exit /b 1
)

echo 打包完成: %TARGET_EXE%
exit /b 0
