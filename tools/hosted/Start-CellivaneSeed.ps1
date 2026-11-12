param(
    [ValidateSet('serve', 'smoke')][string]$Mode = 'serve',
    [string]$StorageRoot = 'D:\AIOS\cellivane-seed-20261012',
    [string]$AssetRoot = 'D:\AIOS\cellivane-bridge-20261009'
)
$ErrorActionPreference = 'Stop'
& py -3 -B (Join-Path $PSScriptRoot 'cellivane_seed_lab.py') --mode $Mode --storage-root $StorageRoot --asset-root $AssetRoot
exit $LASTEXITCODE
