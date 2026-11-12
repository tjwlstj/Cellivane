param(
    [ValidateSet('subengine-smoke', 'strata-reference')]
    [string]$Profile = 'strata-reference',
    [string]$Prompt = 'Reply with only the number: 7 + 8 =',
    [string]$StorageRoot = 'D:\AIOS\cellivane-bridge-20261009',
    [switch]$Benchmark,
    [switch]$ParallelSmoke
)
$ErrorActionPreference = 'Stop'
$taskScript = Join-Path $PSScriptRoot 'cellivane_bridge_lab.py'
$taskArguments = @('-3', '-B', $taskScript, '--storage-root', $StorageRoot, '--profile', $Profile, '--prompt', $Prompt)
if ($Benchmark) { $taskArguments += '--benchmark' }
if ($ParallelSmoke) { $taskArguments += '--parallel-smoke' }
& py @taskArguments
exit $LASTEXITCODE
