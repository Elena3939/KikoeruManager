@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================
echo   KikoeruManager 发布脚本
echo ========================================
echo.

:: 检查参数
if "%1"=="" (
    echo 用法: release.bat ^<版本号^>
    echo   例如: release.bat v2.4.0
    echo.
    set /p TAG="输入版本号 (例如 v2.4.0): "
    if "!TAG!"=="" exit /b 1
) else (
    set TAG=%1
)

:: 验证版本号格式
echo !TAG! | findstr /r "^v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [错误] 版本号格式无效，请使用 vX.Y.Z 格式 (例如 v2.4.0)
    exit /b 1
)

echo.
echo [1/5] 确认提交文件...
set COMMIT_FILES=^
    backend/app/config/settings.py ^
    backend/app/core/ai_title_translation_service.py ^
    backend/app/core/metadata_service.py ^
    backend/app/models/database.py ^
    backend/app/api/routes.py ^
    frontend/src/views/Settings.vue ^
    frontend/src/components/settings/AITitleTranslationSettingsPanel.vue

echo   tag: %TAG%
echo.

:: 检查是否有未提交的改动
git diff --quiet
if not errorlevel 1 (
    git diff --cached --quiet
    if not errorlevel 1 (
        echo [提示] 没有未提交的改动，跳过提交步骤
        set SKIP_COMMIT=1
    )
)

if not defined SKIP_COMMIT (
    echo [2/5] 暂存文件...
    git add %COMMIT_FILES%
    if errorlevel 1 (
        echo [错误] 暂存文件失败
        exit /b 1
    )
    
    echo [3/5] 提交...
    git commit -m "新增 AI 标题汉化功能：元数据获取后自动检测日文作品名并调用 LLM 翻译为中文"
    if errorlevel 1 (
        echo [错误] 提交失败
        exit /b 1
    )
)

echo [4/5] 创建标签 %TAG%...
git tag %TAG%
if errorlevel 1 (
    echo [错误] 创建标签失败（可能已存在）
    exit /b 1
)

echo [5/5] 推送到 GitHub...
echo   推送提交...
git push origin main
if errorlevel 1 (
    echo [警告] 推送提交失败
)
echo   推送标签...
git push origin %TAG%
if errorlevel 1 (
    echo [警告] 推送标签失败
)

echo.
echo ========================================
echo  发布完成！
echo.
echo  tag:    %TAG%
echo  GitHub Actions 已自动触发：
echo    - Windows EXE 构建
echo    - Docker 镜像构建 (ghcr.io)
echo.
echo  查看进度:
echo    https://github.com/GinatWiki/KikoeruManager/actions
echo ========================================

endlocal