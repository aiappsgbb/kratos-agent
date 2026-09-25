#!/usr/bin/env pwsh
#
# Windows counterpart of postdeploy.sh (azd postdeploy hook).
#
# Uploads the selected use-cases' skills to blob storage after a deploy.
#
# NOTE: this is not the same script as the one the project exporter ships as
# hooks/postdeploy.ps1 in an exported agent — that one grants RBAC to the
# identities from `azd ai agent show`. Here, RBAC is assign-agent-roles.ps1's
# job and this hook only does the skills upload.

[CmdletBinding()]
param(
    # azd passes -FromDeploy. A deploy must never stop and wait for input at the
    # end, so that flag makes prompting impossible no matter what state anything
    # else is in; the answer must have been given up front by
    # hooks/select-use-cases.ps1. Run this script by hand and you get the same
    # behaviour minus the "no selection recorded" shortcut.
    [switch] $FromDeploy
)

$ErrorActionPreference = 'Continue'
# See assign-agent-roles.ps1 — keep expected non-zero `az` exits non-terminating.
$PSNativeCommandUseErrorActionPreference = $false

$ContainerName = 'skills'
$StorageAccount = $env:AZURE_BLOB_STORAGE_ACCOUNT_NAME
$UseCasesDir = 'use-cases'

# Written by hooks/select-use-cases.ps1 at preprovision time.
$EnvName = if ($env:AZURE_ENV_NAME) { $env:AZURE_ENV_NAME } else { 'default' }
$SelectionFile = Join-Path (Join-Path '.azure' $EnvName) 'kratos-upload-selection'

if (-not $StorageAccount) {
    Write-Host 'WARNING: AZURE_BLOB_STORAGE_ACCOUNT_NAME is not set. Skipping skills upload.'
    exit 0
}

if (-not (Test-Path $UseCasesDir -PathType Container)) {
    Write-Host "WARNING: '$UseCasesDir' directory not found. Skipping skills upload."
    exit 0
}

# Discover available use-cases
$UseCases = @(Get-ChildItem -Path $UseCasesDir -Directory -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Name | Sort-Object)

if ($UseCases.Count -eq 0) {
    Write-Host "WARNING: No use-cases found in '$UseCasesDir'. Skipping skills upload."
    exit 0
}

Write-Host ''
Write-Host '=============================================================='
Write-Host '          Upload Skills to Azure Blob Storage'
Write-Host '=============================================================='
Write-Host "  Storage Account: $StorageAccount"
Write-Host "  Container:       $ContainerName"
Write-Host '=============================================================='
Write-Host ''

# Never prompt here — on Windows nothing prompts at all (see
# hooks/select-use-cases.ps1 for why). This hook just carries out the choice.
$Selection = ''
if (Test-Path $SelectionFile) {
    $Selection = (Get-Content $SelectionFile -First 1 -ErrorAction SilentlyContinue) -replace '\s', ''
    Remove-Item $SelectionFile -Force -ErrorAction SilentlyContinue
}

# Direct env override, and the legacy flag, still work for scripted runs.
if ($env:KRATOS_UPLOAD_USE_CASES) {
    $Selection = $env:KRATOS_UPLOAD_USE_CASES
} elseif (-not $Selection -and $env:KRATOS_AUTO_UPLOAD_USE_CASES -eq '1') {
    $Selection = 'all'
}

if (-not $Selection) {
    if ($FromDeploy) {
        # Either preprovision never ran (a bare `azd deploy` has no provision
        # phase) or its answer went missing.
        Write-Host 'NOTE: No skills selection was recorded, so nothing was uploaded.'
        Write-Host "      (expected a file at $SelectionFile)"
        Write-Host '      To upload now:  $env:KRATOS_UPLOAD_USE_CASES = "all"; ./hooks/postdeploy.ps1'
    } else {
        Write-Host 'NOTE: No skills upload was requested, so nothing was uploaded.'
        Write-Host '      To upload:  $env:KRATOS_UPLOAD_USE_CASES = "all"; ./hooks/postdeploy.ps1'
    }
    exit 0
}

if ($Selection -eq 'none') {
    Write-Host 'Skipping skills upload.'
    exit 0
}

$Selected = @()
if ($Selection -eq 'all') {
    $Selected = $UseCases
} else {
    # A comma-separated list of use-case names. Numbers are still accepted for
    # anyone setting the env var by hand.
    foreach ($Part in ($Selection -split ',')) {
        $Part = ($Part -replace '\s', '')
        if (-not $Part) { continue }
        if ($Part -match '^\d+$' -and [int]$Part -ge 1 -and [int]$Part -le $UseCases.Count) {
            $Selected += $UseCases[[int]$Part - 1]
        } elseif (Test-Path (Join-Path $UseCasesDir $Part) -PathType Container) {
            $Selected += $Part
        } else {
            Write-Host "WARNING: Unknown use-case: $Part"
        }
    }
}

