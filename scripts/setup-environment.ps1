param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    & $Python -c "import sys; assert sys.version_info[:2] == (3, 12), 'Use Python 3.12 for the validated environment'"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported or unavailable Python interpreter' }
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
    & ./.venv/Scripts/python.exe -m pip install -r requirements-dev-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & ./.venv/Scripts/python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
} finally {
    Pop-Location
}
