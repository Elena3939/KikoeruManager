@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
set "PROJECT_NAME=KikoeruManager"

echo ========================================
echo   KikoeruManager 打包脚本
echo ========================================
call "%~dp0build-release.bat"
if errorlevel 1 (
    echo [ERROR] build-release.bat 执行失败
    exit /b 1
)

if not exist "dist" mkdir dist
copy /Y "backend\dist\%PROJECT_NAME%.exe" "dist\%PROJECT_NAME%.exe" >nul
if errorlevel 1 (
    echo [ERROR] 已生成 backend\\dist 产物，但复制到 dist 失败
    echo [INFO] 请手动使用: backend\dist\%PROJECT_NAME%.exe
    exit /b 1
)

echo ========================================
echo   打包完成!
echo   可执行文件位于：dist\%PROJECT_NAME%.exe
echo ========================================
exit /b 0
