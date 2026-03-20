@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
set "ROOT=%cd%"
set "PROJECT_NAME=Prekikoeru"

set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "ICON=%BACKEND%\app.ico"
set "FALLBACK_ICON=%BACKEND%\app.ico"
set "VENV_PYTHON=%BACKEND%\venv\Scripts\python.exe"
set "PYTHON_LAUNCHER="
set "DIST_EXE=%BACKEND%\dist\%PROJECT_NAME%.exe"
set "TARGET_EXE=%ROOT%\..\%PROJECT_NAME%.exe"

if exist "%VENV_PYTHON%" (
  set "PYTHON_LAUNCHER=%VENV_PYTHON%"
) else (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_LAUNCHER=py -3"
  ) else (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
      set "PYTHON_LAUNCHER=python"
    )
  )
)

if not defined PYTHON_LAUNCHER (
  echo Python interpreter not found.
  echo Checked:
  echo   %VENV_PYTHON%
  echo   py -3
  echo   python
  exit /b 1
)

if not exist "%ICON%" (
  if exist "%FALLBACK_ICON%" (
    set "ICON=%FALLBACK_ICON%"
  ) else (
    echo Icon file not found:
    echo   %ICON%
    echo Fallback icon also not found:
    echo   %FALLBACK_ICON%
    exit /b 1
  )
)

echo Using Python: %PYTHON_LAUNCHER%
echo Using icon: %ICON%

pushd "%FRONTEND%"
call npm.cmd run build
if errorlevel 1 (
  popd
  echo Frontend build failed.
  exit /b 1
)
popd

pushd "%BACKEND%"
call %PYTHON_LAUNCHER% -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  popd
  echo Backend dependency install failed.
  exit /b 1
)

call %PYTHON_LAUNCHER% -m pip install pyinstaller --disable-pip-version-check
if errorlevel 1 (
  popd
  echo PyInstaller install failed.
  exit /b 1
)

call %PYTHON_LAUNCHER% -c "import pystray, PIL; print('pystray ok')"
if errorlevel 1 (
  popd
  echo Dependency check failed: pystray/Pillow not available.
  exit /b 1
)

call %PYTHON_LAUNCHER% -m PyInstaller --onefile --noconsole --clean --name "%PROJECT_NAME%" --icon "%ICON%" --distpath "dist" --workpath "build" --specpath "." --paths "%ROOT%" --hidden-import pystray --hidden-import pystray._base --hidden-import pystray._win32 --hidden-import pystray._util --hidden-import pystray._util.win32 --hidden-import PIL --hidden-import PIL.Image --hidden-import PIL.ImageDraw --add-data "..\frontend\dist;frontend/dist" --add-data "config;backend/config" --add-data "%ICON%;." ..\desktop_app.py
if errorlevel 1 (
  popd
  echo Packaging failed.
  exit /b 1
)
popd

copy /Y "%DIST_EXE%" "%TARGET_EXE%" >nul
if errorlevel 1 (
  echo Built file:
  echo   %DIST_EXE%
  echo Copy to target failed:
  echo   %TARGET_EXE%
  exit /b 1
)

echo Packaging complete:
echo   %TARGET_EXE%
exit /b 0
