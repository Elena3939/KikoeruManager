param(
    [string]$DatabaseName = "kikoerumanager",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5432,
    [double]$MemoryGb = 0,
    [switch]$Hdd,
    [switch]$RestartService,
    [string]$ServiceName = "postgresql-x64-18"
)

$ErrorActionPreference = "Stop"

function Find-PostgresBin {
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if ($psql) {
        return Split-Path $psql.Source -Parent
    }
    $candidates = @(
        "C:\Program Files\PostgreSQL\18\bin",
        "C:\Program Files\PostgreSQL\17\bin",
        "C:\Program Files\PostgreSQL\16\bin"
    )
    foreach ($item in $candidates) {
        if (Test-Path (Join-Path $item "psql.exe")) {
            return $item
        }
    }
    throw "未找到 psql.exe，请先安装 PostgreSQL 18。"
}

function ConvertTo-PlainText([securestring]$Secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Format-PgMemory([int]$Mb) {
    if ($Mb -ge 1024 -and ($Mb % 1024) -eq 0) {
        return "$([int]($Mb / 1024))GB"
    }
    return "${Mb}MB"
}

if ($MemoryGb -le 0) {
    $computer = Get-CimInstance Win32_ComputerSystem
    $MemoryGb = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
}

$totalMb = [int][math]::Max(2048, [math]::Round($MemoryGb * 1024))
$sharedBuffersMb = [int][math]::Min(4096, [math]::Max(256, [math]::Round($totalMb * 0.25)))
$effectiveCacheMb = [int][math]::Max(512, [math]::Round($totalMb * 0.70))
$maintenanceMb = [int][math]::Min(2048, [math]::Max(128, [math]::Round($totalMb * 0.05)))
$workMemMb = 8
if ($totalMb -ge 8192) { $workMemMb = 16 }
if ($totalMb -ge 16384) { $workMemMb = 32 }
if ($totalMb -ge 32768) { $workMemMb = 64 }
$maxWal = "1GB"
if ($totalMb -ge 16384) { $maxWal = "2GB" }
if ($totalMb -ge 32768) { $maxWal = "4GB" }
$randomPageCost = if ($Hdd) { "4.0" } else { "1.1" }
$effectiveIoConcurrency = if ($Hdd) { "2" } else { "200" }

$PgBin = Find-PostgresBin
$Psql = Join-Path $PgBin "psql.exe"
$SecurePassword = Read-Host "请输入 postgres 超级用户密码" -AsSecureString
$SuperPassword = ConvertTo-PlainText $SecurePassword

$settings = [ordered]@{
    "shared_preload_libraries" = "pg_stat_statements"
    "pg_stat_statements.track" = "all"
    "pg_stat_statements.max" = "10000"
    "track_io_timing" = "on"
    "shared_buffers" = Format-PgMemory $sharedBuffersMb
    "effective_cache_size" = Format-PgMemory $effectiveCacheMb
    "maintenance_work_mem" = Format-PgMemory $maintenanceMb
    "work_mem" = Format-PgMemory $workMemMb
    "max_wal_size" = $maxWal
    "checkpoint_timeout" = "15min"
    "random_page_cost" = $randomPageCost
    "effective_io_concurrency" = $effectiveIoConcurrency
    "default_statistics_target" = "200"
    "autovacuum_vacuum_scale_factor" = "0.05"
    "autovacuum_analyze_scale_factor" = "0.02"
}

$LibraryIndexTuneSql = @'
DO $$
BEGIN
    IF to_regclass('library_index_entries') IS NOT NULL THEN
        ALTER TABLE library_index_entries SET (
            autovacuum_analyze_scale_factor = 0.001,
            autovacuum_analyze_threshold = 500,
            autovacuum_vacuum_scale_factor = 0.005,
            autovacuum_vacuum_threshold = 1000
        );
    END IF;
END
$$;
'@

Write-Host "[PostgreSQL] 按 $MemoryGb GB 内存写入性能参数..."
$env:PGPASSWORD = $SuperPassword
try {
    foreach ($entry in $settings.GetEnumerator()) {
        $name = $entry.Key
        $value = $entry.Value.Replace("'", "''")
        & $Psql -h $HostName -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER SYSTEM SET $name = '$value'"
    }
    & $Psql -h $HostName -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_reload_conf()"

    $dbExists = (& $Psql -h $HostName -p $Port -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName'").Trim()
    if ($dbExists -eq "1") {
        & $Psql -h $HostName -p $Port -U postgres -d $DatabaseName -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm"
        & $Psql -h $HostName -p $Port -U postgres -d $DatabaseName -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
        & $Psql -h $HostName -p $Port -U postgres -d $DatabaseName -v ON_ERROR_STOP=1 -c $LibraryIndexTuneSql
    }

    $TestDatabaseName = "${DatabaseName}_test"
    $testDbExists = (& $Psql -h $HostName -p $Port -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$TestDatabaseName'").Trim()
    if ($testDbExists -eq "1") {
        & $Psql -h $HostName -p $Port -U postgres -d $TestDatabaseName -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm"
        & $Psql -h $HostName -p $Port -U postgres -d $TestDatabaseName -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
        & $Psql -h $HostName -p $Port -U postgres -d $TestDatabaseName -v ON_ERROR_STOP=1 -c $LibraryIndexTuneSql
    }

    if ($RestartService) {
        Restart-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 5
    }

    $pending = (& $Psql -h $HostName -p $Port -U postgres -d postgres -tAc "SELECT string_agg(name, ', ') FROM pg_settings WHERE pending_restart").Trim()
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "[PostgreSQL] 调优参数已写入。"
Write-Host "[PostgreSQL] shared_buffers=$(Format-PgMemory $sharedBuffersMb), effective_cache_size=$(Format-PgMemory $effectiveCacheMb), work_mem=$(Format-PgMemory $workMemMb), max_wal_size=$maxWal"
if ($pending) {
    Write-Host "[PostgreSQL] 以下参数等待重启后生效：$pending"
} else {
    Write-Host "[PostgreSQL] 当前没有等待重启的参数。"
}
