[CmdletBinding()]
param(
    [ValidateSet('bootstrap', 'doctor', 'hosted', 'testkit', 'seed', 'all')]
    [string]$Action = 'doctor',
    [switch]$Json,
    [switch]$Native,
    [ValidateRange(1, 86400)][int]$TimeoutSeconds = 1800
)
$ErrorActionPreference = 'Stop'
$workspaceTools = Join-Path $PSScriptRoot 'tools\workspace'
if ($Action -eq 'bootstrap') {
    & (Join-Path $workspaceTools 'bootstrap.ps1')
    exit 0
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Run .\dev.ps1 bootstrap before using this workspace.'
}
if ($Action -eq 'doctor') {
    $toolArgs = @('-B', (Join-Path $workspaceTools 'doctor.py'))
    if ($Native) { $toolArgs += '--native' }
} else {
    if ($Native) { throw '-Native is supported only for the doctor action.' }
    $toolArgs = @('-B', (Join-Path $workspaceTools 'check.py'), '--suite', $Action, '--timeout-seconds', $TimeoutSeconds)
}
if ($Json) { $toolArgs += '--json' }
& $python @toolArgs
exit $LASTEXITCODE
