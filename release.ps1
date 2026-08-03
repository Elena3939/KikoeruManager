<#
.SYNOPSIS
  KikoeruManager 发布脚本 - 提交、打 tag、推送到 GitHub，触发构建
.DESCRIPTION
  自动暂存指定文件、提交（如有改动）、创建 semver 标签并推送。
  GitHub Actions 收到 tag 后自动构建 Windows EXE 和 Docker 镜像。
  用法:
    .\release.ps1                # 交互式输入版本号
    .\release.ps1 v2.4.1         # 直接指定版本
#>

param(
  [string]$Tag = ""
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $rootDir

# 提交文件清单（只包含 AI 标题汉化相关文件）
$commitFiles = @(
  "backend/app/config/settings.py"
  "backend/app/core/ai_title_translation_service.py"
  "backend/app/core/metadata_service.py"
  "backend/app/models/database.py"
  "backend/app/api/routes.py"
  "frontend/src/views/Settings.vue"
  "frontend/src/components/settings/AITitleTranslationSettingsPanel.vue"
  "release.bat"
  "release.ps1"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KikoeruManager 发布脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 如果没有指定版本号，交互输入
if (-not $Tag) {
  $latestTag = git tag --sort=-v:refname | Select-Object -First 1
  $verStr = $latestTag.TrimStart('v')
  $parts = $verStr -split '\.'
  $patch = [int]$parts[2] + 1
  $defaultTag = "v$($parts[0]).$($parts[1]).$patch"
  
  Write-Host "最新 tag: $latestTag  →  推荐: $defaultTag"
  $Tag = Read-Host "输入版本号 (例如 $defaultTag)"
  if (-not $Tag) { $Tag = $defaultTag }
}

# 验证版本号格式
if ($Tag -notmatch '^v\d+\.\d+\.\d+$') {
  Write-Host "[错误] 版本号格式无效，请使用 vX.Y.Z 格式 (例如 v2.4.0)" -ForegroundColor Red
  exit 1
}

Write-Host ""

# 检查是否有改动需要提交
$hasUnstagedChanges = -not (git diff --quiet)
$hasUnstagedNew = -not (git diff --quiet --cached)
$hasUntracked = (git ls-files --others --exclude-standard | Where-Object { $_ -in $commitFiles })

$hasAnythingToCommit = $hasUnstagedChanges -or $hasUnstagedNew -or $hasUntracked

if ($hasAnythingToCommit) {
  Write-Host "[1/3] 暂存文件..."
  foreach ($file in $commitFiles) {
    $fullPath = Join-Path $rootDir $file
    if (Test-Path $fullPath) {
      git add $file 2>$null
    }
  }
  
  Write-Host "[2/3] 提交..."
  git commit -m "新增 AI 标题汉化功能：元数据获取后自动检测日文作品名并调用 LLM 翻译为中文"
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 提交失败" -ForegroundColor Red
    exit 1
  }
} else {
  Write-Host "[跳过] 没有新的改动需要提交"
}

Write-Host "[3/3] 打标签 $Tag 并推送到 GitHub..."
git tag $Tag 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "[错误] 创建标签失败（可能已存在）" -ForegroundColor Red
  exit 1
}

Write-Host "  推送提交..."
git push origin main 2>&1 | Out-Null
Write-Host "  推送标签 $Tag ..."
git push origin $Tag 2>&1

if ($LASTEXITCODE -eq 0) {
  Write-Host ""
  Write-Host "========================================" -ForegroundColor Green
  Write-Host "  发布完成！" -ForegroundColor Green
  Write-Host "  tag:    $Tag" -ForegroundColor White
  Write-Host "  GitHub Actions 已自动触发：" -ForegroundColor White
  Write-Host "    - Windows EXE 构建" -ForegroundColor White
  Write-Host "    - Docker 镜像构建 (ghcr.io)" -ForegroundColor White
  Write-Host ""
  Write-Host "  查看进度:" -ForegroundColor White
  Write-Host "    https://github.com/GinatWiki/KikoeruManager/actions" -ForegroundColor White
  Write-Host "========================================" -ForegroundColor Green
} else {
  Write-Host "[错误] 推送失败" -ForegroundColor Red
  exit 1
}