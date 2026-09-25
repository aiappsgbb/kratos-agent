#!/usr/bin/env bash
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

set -uo pipefail

ROLE_MODULE="infra/modules/agent-role-assignments.bicep"
DEPLOYMENT_NAME="kratos-agent-role-assignments"

# ─── Context from the azd environment (all values are deployment-specific and
#     resolved at runtime — nothing about a particular tenant is baked in) ───
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
PROJECT_ID="${AZURE_AI_PROJECT_ID:-}"            # .../accounts/<account>/projects/<project>
COSMOS_ENDPOINT="${AZURE_COSMOS_DB_ENDPOINT:-}"  # https://<account>.documents.azure.com:443/
STORAGE_ACCOUNT="${AZURE_BLOB_STORAGE_ACCOUNT_NAME:-}"
KEY_VAULT_URI="${AZURE_KEY_VAULT_URI:-}"          # https://<vault>.vault.azure.net/

if [ -z "$PROJECT_ID" ] || [ -z "$SUBSCRIPTION_ID" ] || [ -z "$RESOURCE_GROUP" ]; then
  echo "⚠️  AZURE_AI_PROJECT_ID / AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP not set."
  echo "    Skipping hosted-agent role assignment."
  exit 0
fi

if [ ! -f "$ROLE_MODULE" ]; then
  echo "⚠️  $ROLE_MODULE not found (run from the repository root). Skipping."
  exit 0
fi

