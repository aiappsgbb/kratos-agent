#!/usr/bin/env pwsh
#
# Windows counterpart of assign-agent-roles.sh (azd postdeploy hook).
#
# Apply least-privilege data-plane roles to the Foundry hosted-agent instance
# identity by deploying the declarative Bicep module
# infra/modules/agent-role-assignments.bicep.
#
# Why a hook is still required even though the roles live in IaC
# -------------------------------------------------------------
# A Foundry hosted agent (`host: azure.ai.agent`) runs under its own managed
# "AgentIdentity" service principal, created by `azd ai agent deploy` AFTER
# `azd provision` has already run the main Bicep deployment. A Bicep role
# assignment needs a principalId that already exists, so the agent identity
# cannot be referenced during provisioning.
#
# This hook performs the ONE thing Bicep cannot do — a Microsoft Entra ID lookup
# of the runtime-created agent identity — and then hands the resolved
# principalIds to the Bicep module, which declares the actual role assignments.
# The role *definitions, scopes and types* therefore live in IaC, not in shell.
#
# Idempotent and best-effort: re-running is safe (Bicep assignment names are
# deterministic), and failures are reported without aborting the deploy.
#
# Requirements: the deploying principal must be able to create role assignments
# (Owner or "User Access Administrator") — the same right `azd provision` already
# relies on for the Bicep role assignments. The Azure CLI must additionally be
# signed in to the subscription's home tenant, because the Entra lookup below
# runs through `az`, whose sign-in is independent of azd's.
#
# Exit codes mirror the .sh: 0 when done or when the identity is simply not
# created yet, 1 on a real failure. azure.yaml reports a non-zero exit and
# carries on, so a failure here never aborts the deploy.

$ErrorActionPreference = 'Continue'
# `az` is a native command that manages its own exit codes; we inspect
# $LASTEXITCODE ourselves. In PowerShell 7.4+ $PSNativeCommandUseErrorActionPreference
# defaults to $true, which would turn an expected non-zero az exit (e.g. an
# already-exists role assignment) into a terminating error before our check runs.
$PSNativeCommandUseErrorActionPreference = $false

$RoleModule = 'infra/modules/agent-role-assignments.bicep'
$DeploymentName = 'kratos-agent-role-assignments'

# ─── Context from the azd environment (all values are deployment-specific and
#     resolved at runtime — nothing about a particular tenant is baked in) ───
$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID
$ResourceGroup  = $env:AZURE_RESOURCE_GROUP
$ProjectId      = $env:AZURE_AI_PROJECT_ID           # .../accounts/<account>/projects/<project>
$CosmosEndpoint = $env:AZURE_COSMOS_DB_ENDPOINT      # https://<account>.documents.azure.com:443/
$StorageAccount = $env:AZURE_BLOB_STORAGE_ACCOUNT_NAME
$KeyVaultUri    = $env:AZURE_KEY_VAULT_URI           # https://<vault>.vault.azure.net/

if (-not $ProjectId -or -not $SubscriptionId -or -not $ResourceGroup) {
    Write-Host 'WARNING: AZURE_AI_PROJECT_ID / AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP not set.'
    Write-Host '         Skipping hosted-agent role assignment.'
    exit 0
}

if (-not (Test-Path $RoleModule -PathType Leaf)) {
    Write-Host "WARNING: $RoleModule not found (run from the repository root). Skipping."
    exit 0
}

# ─── Derive resource names from the azd environment ───
function Get-HostName {
    param([string] $Url)
    if ($Url -match '^[a-zA-Z]+://([^/:]+)') { return $Matches[1] }
    return ''
}

$FoundryAccount = if ($ProjectId -match '/accounts/([^/]+)/projects/') { $Matches[1] } else { '' }
$FoundryProject = if ($ProjectId -match '/projects/([^/]+)') { $Matches[1] } else { '' }
$CosmosName     = (Get-HostName $CosmosEndpoint) -split '\.' | Select-Object -First 1
$KeyVaultName   = (Get-HostName $KeyVaultUri) -split '\.' | Select-Object -First 1

