param(
    [string]$Version = "4.0.1",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
    $InstallDir = Join-Path $repoRoot "tools\baidupcs-go"
}

$installPath = [System.IO.Path]::GetFullPath($InstallDir)
$repoRootPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path)
if (-not $installPath.StartsWith($repoRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "安装目录必须位于项目目录内: $installPath"
}

$exePath = Join-Path $installPath "BaiduPCS-Go.exe"
$probeConfigDir = Join-Path $repoRootPath ".runtime\baidupcs-go-probe"

function Invoke-BaiduPCSGoVersion {
    param([string]$Path)
    New-Item -ItemType Directory -Path $probeConfigDir -Force | Out-Null
    $previousConfigDir = $env:BAIDUPCS_GO_CONFIG_DIR
    try {
        $env:BAIDUPCS_GO_CONFIG_DIR = $probeConfigDir
        & $Path -v
    } finally {
        if ($null -eq $previousConfigDir) {
            Remove-Item Env:\BAIDUPCS_GO_CONFIG_DIR -ErrorAction SilentlyContinue
        } else {
            $env:BAIDUPCS_GO_CONFIG_DIR = $previousConfigDir
        }
    }
}

if (Test-Path -LiteralPath $exePath) {
    Invoke-BaiduPCSGoVersion -Path $exePath
    exit 0
}

$processorArch = [string]$env:PROCESSOR_ARCHITECTURE
$arch = if ($processorArch -match "ARM") {
    "arm"
} elseif ([Environment]::Is64BitOperatingSystem) {
    "x64"
} else {
    "x86"
}
$asset = "BaiduPCS-Go-v$Version-windows-$arch.zip"
$url = "https://github.com/qjfoidnh/BaiduPCS-Go/releases/download/v$Version/$asset"
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kikoerumanager-baidupcs-go-" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpRoot $asset
$extractDir = Join-Path $tmpRoot "extract"

New-Item -ItemType Directory -Path $tmpRoot, $extractDir, $installPath -Force | Out-Null

try {
    Write-Host "[BaiduPCS-Go] 下载 $asset"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $downloadedExe = Get-ChildItem -LiteralPath $extractDir -Recurse -File -Filter "BaiduPCS-Go.exe" | Select-Object -First 1
    if (-not $downloadedExe) {
        throw "压缩包中没有找到 BaiduPCS-Go.exe"
    }

    Copy-Item -LiteralPath $downloadedExe.FullName -Destination $exePath -Force
    Write-Host "[BaiduPCS-Go] 已安装到 $exePath"
    Invoke-BaiduPCSGoVersion -Path $exePath
} finally {
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force
    }
}
