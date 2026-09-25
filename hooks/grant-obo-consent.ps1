#!/usr/bin/env pwsh
#
# Windows counterpart of grant-obo-consent.sh (azd postprovision hook).
#
# Grant tenant-wide admin consent for the OBO server app's delegated Microsoft
# Graph `User.Read` permission.
#
# Why this is a hook and not Bicep
# --------------------------------
# The app registration *requests* User.Read declaratively in
# infra/modules/obo-entra-app.bicep (`requiredResourceAccess`) — that needs no
# special rights. Actually *granting* it is a different operation: an
# `oauth2PermissionGrants` with consentType `AllPrincipals` consents on behalf of
# every user in the tenant, which Microsoft Graph refuses unless the caller holds
# an Entra directory role. Azure RBAC does not help — subscription Owner confers
# nothing in the directory.
#
# When the grant lived in Bicep, deploying into a tenant where consent is
# admin-gated (the default for most corporate tenants) failed the entire
# provision with a bare `Authorization_RequestDenied`, giving no hint that the
# problem was an Entra role rather than an Azure one. Bicep cannot attempt a
# resource and continue when it is forbidden, so the grant moved here, where a
# 403 can be reported clearly and the deployment allowed to finish.
#
# Consequence of a skipped grant: OBO still works, but the first user to sign in
# is prompted to consent to User.Read themselves, or an administrator grants it
# once (see the instructions this script prints on failure).
#
# Idempotent and best-effort: re-running is safe (an existing grant is detected
# and left alone) and no failure mode aborts the deploy — this script always
# exits 0.

$ErrorActionPreference = 'Continue'
# See assign-agent-roles.ps1 — keep expected non-zero `az` exits non-terminating.
$PSNativeCommandUseErrorActionPreference = $false

$MsGraphAppId = '00000003-0000-0000-c000-000000000000'
$Scope = 'User.Read'

# Only meaningful when the OBO stack was actually provisioned. Mirrors the
# `condition:`/`if (deployObo)` gating in azure.yaml and infra/main.bicep.
$DeployObo = if ($env:DEPLOY_OBO) { $env:DEPLOY_OBO.ToLowerInvariant() } else { 'true' }
if ($DeployObo -notin @('1', 'true', 'yes')) {
    exit 0
}

$AppId = $env:OBO_SERVER_APP_CLIENT_ID
if (-not $AppId) {
    # Provisioning was skipped or the output is not in the environment. Nothing to
    # consent to; staying quiet avoids noise on every non-OBO deploy.
    exit 0
}

Write-Host "Granting admin consent for the OBO server app's Graph $Scope ..."

# The grant references service principal OBJECT ids, not app ids.
$ClientSpId = (az ad sp show --id $AppId --query id -o tsv 2>$null | Out-String).Trim()
$GraphSpId  = (az ad sp show --id $MsGraphAppId --query id -o tsv 2>$null | Out-String).Trim()

if (-not $ClientSpId -or -not $GraphSpId) {
    Write-Host '   WARNING: Could not resolve the service principals needed for the grant.'
    Write-Host '            Skipping — see the manual steps below.'
    $ClientSpId = ''
}

if ($ClientSpId) {
    # Already consented? Re-granting would create a duplicate grant object rather
    # than failing, so check first to keep repeat deploys genuinely idempotent.
    $FilterUrl = "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?`$filter=clientId eq '$ClientSpId' and resourceId eq '$GraphSpId'"
    $Existing = (az rest --method GET --url $FilterUrl --query 'value[].scope' -o tsv 2>$null | Out-String)

    # Each grant's scope is a space-separated list; match whole words only so
    # User.ReadWrite.All is never mistaken for User.Read.
    $AlreadyGranted = $false
    foreach ($Granted in ($Existing -split '\s+')) {
        if ($Granted.Trim() -eq $Scope) { $AlreadyGranted = $true; break }
    }

    if ($AlreadyGranted) {
        Write-Host '   [ok] Admin consent already in place (nothing to do).'
        exit 0
    }

    $Body = @{
        clientId    = $ClientSpId
        consentType = 'AllPrincipals'
        resourceId  = $GraphSpId
        scope       = $Scope
    } | ConvertTo-Json -Compress

    $ConsentOutput = (az rest --method POST `
        --url 'https://graph.microsoft.com/v1.0/oauth2PermissionGrants' `
        --headers 'Content-Type=application/json' `
        --body $Body `
        --output none 2>&1 | Out-String)

    if ($LASTEXITCODE -eq 0) {
        Write-Host '   [ok] Admin consent granted.'
        exit 0
    }

    if ($ConsentOutput -match 'Authorization_RequestDenied|Insufficient privileges|Forbidden') {
        Write-Host '   NOTE: Your account is not allowed to grant tenant-wide admin consent.'
        Write-Host '         This is expected in most corporate tenants and does NOT break the'
        Write-Host '         deployment — everything else provisioned normally.'
        Write-Host '         Granting consent needs an Entra ID directory role — Global'
        Write-Host '         Administrator, Privileged Role Administrator, or Cloud Application'
        Write-Host '         Administrator. Azure RBAC (even subscription Owner) does not'
        Write-Host '         include it.'
    } else {
        Write-Host '   WARNING: The consent request failed for an unexpected reason:'
        ($ConsentOutput -split "`r?`n" | Select-Object -First 10) | ForEach-Object {
            if ($_) { Write-Host "            $_" }
        }
    }
}

# Shown for every unsuccessful path, since the manual remedy is the same
# whether consent was forbidden, errored, or the lookups failed.
Write-Host @"
         Until someone grants it, OBO still works: the first user to sign in is
         asked to consent to Graph $Scope themselves.

         To grant it once, an administrator can run:
           az ad app permission admin-consent --id $AppId

         ...or open the app registration in the portal, go to
         "API permissions", and choose "Grant admin consent".
"@

exit 0
