# 同步远程分支更新（保留本地配置文件）
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  同步远程分支更新（保留本地配置）" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 设置要忽略的配置文件
$ConfigFiles = @("config/config.yaml", "backend/config/config.yaml")

Write-Host "[1/5] 设置配置文件为忽略状态..." -ForegroundColor Yellow
foreach ($file in $ConfigFiles) {
    Write-Host "  忽略：$file" -ForegroundColor Gray
    git update-index --assume-unchanged $file
}
Write-Host "  完成" -ForegroundColor Green
Write-Host ""

Write-Host "[2/5] 获取远程更新..." -ForegroundColor Yellow
git fetch origin
Write-Host "  完成" -ForegroundColor Green
Write-Host ""

Write-Host "[3/5] 检查本地与远程的差异..." -ForegroundColor Yellow
$behind = git rev-list --count HEAD..origin/feature/start-all-improvement
if ($behind -gt 0) {
    Write-Host "  本地分支落后远程 $behind 个提交" -ForegroundColor Yellow
} else {
    Write-Host "  本地已是最新" -ForegroundColor Green
}
Write-Host ""

Write-Host "[4/5] 合并远程分支更新..." -ForegroundColor Yellow
git pull origin feature/start-all-improvement --no-rebase
Write-Host "  完成" -ForegroundColor Green
Write-Host ""

Write-Host "[5/5] 检查当前状态..." -ForegroundColor Yellow
git status --short
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  同步完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "已忽略的配置文件（不会被远程更新覆盖）：" -ForegroundColor Yellow
Write-Host "  - config/config.yaml" -ForegroundColor Gray
Write-Host "  - backend/config/config.yaml" -ForegroundColor Gray
Write-Host ""
Write-Host "其他文件已更新到最新版本。" -ForegroundColor Green
Write-Host ""
Write-Host "如需恢复配置文件的跟踪，运行：" -ForegroundColor Yellow
Write-Host "  git update-index --no-assume-unchanged config/config.yaml backend/config/config.yaml" -ForegroundColor Gray
Write-Host ""
