$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$configuration = Get-Content -LiteralPath (Join-Path $taskRoot 'workspace.local.json') -Raw | ConvertFrom-Json
$pythonExe = $configuration.python_exe
if (-not $pythonExe) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
Push-Location $taskRoot
try {
    & $pythonExe -B scripts/build_test_package.py
    if ($LASTEXITCODE -ne 0) { throw 'Test bank build failed' }
    & $pythonExe -B scripts/runtime_probe.py --variant test --debug
    if ($LASTEXITCODE -ne 0) { throw 'Native runtime load failed' }
    & $pythonExe -B scripts/runtime_regression.py
    if ($LASTEXITCODE -ne 0) { throw 'Offline playback regression failed' }
    & $pythonExe -B scripts/verify_test_package.py
    if ($LASTEXITCODE -ne 0) { throw 'Verification failed; do not distribute' }
    & $pythonExe -B scripts/package_delivery.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
} finally {
    Pop-Location
}
