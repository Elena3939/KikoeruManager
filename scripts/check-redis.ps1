# Redis runtime readiness check. setup/start-all only verifies availability; it does not install services.
param(
    [string]$Url = $env:KIKOERUMANAGER_REDIS_URL,
    [switch]$Quiet
)

function Write-Step {
    param([string]$Message)
    if (-not $Quiet) { Write-Host "[Redis] $Message" }
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

if (-not $Url) {
    $Url = 'redis://localhost:6379/0'
}

if (-not $redisEnabled) {
    Write-Step "Redis is disabled by runtime config"
    exit 0
}

function Test-RedisTcp {
    param(
        [string]$HostName,
        [int]$Port
    )
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait(2000)) {
            return $false
        }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

try {
    $uri = [Uri]$Url
    $hostName = if ($uri.Host) { $uri.Host } else { 'localhost' }
    $port = if ($uri.Port -gt 0) { $uri.Port } else { 6379 }
} catch {
    Write-Step "Invalid Redis URL: $Url"
    exit 1
}

$redisServer = Get-Command redis-server -ErrorAction SilentlyContinue
if ($redisServer) {
    Write-Step "redis-server found: $($redisServer.Source)"
} else {
    Write-Step "redis-server not found in PATH"
}

$redisCli = Get-Command redis-cli -ErrorAction SilentlyContinue
if ($redisCli) {
    try {
        $pong = & $redisCli.Source -h $hostName -p $port ping 2>$null
        if (($pong -join '').Trim() -eq 'PONG') {
            Write-Step "Redis is ready at $hostName`:$port"
            exit 0
        }
    } catch {
        Write-Step "redis-cli ping failed: $($_.Exception.Message)"
    }
}

if (Test-Path -LiteralPath $pythonPath) {
    $probe = "import redis; c=redis.Redis.from_url('$Url', decode_responses=True, socket_timeout=2, socket_connect_timeout=2); print('PONG' if c.ping() else 'FAIL')"
    try {
        $pong = & $pythonPath -c $probe 2>$null
        if (($pong -join '').Trim() -eq 'PONG') {
            Write-Step "Redis is ready at $hostName`:$port"
            exit 0
        }
    } catch {
        Write-Step "python redis ping failed: $($_.Exception.Message)"
    }
}

if (Test-RedisTcp -HostName $hostName -Port $port) {
    Write-Step "Redis TCP port is reachable at $hostName`:$port"
    exit 0
}

Write-Step "Redis is required but not reachable: $Url"
if ($redisRequired) {
    Write-Step "Install/start Redis, or set redis.enabled=false for local development only."
    exit 1
}
Write-Step "Redis is optional by runtime config; continuing without Redis."
exit 0
