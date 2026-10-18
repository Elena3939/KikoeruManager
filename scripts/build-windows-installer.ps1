param(
    [string]$Version = '',
    [string]$PostgresRoot = '',
    [string]$InnoCompiler = '',
    [switch]$SkipFrontend,
    [switch]$SkipFreeze
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
if (!$Version) {
    $tag = & git describe --tags --abbrev=0 --match 'v*.*.*'
    if ($LASTEXITCODE) { throw '无法读取当前版本 tag，请显式指定 -Version。' }
    $Version = $tag.Trim() -replace '^v', ''
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw '版本号必须为 X.Y.Z' }
$cache = Join-Path $root '.runtime/installer-cache'
$output = Join-Path $root 'output/windows'
$stage = Join-Path $output 'app'
$python = Join-Path $root 'backend/venv/Scripts/python.exe'
if (!(Test-Path $python)) { throw '构建机需要 backend/venv，用户机器不需要 Python。' }
& $python scripts/create-installer-assets.py
if ($LASTEXITCODE) { throw '安装器图标生成失败' }
New-Item -ItemType Directory -Force $cache,$stage | Out-Null
function Download-Package($Name, $Url, $Sha256) {
    $path = Join-Path $cache $Name
    if (!(Test-Path $path)) { Invoke-WebRequest $Url -OutFile $path -TimeoutSec 600 }
    if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $Sha256) { throw "依赖校验失败：$Name" }
    return $path
}
function Copy-Tree($Source, $Target) {
    New-Item -ItemType Directory -Force $Target | Out-Null
    Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force
}
if (!$SkipFrontend) {
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE) { throw '前端构建失败' }
}
if (!$SkipFreeze) {
    & $python -m PyInstaller packaging/windows/app.spec --noconfirm --distpath output/windows/frozen --workpath .runtime/installer-build
    if ($LASTEXITCODE) { throw '应用打包失败' }
}
Copy-Tree (Join-Path $output 'frozen/KikoeruManager') $stage
$runtime = Join-Path $stage 'runtime'
if (!$PostgresRoot) { $PostgresRoot = Join-Path $root 'data/postgresql/pgsql' }
if (!(Test-Path (Join-Path $PostgresRoot 'bin/initdb.exe'))) { throw '请用 -PostgresRoot 指定 PostgreSQL 18 二进制目录，禁止提供数据库数据目录。' }
foreach ($folder in @('bin','lib','share')) {
    Copy-Tree (Join-Path $PostgresRoot $folder) (Join-Path $runtime "postgresql/$folder")
}
Copy-Item (Join-Path $PostgresRoot '*license*.txt') (Join-Path $runtime 'postgresql') -Force
$redis = Download-Package 'redis.zip' 'https://github.com/redis-windows/redis-windows/releases/download/8.10.2/Redis-8.10.2-Windows-x64-msys2.zip' '7C8CEBD50347EAA1D9E784DA842ED47A4F33394637835531D6614777B950EE85'
Expand-Archive $redis (Join-Path $cache 'redis') -Force
Copy-Tree (Join-Path $cache 'redis/Redis-8.10.2-Windows-x64-msys2') (Join-Path $runtime 'redis')
$sevenZip = Download-Package '7zip-full.exe' 'https://github.com/ip7z/7zip/releases/download/26.04/7z2604-x64.exe' 'D54BF805F9F3704D1E8DB2FA3498AE7EF2DF0312B40B558E7C71C734430A665D'
$extractor = (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source
if (!$extractor) { $extractor = 'C:/Program Files/7-Zip/7z.exe' }
& $extractor x $sevenZip "-o$(Join-Path $runtime '7zip')" -y
if ($LASTEXITCODE) { throw '7-Zip 解包失败' }
foreach ($tool in @(@('aria2','aria2'), @('baidupcs-go','baidupcs'), @('unar','unar'))) {
    Copy-Tree (Join-Path $root "tools/$($tool[0])") (Join-Path $runtime $tool[1])
}
$redisLicenses = Join-Path $runtime 'redis/LICENCES'
New-Item -ItemType Directory -Force $redisLicenses | Out-Null
Copy-Tree (Join-Path $cache 'redis-licenses') $redisLicenses
foreach ($license in @('Redis-LICENSE.txt','Redis-Windows-LICENSE.txt')) {
    $source = Join-Path $cache $license
    if (!(Test-Path $source)) { throw "缺少第三方许可证：$source" }
    Copy-Item $source $redisLicenses -Force
}
# Python 自带的 VC 运行库随 PostgreSQL 携带，用户不需要另装开发环境。
Get-ChildItem (Join-Path $stage '_internal') -File | Where-Object { $_.Name -match '^(vcruntime|msvcp).*\.dll$' } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $runtime 'postgresql/bin') -Force
}
# 打包版本和依赖文件摘要，不包含本机配置或数据库。
@{ version=$Version; runtime='embedded'; dataLocation='LocalAppData/KikoeruManager' } | ConvertTo-Json | Set-Content (Join-Path $stage 'desktop-install.json') -Encoding utf8
$versionDir = Join-Path $stage '_internal/backend/app'
New-Item -ItemType Directory -Force $versionDir | Out-Null
Set-Content (Join-Path $versionDir 'version.txt') $Version -Encoding utf8
Get-ChildItem $runtime -Recurse -File | ForEach-Object {
    @{ path=[IO.Path]::GetRelativePath($runtime,$_.FullName); sha256=(Get-FileHash $_.FullName).Hash }
} | ConvertTo-Json | Set-Content (Join-Path $stage 'runtime-manifest.json') -Encoding utf8
if (!$InnoCompiler) { $InnoCompiler = Join-Path $root '.runtime/inno/ISCC.exe' }
& $InnoCompiler "/DAppVersion=$Version" "/DSourceDir=$stage" "/DOutputDirPath=$output" packaging/windows/installer.iss
if ($LASTEXITCODE) { throw '安装器编译失败' }
$exe = Join-Path $output "KikoeruManager-Setup-v$Version-x64.exe"
"$((Get-FileHash $exe).Hash.ToLower())  $([IO.Path]::GetFileName($exe))" | Set-Content (Join-Path $output 'SHA256SUMS.txt') -Encoding ascii
Write-Host "安装包已生成：$exe"
