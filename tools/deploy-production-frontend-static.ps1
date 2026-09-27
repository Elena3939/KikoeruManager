[CmdletBinding()]
param([string]$ReleaseId)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$connect = Join-Path $root '.codex\ssh\connect-production.ps1'
$remoteSource = Join-Path $PSScriptRoot 'deploy-production-frontend-static-remote.sh'
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$dist = Join-Path $root 'frontend\dist'
if (-not (Test-Path -LiteralPath $dist -PathType Container)) { throw "前端构建产物不存在: $dist" }
if ([string]::IsNullOrWhiteSpace($ReleaseId)) { $ReleaseId = "frontend-static-$(Get-Date -Format 'yyyyMMdd-HHmmss')" }
$archive = "/tmp/kikoerumanager-$ReleaseId-dist.tar.gz"
$script = "/tmp/kikoerumanager-$ReleaseId.sh"
$remotePayload = (Get-Content -LiteralPath $remoteSource -Raw) -replace "`r`n", "`n" -replace "`r", "`n"
$remotePayload | & $pwsh -NoProfile -File $connect "umask 077; cat > '$script'; tr -d '\r' < '$script' > '$script.lf'; mv '$script.lf' '$script'; chmod 700 '$script'"
& tar.exe -C $dist -czf - . | & $pwsh -NoProfile -File $connect "umask 077; cat > '$archive'"
if ($LASTEXITCODE -ne 0) { throw '前端静态产物上传失败。' }
& $connect -Sudo "/bin/sh '$script' '$archive' '$ReleaseId'"
if ($LASTEXITCODE -ne 0) { throw "前端静态产物发布失败: $ReleaseId" }
