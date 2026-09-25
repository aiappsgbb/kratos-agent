#!/usr/bin/env pwsh
#
# Windows counterpart of check-azure-prereqs.sh (azd preprovision hook).
#
# Verifies the subscription-level prerequisites this template needs BEFORE
# `azd provision` creates anything. See the .sh for the full rationale; the
# short version is that the Container Apps environment joins a custom VNet and
# needs the Microsoft.Network/AllowBringYourOwnPublicIpAddress feature. Without
# it, provisioning fails ~15 minutes in, reports a misleading "resource already
# exists" error, and leaves a half-created environment that must be deleted by
# hand before any retry can succeed.
#
# The feature is a property of the subscription, not the machine — an
# unprepared subscription fails identically on macOS, Linux and Windows.
#
# Escape hatches:
#   $env:KRATOS_SKIP_PREREQ_CHECK = '1'   skip entirely (CI, or you know better)
#   $env:KRATOS_PREREQ_TIMEOUT_MIN = 'N'  how long to wait (default 15)

$ErrorActionPreference = 'Continue'
# `az` manages its own exit codes; we inspect $LASTEXITCODE ourselves. Without
# this, PowerShell 7.4+ turns an expected non-zero az exit into a terminating
# error before our checks run.
$PSNativeCommandUseErrorActionPreference = $false

if ($env:KRATOS_SKIP_PREREQ_CHECK -eq '1') { exit 0 }

$FeatureNamespace = 'Microsoft.Network'
$FeatureName = 'AllowBringYourOwnPublicIpAddress'
# Microsoft.ContainerService backs the cluster underneath a Container Apps
# environment. It is not auto-registered when the environment joins a custom
# VNet, and its absence produces an equally opaque failure.
$RequiredProviders = @('Microsoft.App', 'Microsoft.ContainerService')
$TimeoutMin = if ($env:KRATOS_PREREQ_TIMEOUT_MIN) { [int]$env:KRATOS_PREREQ_TIMEOUT_MIN } else { 15 }
$PollSeconds = 20

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host 'WARNING: Azure CLI (az) not found - skipping the subscription prerequisite check.'
    Write-Host '         If provisioning fails on the Container Apps environment, see:'
    Write-Host '         https://learn.microsoft.com/azure/container-apps/networking'
    exit 0
}

# azd puts the target subscription in the environment; fall back to whatever the
# CLI has selected so the script is still useful when run by hand.
$Subscription = $env:AZURE_SUBSCRIPTION_ID
if (-not $Subscription) {
    $Subscription = (az account show --query id -o tsv 2>$null | Out-String).Trim()
}
if (-not $Subscription) {
    Write-Host 'WARNING: No Azure subscription available yet - skipping the prerequisite check.'
    Write-Host "         Run 'az login' if provisioning then fails."
    exit 0
}

Write-Host 'Checking Azure subscription prerequisites...'

# -- Resource providers -------------------------------------------------------
$PendingProviders = @()
foreach ($Provider in $RequiredProviders) {
    $State = (az provider show --namespace $Provider --subscription $Subscription `
        --query registrationState -o tsv 2>$null | Out-String).Trim()
    if ($State -eq 'Registered') {
        Write-Host "  [ok]   $Provider"
        continue
    }
    $Shown = if ($State) { $State } else { 'unknown' }
    Write-Host "  [...]  $Provider is '$Shown' - registering..."
    az provider register --namespace $Provider --subscription $Subscription --only-show-errors 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $PendingProviders += $Provider
    } else {
        Write-Host "  WARNING: Could not register $Provider. You may lack permission on this"
        Write-Host '           subscription (Contributor or Owner is required).'
    }
}

# -- Feature flag -------------------------------------------------------------
function Get-FeatureState {
    return (az feature show --namespace $FeatureNamespace --name $FeatureName `
        --subscription $Subscription --query properties.state -o tsv 2>$null | Out-String).Trim()
}

$State = Get-FeatureState
if ($State -eq 'Registered') {
    Write-Host "  [ok]   $FeatureNamespace/$FeatureName"
} else {
    $Shown = if ($State) { $State } else { 'NotRegistered' }
    Write-Host "  [...]  $FeatureNamespace/$FeatureName is '$Shown' - registering..."
    Write-Host '         This is a one-time, subscription-wide operation. It is needed because'
    Write-Host '         the Container Apps environment joins your VNet and needs a public IP.'

    $RegisterErr = (az feature register --namespace $FeatureNamespace --name $FeatureName `
        --subscription $Subscription --only-show-errors 2>&1 | Out-String)

    if ($RegisterErr -match 'AuthorizationFailed|does not have authorization|Forbidden') {
        Write-Host ''
        Write-Host 'FAILED: You do not have permission to register features on this subscription.'
        Write-Host '        Registering needs Contributor or Owner. Ask an administrator to run:'
        Write-Host ''
        Write-Host "          az feature register --namespace $FeatureNamespace --name $FeatureName --subscription $Subscription"
        Write-Host "          az provider register --namespace $FeatureNamespace --subscription $Subscription"
        Write-Host ''
        Write-Host '        Nothing has been provisioned - your subscription is untouched.'
        exit 1
    }

    $Started = Get-Date
    $Deadline = $Started.AddMinutes($TimeoutMin)
    while ($true) {
        $State = Get-FeatureState
        if ($State -eq 'Registered') { break }
        if ((Get-Date) -ge $Deadline) {
            $Shown = if ($State) { $State } else { 'NotRegistered' }
            Write-Host ''
            Write-Host "FAILED: $FeatureName is still '$Shown' after ${TimeoutMin}m."
            Write-Host '        Azure has accepted the request - registration is a global operation'
            Write-Host '        and occasionally takes much longer.'
            Write-Host ''
            Write-Host '        Nothing has been provisioned, so there is nothing to clean up.'
            Write-Host "        Re-run 'azd up' once this prints 'Registered':"
            Write-Host ''
            Write-Host "          az feature show --namespace $FeatureNamespace --name $FeatureName ``"
            Write-Host '            --query properties.state -o tsv'
            Write-Host ''
            Write-Host '        To wait longer instead:  $env:KRATOS_PREREQ_TIMEOUT_MIN = "45"; azd up'
            Write-Host '        To skip this check:      $env:KRATOS_SKIP_PREREQ_CHECK = "1"; azd up'
            exit 1
        }
        $Elapsed = (Get-Date) - $Started
        Write-Host ("         waiting ({0:mm}m{0:ss}s / {1}m)..." -f $Elapsed, $TimeoutMin)
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Host '         [ok] registered.'

    # A freshly registered feature only takes effect once its resource provider is
    # re-registered - without this the deployment still fails as if nothing changed.
    Write-Host "  [...]  Propagating to $FeatureNamespace..."
    az provider register --namespace $FeatureNamespace --subscription $Subscription --only-show-errors 2>&1 | Out-Null
}

# Providers registered above are asynchronous too, but they settle in seconds and
# ARM tolerates a deployment racing them, so report rather than block.
foreach ($Provider in $PendingProviders) {
    $State = (az provider show --namespace $Provider --subscription $Subscription `
        --query registrationState -o tsv 2>$null | Out-String).Trim()
    if ($State -ne 'Registered') {
        Write-Host "  NOTE: $Provider is '$State' - it should finish during provisioning."
    }
}

Write-Host 'Prerequisites OK - starting provisioning.'
exit 0