if ($Selected.Count -eq 0) {
    Write-Host 'No valid use-cases selected. Skipping.'
    exit 0
}

# The storage account is commonly unreachable from the machine running `azd up`:
# it sits behind a private endpoint, and many subscriptions carry a policy that
# forces `publicNetworkAccess: Disabled` (re-applying it within seconds if you
# flip it). Azure Storage reports that denial as `AuthorizationFailure`, which
# reads like an RBAC problem but is a *network* one.
#
# This upload is a convenience, not a requirement: the backend seeds the same
# use-cases from the copy baked into its container image on startup, so the app
# is fully functional either way. Probe once, explain clearly, and let the
# deployment succeed rather than failing `azd up` over an optional step.
$ProbeErr = (az storage blob list `
    --account-name $StorageAccount `
    --container-name $ContainerName `
    --num-results 1 `
    --auth-mode login `
    --only-show-errors `
    --output none 2>&1 | Out-String)

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host "WARNING: Storage account '$StorageAccount' is not reachable from this machine,"
    Write-Host '         so the skills upload was skipped.'
    Write-Host ''
    if ($ProbeErr -match 'AuthorizationFailure|network rule|not authorized|public access') {
        Write-Host '         Cause: the account denies traffic from this network. It is reachable'
        Write-Host '         over its private endpoint from inside the VNet, and a subscription'
        Write-Host '         policy may also be forcing public access off.'
    } else {
        $FirstLine = ($ProbeErr -split "`r?`n" | Where-Object { $_ } | Select-Object -First 1)
        Write-Host "         Cause: $FirstLine"
    }
    Write-Host ''
    Write-Host '         This is not fatal. The backend seeds the same use-cases from its'
    Write-Host '         container image at startup, so the deployed app already has them.'
    Write-Host '         Upload here only matters if you edit use-cases without redeploying.'
    Write-Host ''
    Write-Host '         To upload anyway, run this from a machine on the VNet, or from the'
    Write-Host '         running backend container:'
    Write-Host '           az containerapp exec -g <resource-group> -n <agent-container-app> \'
    Write-Host '             --revision <running-revision> --command /bin/bash'
    exit 0
}

$Failed = @()
foreach ($UseCase in $Selected) {
    $LocalPath = Join-Path $UseCasesDir $UseCase
    Write-Host ''
    Write-Host "Uploading '$UseCase' -> blob://$ContainerName/$UseCase/ ..."

    # Delete existing blobs for this use-case first (replace, not merge), BUT
    # preserve eval run history under evals/runs/ — those are runtime artefacts
    # written by the backend, not source-controlled inputs we ship from the repo.
    # Without this guard, every postdeploy wipes the entire eval history and
    # the e2e-smoke `04-evals` spec fails until a fresh validation run is queued.
    Write-Host "   Clearing existing blobs under 'use-cases/$UseCase/' (preserving evals/runs/)..."
    $ExistingBlobs = (az storage blob list `
        --account-name $StorageAccount `
        --container-name $ContainerName `
        --prefix "use-cases/$UseCase/" `
        --auth-mode login `
        --query "[?!contains(name, '/evals/runs/')].name" `
        --output tsv 2>$null | Out-String)

    foreach ($BlobName in ($ExistingBlobs -split "`r?`n")) {
        $BlobName = $BlobName.Trim()
        if (-not $BlobName) { continue }
        az storage blob delete `
            --account-name $StorageAccount `
            --container-name $ContainerName `
            --name $BlobName `
            --auth-mode login `
            --only-show-errors `
            --output none 2>$null | Out-Null
    }

    # Upload all files from the local use-case folder
    az storage blob upload-batch `
        --account-name $StorageAccount `
        --destination $ContainerName `
        --source $LocalPath `
        --destination-path "use-cases/$UseCase" `
        --auth-mode login `
        --overwrite `
        --only-show-errors `
        --output none

    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [ok] '$UseCase' uploaded successfully."
    } else {
        Write-Host "   WARNING: '$UseCase' failed to upload."
        $Failed += $UseCase
    }
}

Write-Host ''
if ($Failed.Count -eq 0) {
    Write-Host 'Skills upload complete.'
} else {
    Write-Host "WARNING: Skills upload finished with $($Failed.Count) failure(s): $($Failed -join ', ')"
    Write-Host '         The deployed app still serves the copy baked into its container'
    Write-Host '         image, so this does not block the deployment. Re-run'
    Write-Host '         ./hooks/postdeploy.ps1 once the storage account is reachable.'
}

exit 0
