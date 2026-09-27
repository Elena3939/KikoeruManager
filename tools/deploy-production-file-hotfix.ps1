[CmdletBinding()]
param(
    [string]$LocalFile = 'backend\app\core\library_folder_completion_service.py',
    [string]$ContainerPath = '/app/app/core/library_folder_completion_service.py',
    [string]$ReleaseId
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$connectScript = Join-Path $repoRoot '.codex\ssh\connect-production.ps1'
$remoteScriptSource = Join-Path $PSScriptRoot 'deploy-production-file-hotfix-remote.sh'
$pwshExecutable = (Get-Command pwsh -ErrorAction Stop).Source
$sourcePath = Join-Path $repoRoot $LocalFile

if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "本地文件不存在: $sourcePath"
}
if (-not (Test-Path -LiteralPath $remoteScriptSource -PathType Leaf)) {
    throw "远端热补丁脚本不存在: $remoteScriptSource"
}
if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
    $ReleaseId = "file-hotfix-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
if ($ReleaseId -notmatch '^[0-9A-Za-z][0-9A-Za-z-]{5,80}$') {
    throw "非法发布版本号: $ReleaseId"
}
if ($ContainerPath -notmatch '^/app/app/[A-Za-z0-9_./-]+\.py$') {
    throw "拒绝写入非 app Python 源码路径: $ContainerPath"
}

$expectedHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$remoteFile = "/tmp/kikoerumanager-$ReleaseId.py"
$remoteSourceDir = "/tmp/kikoerumanager-source-$ReleaseId"
$remoteScript = "/tmp/kikoerumanager-file-hotfix-$ReleaseId.sh"
$sourceDirectory = Split-Path -Parent $sourcePath
$sourceName = Split-Path -Leaf $sourcePath

Write-Host "同步文件: $LocalFile" -ForegroundColor Cyan
Write-Host "SHA-256: $expectedHash" -ForegroundColor DarkGray

Get-Content -LiteralPath $remoteScriptSource -Raw |
    & $pwshExecutable -NoProfile -File $connectScript "umask 077; cat > '$remoteScript'; chmod 700 '$remoteScript'"
if ($LASTEXITCODE -ne 0) {
    throw '远端热补丁脚本上传失败。'
}

& tar.exe -C $sourceDirectory -czf - $sourceName |
    & $pwshExecutable -NoProfile -File $connectScript "umask 077; rm -rf '$remoteSourceDir'; mkdir -p '$remoteSourceDir'; tar -xzf - -C '$remoteSourceDir'; mv '$remoteSourceDir/$sourceName' '$remoteFile'; rmdir '$remoteSourceDir'"
if ($LASTEXITCODE -ne 0) {
    throw '本地源码上传失败。'
}

& $connectScript -Sudo "/bin/sh '$remoteScript' '$remoteFile' '$ContainerPath' '$ReleaseId' '$expectedHash'"
if ($LASTEXITCODE -ne 0) {
    throw "生产热补丁失败: $ReleaseId"
}
