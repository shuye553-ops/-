$ErrorActionPreference = 'Stop'
# Use the copy inside a dated deployment backup directory.
$recordPath = Join-Path $PSScriptRoot 'deployment.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'Run restore.ps1 from the dated backup folder.' }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if (Get-Process -Name aces -ErrorAction SilentlyContinue) { throw 'Exit War Thunder before restoring.' }
$names = @('masterbank.bank','masterbank.assets.bank','masterbank.strings.bank','tanks_engines.bank','tanks_engines.assets.bank')
foreach ($name in $names) {
    $saved = Join-Path $PSScriptRoot $name
    $target = Join-Path $record.installation $name
    if ((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.oldHashes.$name) {
        throw "Backup hash mismatch: $name"
    }
    $current = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($current -ne $record.newHashes.$name -and $current -ne $record.oldHashes.$name) {
        throw "Installed file changed after deployment; review it before restoring: $name"
    }
}
foreach ($name in $names) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $record.installation $name) -Force
    if ((Get-FileHash -LiteralPath (Join-Path $record.installation $name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.oldHashes.$name) {
        throw "Restore verification failed: $name"
    }
}
Write-Output 'Restored all five banks. Backup copies remain in this folder.'
