[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$venvRoot = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$localAppDataRoots = @($env:LOCALAPPDATA)
$repoParts = $repoRoot -split '[\\/]'
if ($repoParts.Length -ge 3 -and $repoParts[1] -eq 'Users') {
    # Sandboxed processes can have a different profile from the workspace owner.
    $workspaceProfile = Join-Path ($repoParts[0] + '\Users') $repoParts[2]
    $localAppDataRoots += Join-Path $workspaceProfile 'AppData\Local'
}
$localAppDataRoots = @($localAppDataRoots | Where-Object { $_ } | Select-Object -Unique)

function Test-Python311([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    try {
        & $Executable -B -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$basePython = $null
if (Test-Path -LiteralPath $venvRoot) {
    if (-not (Test-Python311 $venvPython)) {
        throw 'Existing .venv is not a usable Python 3.11 environment. Preserve or relocate it before bootstrapping again.'
    }
} else {
    $pythonCandidates = @(
        $env:CELLIVANE_PYTHON,
        'C:\Python311\python.exe',
        'C:\Program Files\Python311\python.exe'
    )
    foreach ($localRoot in $localAppDataRoots) {
        $pythonCandidates += Join-Path $localRoot 'Programs\Python\Python311\python.exe'
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $launcherResult = & $launcher.Source -3.11 -B -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $launcherResult) {
                $pythonCandidates += [string]($launcherResult | Select-Object -Last 1)
            }
        } catch { }
    }
    foreach ($commandName in @('python3.11.exe', 'python.exe', 'python3.exe')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch '\\WindowsApps\\') { $pythonCandidates += $command.Source }
    }
    foreach ($candidate in ($pythonCandidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Python311 $candidate) { $basePython = $candidate; break }
    }
    if (-not $basePython) {
        throw 'Python 3.11 is required. Install it separately or set CELLIVANE_PYTHON to its executable, then retry.'
    }
    & $basePython -B -m venv --without-pip $venvRoot
    if ($LASTEXITCODE -ne 0 -or -not (Test-Python311 $venvPython)) {
        throw 'Virtual environment creation failed. No packages were downloaded.'
    }
}

$configRoot = Join-Path $repoRoot '.cellivane'
$configPath = Join-Path $configRoot 'local-tools.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
    $basePython = & $venvPython -B -c 'import sys; print(sys._base_executable)'
    $winget = Join-Path $localAppDataRoots[0] 'Microsoft\WinGet\Packages'
    foreach ($localRoot in $localAppDataRoots) {
        $candidateWinget = Join-Path $localRoot 'Microsoft\WinGet\Packages'
        if (Test-Path -LiteralPath (Join-Path $candidateWinget 'BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin')) {
            $winget = $candidateWinget
            break
        }
    }
    $winlibsBin = Join-Path $winget 'BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin'
    $makePath = Join-Path $winget 'ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\make.exe'
    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
    $config = [ordered]@{
        python = $venvPython
        python_base = [string]$basePython
        git = $(if ($gitCommand) { $gitCommand.Source } else { '' })
        qemu = 'C:\Program Files\QEMU\qemu-system-x86_64.exe'
        make = $(if (Test-Path -LiteralPath $makePath) { $makePath } else { Join-Path $winlibsBin 'mingw32-make.exe' })
        nasm = (Join-Path $winlibsBin 'nasm.exe')
        x86_64_elf_root = (Join-Path $repoRoot '.toolchain\x86_64-elf')
        grub_root = (Join-Path $repoRoot '.toolchain\grub-2.12-for-windows')
        xorriso = ''
    }
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
}

Write-Output 'Python 3.11 environment ready: .venv (stdlib only; no package downloads).'
Write-Output 'Local tool locations: .cellivane/local-tools.json (keep this file untracked).'
