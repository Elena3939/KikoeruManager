#Requires -RunAsAdministrator
<#
.SYNOPSIS
给 Windows Defender 添加 KikoeruManager 的路径 / 进程排除项，减少实时扫描对解压性能的拖累。

.DESCRIPTION
ASMR 包解压到工作目录后，Windows Defender 实时保护会立刻对每个解出的音频 / 图片文件做签名扫描。
即使在 NVMe SSD 上也会因此让 IOPS 和 CPU 双双打满，实测解压吞吐掉到正常的 1/10。
把解压工作目录 / 常用进程加到 Defender 排除项后吞吐能恢复正常。

.PARAMETER AsmrRoot
ASMR 根目录，脚本会连同其下常用子目录（待处理 / temp / asmr / 删除）一起加入 Defender 排除。
默认是当前 data/config/config.yaml 里配置的 E:\0\临时\asmr。

.EXAMPLE
PS> .\scripts\add-defender-exclusions.ps1
用默认路径 E:\0\临时\asmr 添加排除。

PS> .\scripts\add-defender-exclusions.ps1 -AsmrRoot 'F:\asmr'
自定义 ASMR 根目录。

.NOTES
必须用管理员 PowerShell 跑。否则会直接退出。
#>
[CmdletBinding()]
param(
    [string]$AsmrRoot = 'E:\0\临时\asmr'
)

$ErrorActionPreference = 'Stop'

Write-Host ('=' * 56) -ForegroundColor Cyan
Write-Host 'KikoeruManager -> Windows Defender 排除项' -ForegroundColor Cyan
Write-Host ('=' * 56) -ForegroundColor Cyan

# --- 路径排除 ---
$paths = @(
    $AsmrRoot,
    (Join-Path $AsmrRoot '待处理'),
    (Join-Path $AsmrRoot 'temp'),
    (Join-Path $AsmrRoot 'asmr'),
    (Join-Path $AsmrRoot '删除')
)

Write-Host "`n>> 添加路径排除" -ForegroundColor Yellow
foreach ($p in $paths) {
    try {
        Add-MpPreference -ExclusionPath $p -ErrorAction Stop
        Write-Host ('   [+] ' + $p) -ForegroundColor Green
    } catch {
        # 路径已在排除列表里会抛错，降级为提示
        Write-Host ('   [-] ' + $p + ' (' + $_.Exception.Message + ')') -ForegroundColor DarkGray
    }
}

# --- 进程排除 ---
$procs = @(
    '7z.exe',           # 7-Zip CLI
    '7zz.exe',          # 7-Zip 官方跨平台 CLI
    'python.exe',       # 开发模式下后端主进程
    'pythonw.exe',      # 桌面托盘版无窗口 Python
    'KikoeruManager.exe' # PyInstaller 打包后的桌面 exe
)

Write-Host "`n>> 添加进程排除" -ForegroundColor Yellow
foreach ($pr in $procs) {
    try {
        Add-MpPreference -ExclusionProcess $pr -ErrorAction Stop
        Write-Host ('   [+] ' + $pr) -ForegroundColor Green
    } catch {
        Write-Host ('   [-] ' + $pr + ' (' + $_.Exception.Message + ')') -ForegroundColor DarkGray
    }
}

# --- 确认 ---
Write-Host "`n>> 当前 Defender 路径排除列表" -ForegroundColor Cyan
$currentPaths = (Get-MpPreference).ExclusionPath
if ($currentPaths) {
    $currentPaths | ForEach-Object { Write-Host ('   - ' + $_) }
} else {
    Write-Host '   (空)' -ForegroundColor DarkGray
}

Write-Host "`n>> 当前 Defender 进程排除列表" -ForegroundColor Cyan
$currentProcs = (Get-MpPreference).ExclusionProcess
if ($currentProcs) {
    $currentProcs | ForEach-Object { Write-Host ('   - ' + $_) }
} else {
    Write-Host '   (空)' -ForegroundColor DarkGray
}

Write-Host "`n完成。按任意键关闭此窗口。" -ForegroundColor Green
[void][System.Console]::ReadKey($true)
