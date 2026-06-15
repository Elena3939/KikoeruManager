param(
    [string]$DatabaseName = "kikoerumanager",
    [string]$AppUser = "kikoerumanager",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5432,
    [string]$ConfigPath = "",
    [string]$InstallRoot = "",
    [switch]$StartOnly,
    [switch]$ForceWriteConfig
)

$ErrorActionPreference = "Stop"

$PostgresVersion = "18.4"
$PostgresPackage = "postgresql-18.4-1-windows-x64-binaries.zip"
$PostgresDownloadUrl = "https://get.enterprisedb.com/postgresql/$PostgresPackage"

function Resolve-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Write-Step([string]$Message) {
    Write-Host "[PostgreSQL] $Message"
}

function New-AppPassword {
    $bytes = [byte[]]::new(32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Test-CommandPath([string]$Path) {
    return $Path -and (Test-Path -LiteralPath $Path)
}

function Find-PostgresBin([string]$PreferredRoot) {
    $candidates = @()
    if ($PreferredRoot) {
        $candidates += (Join-Path $PreferredRoot "pgsql\bin")
        $candidates += (Join-Path $PreferredRoot "bin")
    }
    $candidates += @(
        (Join-Path (Resolve-ProjectRoot) "data\postgresql\pgsql\bin"),
        "D:\softApp\PostgreSQL\pgsql\bin",
        "C:\Program Files\PostgreSQL\18\bin",
        "C:\Program Files\PostgreSQL\17\bin",
        "C:\Program Files\PostgreSQL\16\bin"
    )
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if ($psql) {
        $candidates = @((Split-Path $psql.Source -Parent)) + $candidates
    }
    foreach ($item in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $item "psql.exe")) {
            return $item
        }
    }
    return ""
}

function Find-EmbeddedPostgresBin([string]$Root) {
    $candidates = @(
        (Join-Path $Root "pgsql\bin"),
        (Join-Path $Root "bin")
    )
    foreach ($item in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $item "psql.exe")) {
            return $item
        }
    }
    return ""
}

function Test-LocalHost([string]$Value) {
    $normalized = ([string]$Value).Trim().ToLowerInvariant()
    return $normalized -in @("", "localhost", "127.0.0.1", "::1")
}

function Resolve-PostgresDataDirs([string]$Bin, [string]$PreferredRoot) {
    $items = New-Object System.Collections.Generic.List[string]
    if ($PreferredRoot) {
        $items.Add((Join-Path $PreferredRoot "data"))
    }
    if ($Bin) {
        $binPath = (Resolve-Path -LiteralPath $Bin -ErrorAction SilentlyContinue)
        if ($binPath) {
            $binFull = $binPath.Path
            $binParent = Split-Path $binFull -Parent
            if ($binParent) {
                $items.Add((Join-Path $binParent "data"))
                $grandParent = Split-Path $binParent -Parent
                if ($grandParent) {
                    $items.Add((Join-Path $grandParent "data"))
                }
            }
        }
    }
    $items.Add("D:\softApp\PostgreSQL\data")
    $items.Add("C:\Program Files\PostgreSQL\18\data")
    $items.Add("C:\Program Files\PostgreSQL\17\data")
    $items.Add("C:\Program Files\PostgreSQL\16\data")

    $seen = @{}
    foreach ($item in $items) {
        if (-not $item) {
            continue
        }
        $key = $item.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            continue
        }
        $seen[$key] = $true
        if (Test-Path -LiteralPath (Join-Path $item "PG_VERSION")) {
            $item
        }
    }
}

function Start-LocalPostgresCandidates([string]$Bin, [string]$PreferredRoot) {
    if (-not $Bin) {
        return
    }
    foreach ($candidateDataDir in (Resolve-PostgresDataDirs $Bin $PreferredRoot)) {
        try {
            Ensure-PostgresStarted $Bin $candidateDataDir
            return
        } catch {
            Write-Step "Start candidate failed: $candidateDataDir"
        }
    }
}

function Get-ConfigDatabase([string]$Path, [string]$Python) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $env:KIKOERUMANAGER_CONFIG_PATH = $Path
    try {
        $json = @'
from __future__ import annotations
import json
import os
from pathlib import Path
import yaml
path = Path(os.environ["KIKOERUMANAGER_CONFIG_PATH"])
data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
print(json.dumps(data.get("database") or {}, ensure_ascii=False))
'@ | & $Python -
        if ($LASTEXITCODE -ne 0 -or -not $json) {
            return $null
        }
        return $json | ConvertFrom-Json
    }
    finally {
        Remove-Item Env:\KIKOERUMANAGER_CONFIG_PATH -ErrorAction SilentlyContinue
    }
}