Write-Host ''
Write-Host '=============================================================='
Write-Host '     Assign least-privilege roles to hosted agent(s)'
Write-Host '=============================================================='
Write-Host "  Foundry account : $FoundryAccount"
Write-Host "  Foundry project : $FoundryProject"
Write-Host "  Subscription    : $SubscriptionId"

if (-not $FoundryAccount -or -not $FoundryProject -or -not $CosmosName `
    -or -not $KeyVaultName -or -not $StorageAccount) {
    Write-Host 'WARNING: Could not derive all resource names from the azd environment. Skipping.'
    exit 0
}

# ─── Preflight: the lookup below runs through the Azure CLI, whose sign-in is
#     SEPARATE from azd's. Pointed at another directory, `az ad sp list` returns
#     an empty list with exit code 0 — indistinguishable from "the identity does
#     not exist yet" — so the roles are silently never applied while the deploy
#     still reports success.
#
#     The expected directory is the subscription's home tenant, not
#     AZURE_TENANT_ID: the postprovision hook in azure.yaml seeds that variable
#     from the active `az` session when unset, so comparing against it would let
#     a CLI in the wrong directory validate itself. ───
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: The Azure CLI ('az') is required to resolve the hosted-agent identity"
    Write-Host '       in Microsoft Entra ID, but it was not found on PATH.'
    exit 1
}

$AzTenant = (az account show --query tenantId -o tsv 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $AzTenant) {
    Write-Host "ERROR: Could not read the Azure CLI account context. azd's sign-in does not"
    Write-Host "       cover 'az'."
    Write-Host "       Fix: az login --tenant <home-tenant-of-$SubscriptionId> --use-device-code"
    exit 1
}
$AzSubscription = (az account show --query id -o tsv 2>$null | Out-String).Trim()

# The agent identity is created in the subscription's home tenant, so that — not
# a tenant the subscription merely happens to be reachable through — is the
# directory the lookup has to run against.
$SubTenants = @(
    (az account list --all --query "[?id=='$SubscriptionId'].homeTenantId" -o tsv 2>$null | Out-String) -split "`r?`n" |
        ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique
)

if ($SubTenants.Count -ne 1) {
    Write-Host "ERROR: Could not establish the deployment subscription's home tenant from the"
    Write-Host '       Azure CLI, so the directory to search cannot be confirmed.'
    Write-Host "         deployment subscription : $SubscriptionId"
    Write-Host "         az CLI active tenant    : $AzTenant"
    Write-Host '       Fix: az login --tenant <home-tenant-of-the-subscription> --use-device-code'
    Write-Host "            (if access is recent, try 'az account list --refresh' first)"
    exit 1
}
$SubTenant = $SubTenants[0]

if ($AzTenant -ne $SubTenant) {
    Write-Host 'ERROR: The Azure CLI is active in a different directory than the one holding'
    Write-Host '       the agent identity — the lookup would find nothing and the roles would'
    Write-Host '       silently never be applied.'
    Write-Host "         subscription's home tenant : $SubTenant"
    Write-Host "         az CLI active tenant       : $AzTenant"
    Write-Host "       Fix: az account set --subscription $SubscriptionId"
    Write-Host "            (or, if that does not switch directory: az login --tenant $SubTenant)"
    exit 1
}

Write-Host "  Directory       : $AzTenant (Azure CLI, verified)"
# Only the directory has to match. The role deployment below pins --subscription
# explicitly and the Entra lookup is directory-scoped, so a different active
# subscription is harmless -- but say so, rather than leaving it unexplained.
if ($AzSubscription -ne $SubscriptionId) {
    Write-Host "  Note: the Azure CLI's active subscription is $AzSubscription,"
    Write-Host '        not the deployment subscription above. That is fine here —'
    Write-Host '        only the directory matters for the identity lookup.'
}

# ─── Resolve the hosted-agent instance identity (the Entra lookup Bicep can't do) ───
# Foundry names the agent's service principal deterministically:
#   <account>-<project>-<agentName>-AgentIdentity
# Matching the "<account>-<project>-" prefix plus the "-AgentIdentity" suffix
# discovers every hosted agent under this project without hard-coding the agent
# name, so the hook keeps working if the template is renamed or grows more agents.
$Prefix = "$FoundryAccount-$FoundryProject-"
# stderr is deliberately not discarded: a genuine query failure has to be
# distinguishable from an empty directory.
$RawIds = (az ad sp list --display-name $Prefix `
    --query "[?ends_with(displayName, '-AgentIdentity')].id" -o tsv | Out-String)
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: Could not query the hosted-agent identity in Microsoft Entra ID.'
    Write-Host '       The signed-in principal needs permission to read directory objects.'
    exit 1
}

