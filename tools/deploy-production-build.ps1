[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$DryRun,
    [string]$ReleaseId
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$connectScript = Join-Path $repoRoot '.codex\ssh\connect-production.ps1'
$remoteScriptSource = Join-Path $PSScriptRoot 'deploy-production-build-remote.sh'
$pwshExecutable = (Get-Command pwsh -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $connectScript)) {
    throw "生产 SSH 入口不存在: $connectScript"
}
if (-not (Test-Path -LiteralPath $remoteScriptSource)) {
    throw "远端发布脚本不存在: $remoteScriptSource"
}

if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
    $shortRevision = (& git -C $repoRoot rev-parse --short=12 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $shortRevision) {
        throw '无法读取当前 Git revision，拒绝创建无法追溯的生产发布。'
    }
    $ReleaseId = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$shortRevision"
}

if ($ReleaseId -notmatch '^[0-9A-Za-z][0-9A-Za-z-]{5,80}$') {
    throw "非法发布版本号: $ReleaseId"
}

$sourceRevision = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceRevision) {
    throw '无法读取当前 Git revision，拒绝发布。'
}

$sourceFiles = @(& git -C $repoRoot -c core.quotepath=false ls-files -co --exclude-standard | Where-Object {
    $_ -notmatch '(^|/)(\.test-tmp[^/]*|\.pytest-tmp|\.codex[^/]*|\.codegraph|__pycache__)(/|$)'
})
if ($LASTEXITCODE -ne 0 -or $sourceFiles.Count -eq 0) {
    throw '无法列出源码快照文件，拒绝发布。'
}

foreach ($requiredFile in @('Dockerfile', '.dockerignore', 'backend/requirements.txt', 'frontend/package-lock.json')) {
    if ($sourceFiles -notcontains $requiredFile) {
        throw "源码快照缺少构建必需文件: $requiredFile"
    }
}

$fileList = Join-Path ([System.IO.Path]::GetTempPath()) "kikoerumanager-release-$ReleaseId-files.txt"
$localArchive = Join-Path ([System.IO.Path]::GetTempPath()) "kikoerumanager-release-$ReleaseId.tar.gz"
$remoteArchive = "/tmp/kikoerumanager-release-$ReleaseId.tar.gz"
$remoteScript = "/tmp/kikoerumanager-deploy-$ReleaseId.sh"
$forceValue = if ($Force) { '1' } else { '0' }
$dryRunValue = if ($DryRun) { '1' } else { '0' }
$packageOverrides = Join-Path ([System.IO.Path]::GetTempPath()) "kikoerumanager-image-$ReleaseId"

try {
    # 完整镜像也只使用本机构建的前端，生产不安装 Node 或运行 npm。
    & npm --prefix (Join-Path $repoRoot 'frontend') run build
    if ($LASTEXITCODE -ne 0) { throw '本地前端构建失败，拒绝发布。' }
    New-Item -ItemType Directory -Path $packageOverrides -ErrorAction Stop | Out-Null
    $dockerfile = [IO.File]::ReadAllText((Join-Path $repoRoot 'Dockerfile'))
    $runtimeStart = $dockerfile.IndexOf('# 阶段2：后端运行环境')
    if ($runtimeStart -lt 0) { throw 'Dockerfile 运行阶段标记不存在，拒绝改写构建快照。' }
    $imageDockerfile = "FROM scratch AS frontend-builder`nCOPY frontend/dist /app/frontend/dist`n`n" + $dockerfile.Substring($runtimeStart)
    [IO.File]::WriteAllText((Join-Path $packageOverrides 'Dockerfile'), $imageDockerfile, [Text.UTF8Encoding]::new($false))
    $dockerignore = [IO.File]::ReadAllText((Join-Path $repoRoot '.dockerignore')) + "`n!frontend/dist`n!frontend/dist/**`n"
    [IO.File]::WriteAllText((Join-Path $packageOverrides '.dockerignore'), $dockerignore, [Text.UTF8Encoding]::new($false))
    $sourceFiles = @($sourceFiles | Where-Object { $_ -notin @('Dockerfile', '.dockerignore') })
    $sourceFiles += @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'frontend/dist') -Recurse -File | ForEach-Object {
        [IO.Path]::GetRelativePath($repoRoot, $_.FullName).Replace('\', '/')
    })
    [System.IO.File]::WriteAllLines(
        $fileList,
        [string[]]$sourceFiles,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "发布版本: $ReleaseId" -ForegroundColor Cyan
    Write-Host "源码 revision: $sourceRevision" -ForegroundColor DarkGray
    Write-Host "源码文件数: $($sourceFiles.Count)" -ForegroundColor DarkGray
    Write-Host '上传远端发布脚本...' -ForegroundColor Yellow

    # 远端使用 POSIX sh，必须将 Windows CRLF 转为 LF，否则 ash 会把 `set -eu` 解析失败。
    $remoteScriptPayload = (Get-Content -LiteralPath $remoteScriptSource -Raw) -replace "`r`n", "`n" -replace "`r", "`n"
    $remoteScriptPayload |
        & $pwshExecutable -NoProfile -File $connectScript "umask 077; cat > '$remoteScript'; chmod 700 '$remoteScript'"
    if ($LASTEXITCODE -ne 0) {
        throw '远端发布脚本上传失败。'
    }

    Write-Host '上传当前工作区源码快照...' -ForegroundColor Yellow
    $archivePython = Join-Path $repoRoot 'backend/venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $archivePython)) {
        $archivePython = (Get-Command python -ErrorAction Stop).Source
    }
    & $archivePython (Join-Path $repoRoot 'tools/build-production-archive.py') $repoRoot $fileList $packageOverrides $localArchive
    if ($LASTEXITCODE -ne 0) {
        throw '源码快照打包失败，拒绝上传不完整的发布包。'
    }
    & tar.exe -C ([System.IO.Path]::GetTempPath()) -cf - ([System.IO.Path]::GetFileName($localArchive)) |
        & $pwshExecutable -NoProfile -File $connectScript "umask 077; tar -xf - -C /tmp"
    if ($LASTEXITCODE -ne 0) {
        throw '源码快照上传失败。'
    }

    Write-Host '由生产服务器构建并切换容器...' -ForegroundColor Yellow
    $archiveHash = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    & $connectScript -Sudo "/bin/sh '$remoteScript' '$remoteArchive' '$ReleaseId' '$sourceRevision' '$forceValue' '$dryRunValue' '$archiveHash'"
    if ($LASTEXITCODE -ne 0) {
        throw "生产发布失败，版本 $ReleaseId 未完成切换。"
    }

    Write-Host "生产发布完成: $ReleaseId" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $fileList -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $localArchive -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $packageOverrides) {
        Remove-Item -LiteralPath $packageOverrides -Recurse -Force
    }
}