# ─── Derive resource names from the azd environment ───
host_of() { printf '%s' "$1" | sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#'; }

FOUNDRY_ACCOUNT="$(printf '%s' "$PROJECT_ID" | sed -nE 's#.*/accounts/([^/]+)/projects/.*#\1#p')"
FOUNDRY_PROJECT="$(printf '%s' "$PROJECT_ID" | sed -nE 's#.*/projects/([^/]+).*#\1#p')"
COSMOS_NAME="$(host_of "$COSMOS_ENDPOINT" | cut -d. -f1)"
KEY_VAULT_NAME="$(host_of "$KEY_VAULT_URI" | cut -d. -f1)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     Assign least-privilege roles to hosted agent(s)      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Foundry account : ${FOUNDRY_ACCOUNT}"
echo "  Foundry project : ${FOUNDRY_PROJECT}"
echo "  Subscription    : ${SUBSCRIPTION_ID}"

if [ -z "$FOUNDRY_ACCOUNT" ] || [ -z "$FOUNDRY_PROJECT" ] || [ -z "$COSMOS_NAME" ] \
   || [ -z "$KEY_VAULT_NAME" ] || [ -z "$STORAGE_ACCOUNT" ]; then
  echo "⚠️  Could not derive all resource names from the azd environment. Skipping."
  exit 0
fi

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
if ! command -v az >/dev/null 2>&1; then
  echo "❌ The Azure CLI ('az') is required to resolve the hosted-agent identity"
  echo "   in Microsoft Entra ID, but it was not found on PATH."
  exit 1
fi

if ! AZ_TENANT="$(az account show --query tenantId -o tsv 2>/dev/null)" || [ -z "$AZ_TENANT" ]; then
  echo "❌ Could not read the Azure CLI account context. azd's sign-in does not"
  echo "   cover 'az'."
  echo "   Fix: az login --tenant <home-tenant-of-${SUBSCRIPTION_ID}> --use-device-code"
  exit 1
fi
AZ_SUBSCRIPTION="$(az account show --query id -o tsv 2>/dev/null)"

# The agent identity is created in the subscription's home tenant, so that — not
# a tenant the subscription merely happens to be reachable through — is the
# directory the lookup has to run against.
SUB_TENANT="$(az account list --all \
  --query "[?id=='${SUBSCRIPTION_ID}'].homeTenantId" -o tsv 2>/dev/null \
  | grep -v '^$' | sort -u)"

if [ -z "$SUB_TENANT" ] || [ "$(printf '%s\n' "$SUB_TENANT" | wc -l)" -ne 1 ]; then
  echo "❌ Could not establish the deployment subscription's home tenant from the"
  echo "   Azure CLI, so the directory to search cannot be confirmed."
  echo "     deployment subscription : ${SUBSCRIPTION_ID}"
  echo "     az CLI active tenant    : ${AZ_TENANT}"
  echo "   Fix: az login --tenant <home-tenant-of-the-subscription> --use-device-code"
  echo "        (if access is recent, try 'az account list --refresh' first)"
  exit 1
fi

if [ "$AZ_TENANT" != "$SUB_TENANT" ]; then
  echo "❌ The Azure CLI is active in a different directory than the one holding"
  echo "   the agent identity — the lookup would find nothing and the roles would"
  echo "   silently never be applied."
  echo "     subscription's home tenant : ${SUB_TENANT}"
  echo "     az CLI active tenant       : ${AZ_TENANT}"
  echo "   Fix: az account set --subscription ${SUBSCRIPTION_ID}"
  echo "        (or, if that does not switch directory: az login --tenant ${SUB_TENANT})"
  exit 1
fi

echo "  Directory       : ${AZ_TENANT} (Azure CLI, verified)"
# Only the directory has to match. The role deployment below pins --subscription
# explicitly and the Entra lookup is directory-scoped, so a different active
# subscription is harmless -- but say so, rather than leaving it unexplained.
if [ "$AZ_SUBSCRIPTION" != "$SUBSCRIPTION_ID" ]; then
  echo "  Note: the Azure CLI's active subscription is ${AZ_SUBSCRIPTION},"
  echo "        not the deployment subscription above. That is fine here —"
  echo "        only the directory matters for the identity lookup."
fi

# ─── Resolve the hosted-agent instance identity (the Entra lookup Bicep can't do) ───
# Foundry names the agent's service principal deterministically:
#   <account>-<project>-<agentName>-AgentIdentity
# Matching the "<account>-<project>-" prefix plus the "-AgentIdentity" suffix
# discovers every hosted agent under this project without hard-coding the agent
# name, so the hook keeps working if the template is renamed or grows more agents.
PREFIX="${FOUNDRY_ACCOUNT}-${FOUNDRY_PROJECT}-"
if ! AGENT_PRINCIPAL_IDS="$(az ad sp list --display-name "$PREFIX" \
  --query "[?ends_with(displayName, '-AgentIdentity')].id" -o tsv)"; then
  echo "❌ Could not query the hosted-agent identity in Microsoft Entra ID."
  echo "   The signed-in principal needs permission to read directory objects."
  exit 1
fi

if [ -z "$AGENT_PRINCIPAL_IDS" ]; then
  echo "⚠️  No '*-AgentIdentity' service principal found yet for prefix '${PREFIX}'."
  echo "    The hosted agent identity may still be propagating in Microsoft Entra ID."
  echo "    Re-run 'azd deploy kratos-agent' (or 'azd up') once it appears."
  exit 0
fi

# Build a JSON array of principal IDs for the Bicep `agentPrincipalIds` param.
PRINCIPALS_JSON="["
SEP=""
for PID in $AGENT_PRINCIPAL_IDS; do
  echo "  Discovered agent identity: ${PID}"
  PRINCIPALS_JSON="${PRINCIPALS_JSON}${SEP}\"${PID}\""
  SEP=","
done
PRINCIPALS_JSON="${PRINCIPALS_JSON}]"

# ─── Apply the declarative Bicep role-assignment module ───
echo ""
echo "  Deploying ${ROLE_MODULE} (declarative role assignments)..."
DEPLOY_ERR="$(mktemp)"
trap 'rm -f "$DEPLOY_ERR"' EXIT
if az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$ROLE_MODULE" \
    --parameters \
        agentPrincipalIds="$PRINCIPALS_JSON" \
        cosmosDbAccountName="$COSMOS_NAME" \
        aiServicesName="$FOUNDRY_ACCOUNT" \
        keyVaultName="$KEY_VAULT_NAME" \
        storageAccountName="$STORAGE_ACCOUNT" \
    --only-show-errors >/dev/null 2>"$DEPLOY_ERR"; then
  echo "   ✅ Hosted-agent role assignments applied."
  echo "      Data-plane role propagation can take a few minutes before the"
  echo "      agent's first successful model / Cosmos call."
elif grep -q "RoleAssignmentExists" "$DEPLOY_ERR" && \
     ! grep -qE '"code":\s*"(AuthorizationFailed|InvalidTemplate|InvalidTemplateDeployment|PrincipalNotFound|LinkedAuthorizationFailed)"' "$DEPLOY_ERR"; then
  # ARM fails the whole deployment when a role assignment already exists, even
  # though that is exactly the state we want. Re-running the hook (e.g. on every
  # `azd deploy`) therefore "failed" while being fully converged. Treat an
  # exists-only failure as success so repeat deploys are genuinely idempotent,
  # but still surface any real error such as a missing permission.
  echo "   ✅ Hosted-agent role assignments already in place (nothing to do)."
else
  echo "   ⚠️  Role-assignment deployment failed."
  echo "      Verify the deploying principal has Owner or User Access Administrator."
  echo "      The hosted agent's permissions could not be fully applied or verified;"
  echo "      invocations may fail with HTTP 401 PermissionDenied until this succeeds."
  sed -n '1,20p' "$DEPLOY_ERR" | sed 's/^/      /'
  exit 1
fi