$AgentPrincipalIds = @(
    $RawIds -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
)

if ($AgentPrincipalIds.Count -eq 0) {
    Write-Host "WARNING: No '*-AgentIdentity' service principal found yet for prefix '$Prefix'."
    Write-Host '         The hosted agent identity may still be propagating in Microsoft Entra ID.'
    Write-Host "         Re-run 'azd deploy kratos-agent' (or 'azd up') once it appears."
    exit 0
}

foreach ($Id in $AgentPrincipalIds) {
    Write-Host "  Discovered agent identity: $Id"
}

# ─── Apply the declarative Bicep role-assignment module ───
# Parameters go through an ARM parameter FILE rather than `--parameters key=value`.
# agentPrincipalIds is an array, and passing a JSON literal as a native-command
# argument is where PowerShell quoting reliably goes wrong; a file sidesteps it.
Write-Host ''
Write-Host "  Deploying $RoleModule (declarative role assignments)..."

$ParamFile = Join-Path ([System.IO.Path]::GetTempPath()) "kratos-agent-roles-$PID.json"
$ParamDoc = [ordered]@{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = [ordered]@{
        agentPrincipalIds   = @{ value = $AgentPrincipalIds }
        cosmosDbAccountName = @{ value = $CosmosName }
        aiServicesName      = @{ value = $FoundryAccount }
        keyVaultName        = @{ value = $KeyVaultName }
        storageAccountName  = @{ value = $StorageAccount }
    }
}

$Failed = $false
try {
    $ParamDoc | ConvertTo-Json -Depth 5 | Set-Content -Path $ParamFile -Encoding utf8

    $DeployOutput = (az deployment group create `
        --name $DeploymentName `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroup `
        --template-file $RoleModule `
        --parameters "@$ParamFile" `
        --only-show-errors `
        --output none 2>&1 | Out-String)

    if ($LASTEXITCODE -eq 0) {
        Write-Host '   [ok] Hosted-agent role assignments applied.'
        Write-Host '        Data-plane role propagation can take a few minutes before the'
        Write-Host "        agent's first successful model / Cosmos call."
    } elseif ($DeployOutput -match 'RoleAssignmentExists' -and
              $DeployOutput -notmatch '"code":\s*"(AuthorizationFailed|InvalidTemplate|InvalidTemplateDeployment|PrincipalNotFound|LinkedAuthorizationFailed)"') {
        # ARM fails the whole deployment when a role assignment already exists, even
        # though that is exactly the state we want. Re-running the hook (e.g. on every
        # `azd deploy`) therefore "failed" while being fully converged. Treat an
        # exists-only failure as success so repeat deploys are genuinely idempotent,
        # but still surface any real error such as a missing permission.
        Write-Host '   [ok] Hosted-agent role assignments already in place (nothing to do).'
    } else {
        Write-Host '   WARNING: Role-assignment deployment failed.'
        Write-Host '            Verify the deploying principal has Owner or User Access Administrator.'
        Write-Host "            The hosted agent's permissions could not be fully applied or verified;"
        Write-Host '            invocations may fail with HTTP 401 PermissionDenied until this succeeds.'
        ($DeployOutput -split "`r?`n" | Select-Object -First 20) | ForEach-Object {
            if ($_) { Write-Host "            $_" }
        }
        $Failed = $true
    }
} finally {
    Remove-Item $ParamFile -Force -ErrorAction SilentlyContinue
}

if ($Failed) { exit 1 }
exit 0
