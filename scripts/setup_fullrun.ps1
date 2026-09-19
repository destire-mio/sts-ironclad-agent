param([int]$Jobs = 2)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.12 with the Python launcher.' }
    }
    $python = Join-Path $repo '.venv/Scripts/python.exe'
    & $python -m pip install -r requirements-fullrun.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    $env:PATH = (Join-Path $repo '.venv/Scripts') + ';' + $env:PATH
    & $python scripts/bootstrap_fullrun.py --jobs $Jobs --test
    if ($LASTEXITCODE -ne 0) { throw 'Simulator build/checks failed. See the first error above.' }
    & $python scripts/fullrun.py doctor
    if ($LASTEXITCODE -ne 0) { throw 'Runtime identity check failed.' }
} finally {
    Pop-Location
}
