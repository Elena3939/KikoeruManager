# Starts the local Redis runtime required by KikoeruManager.
param(
    [string]$Url = $env:KIKOERUMANAGER_REDIS_URL,
    [string]$RedisServerPath = $env:KIKOERUMANAGER_REDIS_SERVER_PATH,
    [string]$DataDir = $env:KIKOERUMANAGER_REDIS_DATA_DIR,
    [switch]$Quiet
)

function Write-Step {
    param([string]$Message)
    if (-not $Quiet) { Write-Host "[Redis] $Message" }
}

function Test-RedisTcp {
    param(
        [string]$HostName,
        [int]$Port
    )
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait(1200)) {
            return $false
        }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Find-RedisServer {
    param([string]$ExplicitPath)
    $candidates = @()
    if ($ExplicitPath) { $candidates += $ExplicitPath }
    $command = Get-Command redis-server -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @(
        'D:\softApp\redis\Redis-8.8.0-Windows-x64-msys2-with-Service\redis-server.exe',
        'D:\softApp\redis\redis-server.exe',
        (Join-Path $rootPath 'tools\redis\redis-server.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    foreach ($baseDir in @('D:\softApp\redis', (Join-Path $rootPath 'tools\redis'))) {
        if (-not (Test-Path -LiteralPath $baseDir)) { continue }
        $found = Get-ChildItem -LiteralPath $baseDir -Filter 'redis-server.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return ''
}

function Test-RedisReady {
    param([string]$ProbeUrl)
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        return $false
    }
    $env:KIKOERUMANAGER_REDIS_PROBE_URL = $ProbeUrl
    $probe = "import os, redis; c=redis.Redis.from_url(os.environ['KIKOERUMANAGER_REDIS_PROBE_URL'], decode_responses=True, socket_timeout=1.5, socket_connect_timeout=1.5); print('PONG' if c.ping() else 'FAIL')"
    try {
        $pong = & $pythonPath -c $probe 2>$null
        return (($pong -join '').Trim() -eq 'PONG')
    } catch {
        return $false
    }
}

$rootPath = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$backendPath = Join-Path $rootPath 'backend'
$pythonPath = Join-Path $backendPath 'venv\Scripts\python.exe'
$redisEnabled = $true
$redisRequired = $true

if (-not $Url -and (Test-Path -LiteralPath $pythonPath)) {
    $env:KIKOERUMANAGER_SCRIPT_BACKEND_PATH = $backendPath
    $configProbe = "import json, os, sys; sys.path.insert(0, os.environ['KIKOERUMANAGER_SCRIPT_BACKEND_PATH']); from app.config.settings import get_config; cfg=get_config().redis; print(json.dumps({'enabled': bool(cfg.enabled), 'required': bool(cfg.required), 'url': str(cfg.url or '')}, ensure_ascii=False))"
    try {
        $configJson = & $pythonPath -c $configProbe 2>$null
        if ($LASTEXITCODE -eq 0 -and $configJson) {
            $runtimeConfig = ($configJson -join '') | ConvertFrom-Json
            $redisEnabled = [bool]$runtimeConfig.enabled
            $redisRequired = [bool]$runtimeConfig.required
            $Url = [string]$runtimeConfig.url
        }
    } catch {
        Write-Step "failed to read runtime Redis config: $($_.Exception.Message)"
    }
}

if (-not $redisEnabled) {
    Write-Step 'Redis is disabled by runtime config'
    exit 0
}
if (-not $Url) {
    $Url = 'redis://localhost:6379/0'
}

try {
    $uri = [Uri]$Url
    $hostName = if ($uri.Host) { $uri.Host } else { 'localhost' }
    $port = if ($uri.Port -gt 0) { $uri.Port } else { 6379 }
    $userInfo = [System.Uri]::UnescapeDataString([string]$uri.UserInfo)
    $password = ''
    if ($userInfo.Contains(':')) {
        $password = $userInfo.Split(':', 2)[1]
    } elseif ($userInfo) {
        $password = $userInfo
    }
} catch {
    Write-Step "Invalid Redis URL: $Url"
    exit 1
}

$localHosts = @('localhost', '127.0.0.1', '::1')
if (Test-RedisReady -ProbeUrl $Url) {
    Write-Step "Redis is ready at $hostName`:$port"
    exit 0
}

if ($localHosts -notcontains $hostName.ToLowerInvariant()) {
    Write-Step "Configured Redis is remote; auto-start skipped: $hostName`:$port"
    if ($redisRequired) { exit 1 }
    exit 0
}

if (Test-RedisTcp -HostName $hostName -Port $port) {
    Write-Step "Redis port is occupied but authenticated ping failed: $hostName`:$port"
    if ($redisRequired) { exit 1 }
    exit 0
}

$redisServer = Find-RedisServer -ExplicitPath $RedisServerPath
if (-not $redisServer) {
    Write-Step 'redis-server.exe not found. Expected D:\softApp\redis or KIKOERUMANAGER_REDIS_SERVER_PATH.'
    if ($redisRequired) { exit 1 }
    exit 0
}

if (-not $DataDir) {
    if ($redisServer.StartsWith('D:\softApp\redis', [System.StringComparison]::OrdinalIgnoreCase)) {
        $DataDir = 'D:\softApp\redis\data'
    } else {
        $DataDir = Join-Path $rootPath 'data\redis'
    }
}
if (-not (Test-Path -LiteralPath $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

$args = @(
    '--bind', '127.0.0.1',
    '--port', [string]$port,
    '--dir', $DataDir,
    '--dbfilename', 'dump.rdb',
    '--appendonly', 'yes'
)
if ($password) {
    $args += @('--requirepass', $password)
}

Write-Step "Starting Redis: $redisServer"
Start-Process -FilePath $redisServer -ArgumentList $args -WindowStyle Hidden | Out-Null

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-RedisReady -ProbeUrl $Url) {
        Write-Step "Redis is ready at $hostName`:$port"
        exit 0
    }
}

Write-Step "Redis failed to become ready at $hostName`:$port"
if ($redisRequired) { exit 1 }
exit 0