function Test-PostgresConnection([string]$Bin, [string]$HostValue, [int]$PortValue, [string]$UserValue, [string]$PasswordValue, [string]$DatabaseValue) {
    if (-not $Bin -or -not $UserValue -or -not $DatabaseValue) {
        return $false
    }
    $psql = Join-Path $Bin "psql.exe"
    if (-not (Test-Path -LiteralPath $psql)) {
        return $false
    }
    if ($null -eq $PasswordValue) {
        $env:PGPASSWORD = ""
    } else {
        $env:PGPASSWORD = [string]$PasswordValue
    }
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $output = & $psql -h $HostValue -p $PortValue -U $UserValue -d $DatabaseValue -At -c "SELECT 1" 2>$null
        return ($LASTEXITCODE -eq 0 -and (($output | Select-Object -First 1) -eq "1"))
    } catch {
        return $false
    }
    finally {
        if ($previousErrorActionPreference) {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Ensure-EmbeddedPostgresInstalled([string]$Root) {
    $bin = Find-EmbeddedPostgresBin $Root
    if ($bin) {
        return $bin
    }

    $downloadDir = Join-Path (Resolve-ProjectRoot) "data\downloads"
    $zipPath = Join-Path $downloadDir $PostgresPackage
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    New-Item -ItemType Directory -Force -Path $Root | Out-Null

    if (-not (Test-Path -LiteralPath $zipPath)) {
        Write-Step "Local PostgreSQL not found. Downloading $PostgresVersion Windows binaries..."
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $PostgresDownloadUrl -OutFile $zipPath -UseBasicParsing
    }

    Write-Step "Extracting PostgreSQL to $Root ..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $Root -Force
    $bin = Find-EmbeddedPostgresBin $Root
    if (-not $bin) {
        throw "psql.exe not found after extracting PostgreSQL: $Root"
    }
    return $bin
}

function Ensure-PostgresStarted([string]$Bin, [string]$DataDir) {
    $pgCtl = Join-Path $Bin "pg_ctl.exe"
    $logFile = Join-Path (Split-Path $DataDir -Parent) "postgresql.log"
    if (-not (Test-Path -LiteralPath $pgCtl)) {
        throw "pg_ctl.exe not found: $pgCtl"
    }
    $statusOutput = & $pgCtl -D $DataDir status 2>$null
    if ($LASTEXITCODE -eq 0 -and ($statusOutput -join "`n") -match "server is running") {
        return
    }
    Write-Step "Starting local PostgreSQL..."
    & $pgCtl -D $DataDir -l $logFile -w start
}

function Initialize-EmbeddedCluster([string]$Bin, [string]$DataDir, [string]$SuperUser, [string]$SuperPassword) {
    if (Test-Path -LiteralPath (Join-Path $DataDir "PG_VERSION")) {
        return
    }
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $initdb = Join-Path $Bin "initdb.exe"
    $pwFile = Join-Path (Split-Path $DataDir -Parent) "pg_init_password.txt"
    Set-Content -LiteralPath $pwFile -Value $SuperPassword -Encoding ASCII -NoNewline
    try {
        Write-Step "Initializing PostgreSQL data directory $DataDir ..."
        & $initdb -D $DataDir -U $SuperUser -A scram-sha-256 "--pwfile=$pwFile" --encoding=UTF8 --locale=C
    }
    finally {
        Remove-Item -LiteralPath $pwFile -Force -ErrorAction SilentlyContinue
    }
    Add-Content -LiteralPath (Join-Path $DataDir "postgresql.conf") -Value @"

listen_addresses = '127.0.0.1'
port = $Port
shared_buffers = '128MB'
effective_cache_size = '1GB'
maintenance_work_mem = '128MB'
work_mem = '8MB'
checkpoint_completion_target = 0.9
random_page_cost = 1.1
default_statistics_target = 200
log_min_duration_statement = 1000
"@
}

function Invoke-Psql([string]$Bin, [string]$UserValue, [string]$PasswordValue, [string]$DatabaseValue, [string]$Sql) {
    $psql = Join-Path $Bin "psql.exe"
    $env:PGPASSWORD = $PasswordValue
    try {
        $Sql | & $psql -h $HostName -p $Port -U $UserValue -d $DatabaseValue -v ON_ERROR_STOP=1
        if ($LASTEXITCODE -ne 0) {
            throw "psql execution failed"
        }
    }
    finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Invoke-PsqlScalar([string]$Bin, [string]$UserValue, [string]$PasswordValue, [string]$DatabaseValue, [string]$Sql) {
    $psql = Join-Path $Bin "psql.exe"
    $env:PGPASSWORD = $PasswordValue
    try {
        $output = & $psql -h $HostName -p $Port -U $UserValue -d $DatabaseValue -At -c $Sql
        if ($LASTEXITCODE -ne 0) {
            return ""
        }
        $first = $output | Select-Object -First 1
        if ($null -eq $first) {
            return ""
        }
        return $first.ToString().Trim()
    }
    finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Ensure-DatabaseAndRole([string]$Bin, [string]$SuperUser, [string]$SuperPassword, [string]$RoleName, [string]$RolePassword, [string]$DbName) {
    $escapedRole = $RoleName.Replace('"', '""')
    $escapedDb = $DbName.Replace('"', '""')
    $escapedPassword = $RolePassword.Replace("'", "''")
    $roleExists = Invoke-PsqlScalar $Bin $SuperUser $SuperPassword "postgres" "SELECT 1 FROM pg_roles WHERE rolname = '$($RoleName.Replace("'", "''"))'"
    if ($roleExists -ne "1") {
        Invoke-Psql $Bin $SuperUser $SuperPassword "postgres" "CREATE ROLE ""$escapedRole"" LOGIN PASSWORD '$escapedPassword';"
    }
    $dbExists = Invoke-PsqlScalar $Bin $SuperUser $SuperPassword "postgres" "SELECT 1 FROM pg_database WHERE datname = '$($DbName.Replace("'", "''"))'"
    if ($dbExists -ne "1") {
        Invoke-Psql $Bin $SuperUser $SuperPassword "postgres" "CREATE DATABASE ""$escapedDb"" OWNER ""$escapedRole"";"
    }
    $testDb = "${DbName}_test"
    $escapedTestDb = $testDb.Replace('"', '""')
    $testDbExists = Invoke-PsqlScalar $Bin $SuperUser $SuperPassword "postgres" "SELECT 1 FROM pg_database WHERE datname = '$($testDb.Replace("'", "''"))'"
    if ($testDbExists -ne "1") {
        Invoke-Psql $Bin $SuperUser $SuperPassword "postgres" "CREATE DATABASE ""$escapedTestDb"" OWNER ""$escapedRole"";"
    }
    Invoke-Psql $Bin $SuperUser $SuperPassword $DbName "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
    Invoke-Psql $Bin $SuperUser $SuperPassword $testDb "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
}

function Write-AppConfig([string]$Path, [string]$Python, [string]$DbPassword) {
    $env:KIKOERUMANAGER_CONFIG_PATH = $Path
    $env:KIKOERUMANAGER_PG_HOST = $HostName
    $env:KIKOERUMANAGER_PG_PORT = [string]$Port
    $env:KIKOERUMANAGER_PG_DATABASE = $DatabaseName
    $env:KIKOERUMANAGER_PG_USERNAME = $AppUser
    $env:KIKOERUMANAGER_PG_PASSWORD = $DbPassword
    try {
@'
from __future__ import annotations

import os
from pathlib import Path

import yaml

path = Path(os.environ["KIKOERUMANAGER_CONFIG_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if path.exists():
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
old = dict(data.get("database") or {})
data["database"] = {
    "host": os.environ["KIKOERUMANAGER_PG_HOST"],
    "port": int(os.environ["KIKOERUMANAGER_PG_PORT"]),
    "database": os.environ["KIKOERUMANAGER_PG_DATABASE"],
    "username": os.environ["KIKOERUMANAGER_PG_USERNAME"],
    "password": os.environ["KIKOERUMANAGER_PG_PASSWORD"],
    "sslmode": old.get("sslmode") or "prefer",
    "connect_timeout_seconds": int(old.get("connect_timeout_seconds") or 10),
    "pool_size": int(old.get("pool_size") or 10),
    "max_overflow": int(old.get("max_overflow") or 20),
    "pool_recycle_seconds": int(old.get("pool_recycle_seconds") or 1800),
    "pool_timeout_seconds": int(old.get("pool_timeout_seconds") or 30),
    "statement_timeout_ms": int(old.get("statement_timeout_ms") or 120000),
    "startup_health_check": bool(old.get("startup_health_check", True)),
}
budget = dict(data.get("resource_budget") or {})
legacy_key = "sqli" + "te_write"
if "database_write" not in budget:
    budget["database_write"] = int(budget.get(legacy_key) or 4)
budget.pop(legacy_key, None)
data["resource_budget"] = budget
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(path)
'@ | & $Python -
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to write config"
        }
    }
    finally {
        Remove-Item Env:\KIKOERUMANAGER_CONFIG_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:\KIKOERUMANAGER_PG_HOST -ErrorAction SilentlyContinue
        Remove-Item Env:\KIKOERUMANAGER_PG_PORT -ErrorAction SilentlyContinue
        Remove-Item Env:\KIKOERUMANAGER_PG_DATABASE -ErrorAction SilentlyContinue
        Remove-Item Env:\KIKOERUMANAGER_PG_USERNAME -ErrorAction SilentlyContinue
        Remove-Item Env:\KIKOERUMANAGER_PG_PASSWORD -ErrorAction SilentlyContinue
    }
}

$ProjectRoot = Resolve-ProjectRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $ProjectRoot "data\config\config.yaml"
}
if (-not $InstallRoot) {
    $InstallRoot = Join-Path $ProjectRoot "data\postgresql"
}
$DataDir = Join-Path $InstallRoot "data"
$Python = Join-Path $ProjectRoot "backend\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python venv not found: $Python"
}

$embeddedBin = Find-EmbeddedPostgresBin $InstallRoot
$existingBin = Find-PostgresBin $InstallRoot
$existingConfig = Get-ConfigDatabase $ConfigPath $Python
if ($existingConfig -and -not $ForceWriteConfig) {
    $cfgHost = [string]$existingConfig.host
    if (-not $cfgHost) {
        $cfgHost = ""
    }
    $cfgPort = 5432
    if ($existingConfig.port) {
        $cfgPort = [int]$existingConfig.port
    }
    $cfgDb = [string]$existingConfig.database
    if (-not $cfgDb) {
        $cfgDb = ""
    }
    $cfgUser = [string]$existingConfig.username
    if (-not $cfgUser) {
        $cfgUser = ""
    }
    $cfgPassword = [string]$existingConfig.password
    if (-not $cfgPassword) {
        $cfgPassword = ""
    }
    if (Test-LocalHost $cfgHost) {
        Start-LocalPostgresCandidates $existingBin $InstallRoot
    }
    if (Test-PostgresConnection $existingBin $cfgHost $cfgPort $cfgUser $cfgPassword $cfgDb) {
        Write-Step "Existing database config is healthy. Skipping initialization."
        return
    }
}

if ($StartOnly) {
    Write-Step "PostgreSQL is not ready. Run setup.bat to install or fix data/config/config.yaml."
    exit 1
}

$systemBin = Find-PostgresBin ""
if ($systemBin -and -not $embeddedBin) {
    throw "System PostgreSQL was detected, but current config is not healthy. Not installing embedded PostgreSQL over an existing environment. Fix data/config/config.yaml."
}

$appPassword = New-AppPassword
$superUser = $AppUser
$superPassword = $appPassword
$pgBin = Ensure-EmbeddedPostgresInstalled $InstallRoot

$ownsEmbeddedCluster = (Test-Path -LiteralPath (Join-Path $InstallRoot "pgsql\bin\initdb.exe")) -or ($pgBin -like "$InstallRoot*")
if ($ownsEmbeddedCluster) {
    Initialize-EmbeddedCluster $pgBin $DataDir $superUser $superPassword
    Ensure-PostgresStarted $pgBin $DataDir
    Ensure-DatabaseAndRole $pgBin $superUser $superPassword $AppUser $appPassword $DatabaseName
    Write-AppConfig $ConfigPath $Python $appPassword
    Write-Step "Embedded PostgreSQL initialized and config written: $ConfigPath"
    Write-Step "Generated database password is stored as plain text in local config for later viewing/editing."
    return
}

throw "PostgreSQL initialization did not complete."
