# Prekikoeru 开发环境启动脚本 (PowerShell)
# 使用方式: 右键点击 -> 使用 PowerShell 运行

$Host.UI.RawUI.WindowTitle = "Prekikoeru 开发服务器"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Prekikoeru 本地开发环境启动器" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查依赖
function Test-Command($Command) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'stop'
    try {
        if (Get-Command $Command) { return $true }
    } Catch { return $false }
    Finally { $ErrorActionPreference = $oldPreference }
}

Write-Host "检查依赖..." -ForegroundColor Yellow

if (Test-Command "py") {
    & py -3 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "py"
        $PythonArgs = @("-3")
    } else {
        $PythonExe = $null
        $PythonArgs = @()
    }
} else {
    $PythonExe = $null
    $PythonArgs = @()
}

if (-not $PythonExe -and (Test-Command "python")) {
    & python --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "python"
    }
}

if (-not $PythonExe) {
    Write-Host "[错误] 未找到Python，请确保Python已安装并添加到PATH" -ForegroundColor Red
    Read-Host "按Enter键退出"
    exit 1
}
Write-Host "[OK] Python已安装" -ForegroundColor Green

if (-not (Test-Command "node")) {
    Write-Host "[错误] 未找到Node.js，请确保Node.js已安装并添加到PATH" -ForegroundColor Red
    Read-Host "按Enter键退出"
    exit 1
}
Write-Host "[OK] Node.js已安装" -ForegroundColor Green

if (-not (Test-Command "7z")) {
    Write-Host "[警告] 未找到7-Zip，解压功能可能无法正常工作" -ForegroundColor Yellow
    Write-Host "请从 https://www.7-zip.org/ 下载安装" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host "[OK] 7-Zip已安装" -ForegroundColor Green
}

# 创建测试目录
Write-Host ""
Write-Host "创建测试目录..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "test_data\input" | Out-Null
New-Item -ItemType Directory -Force -Path "test_data\library" | Out-Null
New-Item -ItemType Directory -Force -Path "test_data\temp" | Out-Null
New-Item -ItemType Directory -Force -Path "data" | Out-Null
Write-Host "[OK] 目录创建完成" -ForegroundColor Green

# 安装后端依赖
Write-Host ""
Write-Host "[1/4] 正在创建Python虚拟环境..." -ForegroundColor Yellow
cd backend
if (Test-Path "venv\Scripts\python.exe") {
    & .\venv\Scripts\python.exe --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[提示] 检测到失效虚拟环境，正在重建..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force "venv"
    }
}
if (-not (Test-Path "venv\Scripts\python.exe")) {
    & $PythonExe @PythonArgs -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 虚拟环境创建失败" -ForegroundColor Red
        Read-Host "按Enter键退出"
        exit 1
    }
}
Write-Host "[OK] 虚拟环境已创建" -ForegroundColor Green

Write-Host ""
Write-Host "[2/4] 正在安装后端依赖..." -ForegroundColor Yellow
& .\venv\Scripts\python.exe -m ensurepip --upgrade *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 虚拟环境 pip 初始化失败" -ForegroundColor Red
    Read-Host "按Enter键退出"
    exit 1
}
& .\venv\Scripts\python.exe -c "import click,uvicorn,fastapi" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[提示] 检测到后端依赖不完整，正在修复..." -ForegroundColor Yellow
    & .\venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 后端依赖安装失败" -ForegroundColor Red
        Read-Host "按Enter键退出"
        exit 1
    }
}
Write-Host "[OK] 后端依赖安装完成" -ForegroundColor Green
cd ..

# 安装前端依赖
Write-Host ""
if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "[3/4] 正在安装前端依赖..." -ForegroundColor Yellow
    cd frontend
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 前端依赖安装失败" -ForegroundColor Red
        Read-Host "按Enter键退出"
        exit 1
    }
    cd ..
} else {
    Write-Host "[3/4] 前端依赖已安装，跳过" -ForegroundColor Green
}

# 启动服务
Write-Host ""
Write-Host "[4/4] 正在启动服务..." -ForegroundColor Yellow
Write-Host ""
Write-Host "服务地址:" -ForegroundColor Cyan
Write-Host "  后端API: http://localhost:8000" -ForegroundColor Green
Write-Host "  前端界面: http://localhost:5173" -ForegroundColor Green
Write-Host "  API文档: http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "按 Ctrl+C 停止服务" -ForegroundColor Yellow
Write-Host ""

# 启动后端（在新窗口）
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; .\venv\Scripts\python.exe -m app.main" -WindowStyle Normal

# 等待后端启动
Start-Sleep -Seconds 3

# 启动前端
cd frontend
npm run dev

# 清理（当前端停止时）
Write-Host ""
Write-Host "正在关闭服务..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host ""
Write-Host "服务已停止" -ForegroundColor Green
Write-Host ""
Read-Host "按Enter键退出"
