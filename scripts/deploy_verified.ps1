param([switch]$AuditOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$configuration = Get-Content -LiteralPath (Join-Path $taskRoot 'workspace.local.json') -Raw | ConvertFrom-Json
if (-not $configuration.game_root) { throw 'Configure game_root before deployment.' }
$gameRoot = [IO.Path]::GetFullPath($configuration.game_root)
$modDir = Join-Path $gameRoot 'sound\mod'
$packageDir = Join-Path $taskRoot 'test-package'
$names = @('masterbank.bank','masterbank.assets.bank','masterbank.strings.bank','tanks_engines.bank','tanks_engines.assets.bank')

function Get-Sha([string]$FilePath) {
    return (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-GameClosed {
    if (Get-Process -Name aces -ErrorAction SilentlyContinue) {
        throw 'War Thunder is running. Deployment stopped before moving banks.'
    }
}

Assert-GameClosed
$packageManifest = Get-Content -LiteralPath (Join-Path $packageDir 'manifest.json') -Raw | ConvertFrom-Json
$regression = Get-Content -LiteralPath (Join-Path $taskRoot 'reports\runtime_regression.json') -Raw | ConvertFrom-Json
$probe = Get-Content -LiteralPath (Join-Path $taskRoot 'reports\runtime-probe-test.json') -Raw | ConvertFrom-Json
$static = Get-Content -LiteralPath (Join-Path $taskRoot 'reports\test_package_verification.json') -Raw | ConvertFrom-Json
if ($regression.status -ne 'PASS_RUNTIME_LOAD_AND_OFFLINE_REGRESSION' -or $regression.parent_count -ne 72 -or
    $probe.status -ne 'PASS_BANK_LOAD_AND_SAMPLE_LOAD' -or -not $static.native_engine_bank_load_test) {
    throw 'Runtime or preservation review has not passed.'
}
if (@($probe.calls | Where-Object result -ne 0).Count) { throw 'Runtime probe contains API errors.' }
if ($packageManifest.files.Count -ne 5) { throw 'Unexpected package dependency list.' }
$newHashes = @{}
foreach ($name in $names) {
    $entry = @($packageManifest.files | Where-Object path -eq ('sound/mod/'+$name))
    if ($entry.Count -ne 1) { throw "Manifest mismatch: $name" }
    $hash = Get-Sha (Join-Path $packageDir ('sound\mod\'+$name))
    if ($hash -ne $entry[0].sha256 -or $hash -ne $regression.tested_banks.$name -or $hash -ne $probe.tested_banks.$name) {
        throw "Bank differs from runtime-tested artifact: $name"
    }
    $newHashes[$name] = $hash
}
$baseline = @(Get-Content -LiteralPath (Join-Path $taskRoot 'baseline\manifest.json') -Raw | ConvertFrom-Json)
$previousReceiptPath = Join-Path $taskRoot 'reports\deployment.latest.json'
if (Test-Path -LiteralPath $previousReceiptPath) {
    $previous = Get-Content -LiteralPath $previousReceiptPath -Raw | ConvertFrom-Json
    if ($previous.status -eq 'DEPLOYED') {
        foreach ($entry in $baseline) {
            if ($previous.newHashes.PSObject.Properties.Name -contains $entry.name) {
                $entry.sha256 = $previous.newHashes.($entry.name)
            }
        }
    }
}
foreach ($entry in $baseline) {
    if ((Get-Sha (Join-Path $modDir $entry.name)) -ne $entry.sha256) {
        throw "Installed baseline changed: $($entry.name)"
    }
}
if ($AuditOnly) {
    Write-Output 'PASS: reviewed package hashes, runtime reports, 72 parent cases, installed baseline, and game process state.'
    return
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $taskRoot ('deployment-backups\'+$stamp)
$stageDir = Join-Path $modDir ('._vox_stage_'+$stamp)
$resolvedMod = (Resolve-Path -LiteralPath $modDir).Path
if ($resolvedMod -ne (Join-Path $gameRoot 'sound\mod')) { throw 'Unexpected installation path.' }
if (-not $stageDir.StartsWith(($resolvedMod+'\'),[StringComparison]::OrdinalIgnoreCase) -or
    -not $backupDir.StartsWith(($taskRoot+'\deployment-backups\'),[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved deployment targets leave their intended directories.'
}
if ((Test-Path -LiteralPath $backupDir) -or (Test-Path -LiteralPath $stageDir)) { throw 'Deployment directories already exist.' }
New-Item -ItemType Directory -Path $backupDir,$stageDir | Out-Null
$receipt = [ordered]@{ status='STAGING'; timestamp=(Get-Date).ToString('o'); installation=$modDir; backup=$backupDir;
    staging=$stageDir; originalMoved=@(); deployed=@(); oldHashes=@{}; newHashes=$newHashes;
    runtime='FMOD 2.02.14 isolated load and offline replay'; inGameTest=$false; unrelatedBanksUnchanged=$false }
$receiptPath = Join-Path $taskRoot 'reports\deployment.latest.json'
function Save-Receipt {
    $json = $receipt | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($receiptPath,$json,[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $backupDir 'deployment.json'),$json,[Text.UTF8Encoding]::new($false))
}
Save-Receipt
try {
    foreach ($name in $names) {
        Copy-Item -LiteralPath (Join-Path $packageDir ('sound\mod\'+$name)) -Destination (Join-Path $stageDir $name)
        if ((Get-Sha (Join-Path $stageDir $name)) -ne $newHashes[$name]) { throw "Staging hash failed: $name" }
    }
    Assert-GameClosed
    foreach ($name in $names) {
        $target = Join-Path $modDir $name
        $handle = [IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
        $handle.Dispose()
    }
    $receipt.status='MOVING_ORIGINALS'; Save-Receipt
    foreach ($name in $names) {
        $entry = $baseline | Where-Object name -eq $name
        $target = Join-Path $modDir $name
        if ((Get-Sha $target) -ne $entry.sha256) { throw "Original changed during staging: $name" }
        Move-Item -LiteralPath $target -Destination (Join-Path $backupDir $name)
        $receipt.originalMoved += $name
        $receipt.oldHashes[$name] = $entry.sha256
        Save-Receipt
        if ((Get-Sha (Join-Path $backupDir $name)) -ne $entry.sha256) { throw "Moved backup hash failed: $name" }
    }
    $receipt.status='DEPLOYING'; Save-Receipt
    foreach ($name in $names) {
        Move-Item -LiteralPath (Join-Path $stageDir $name) -Destination (Join-Path $modDir $name)
        $receipt.deployed += $name
        Save-Receipt
    }
    foreach ($entry in $baseline) {
        $expected = if ($newHashes.ContainsKey($entry.name)) { $newHashes[$entry.name] } else { $entry.sha256 }
        if ((Get-Sha (Join-Path $modDir $entry.name)) -ne $expected) { throw "Post-deployment hash failed: $($entry.name)" }
    }
    foreach ($name in $names) {
        if ((Get-Sha (Join-Path $backupDir $name)) -ne $receipt.oldHashes[$name]) { throw "Backup recheck failed: $name" }
    }
    $receipt.status='DEPLOYED'; $receipt.unrelatedBanksUnchanged=$true; Save-Receipt
    # This is an empty directory created by this script; no recursive cleanup.
    Remove-Item -LiteralPath $stageDir
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'restore_deployment.ps1') -Destination (Join-Path $backupDir 'restore.ps1')
    Write-Output ($receipt | ConvertTo-Json -Depth 12)
} catch {
    $reason = $_.Exception.Message
    foreach ($name in $receipt.originalMoved) {
        $saved = Join-Path $backupDir $name
        if ((Get-Sha $saved) -ne $receipt.oldHashes[$name]) { throw "Rollback blocked by invalid backup: $name; $reason" }
        Copy-Item -LiteralPath $saved -Destination (Join-Path $modDir $name) -Force
        if ((Get-Sha (Join-Path $modDir $name)) -ne $receipt.oldHashes[$name]) { throw "Rollback verification failed: $name" }
    }
    $receipt.status='ROLLED_BACK'; $receipt.error=$reason; Save-Receipt
    throw "Deployment failed; moved originals restored. $reason"
}
