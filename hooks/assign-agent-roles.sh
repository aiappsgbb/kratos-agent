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
# relies on for the Bicep role assignments.

set -uo pipefail

ROLE_MODULE="infra/modules/agent-role-assignments.bicep"
DEPLOYMENT_NAME="kratos-agent-role-assignments"

# ─── Context from the azd environment (all values are deployment-specific and
#     resolved at runtime — nothing about a particular tenant is baked in) ───
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-}"
PROJECT_ID="${AZURE_AI_PROJECT_ID:-}"            # .../accounts/<account>/projects/<project>
COSMOS_ENDPOINT="${AZURE_COSMOS_DB_ENDPOINT:-}"  # https://<account>.documents.azure.com:443/
SEARCH_ENDPOINT="${AZURE_AI_SEARCH_ENDPOINT:-}"  # https://<service>.search.windows.net
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
SEARCH_NAME="$(host_of "$SEARCH_ENDPOINT" | cut -d. -f1)"
COSMOS_NAME="$(host_of "$COSMOS_ENDPOINT" | cut -d. -f1)"
KEY_VAULT_NAME="$(host_of "$KEY_VAULT_URI" | cut -d. -f1)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     Assign least-privilege roles to hosted agent(s)      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Foundry account : ${FOUNDRY_ACCOUNT}"
echo "  Foundry project : ${FOUNDRY_PROJECT}"

if [ -z "$FOUNDRY_ACCOUNT" ] || [ -z "$FOUNDRY_PROJECT" ] || [ -z "$COSMOS_NAME" ] \
   || [ -z "$SEARCH_NAME" ] || [ -z "$KEY_VAULT_NAME" ] || [ -z "$STORAGE_ACCOUNT" ]; then
  echo "⚠️  Could not derive all resource names from the azd environment. Skipping."
  exit 0
fi

# ─── Resolve the hosted-agent instance identity (the Entra lookup Bicep can't do) ───
# Foundry names the agent's service principal deterministically:
#   <account>-<project>-<agentName>-AgentIdentity
# Matching the "<account>-<project>-" prefix plus the "-AgentIdentity" suffix
# discovers every hosted agent under this project without hard-coding the agent
# name, so the hook keeps working if the template is renamed or grows more agents.
PREFIX="${FOUNDRY_ACCOUNT}-${FOUNDRY_PROJECT}-"
AGENT_PRINCIPAL_IDS="$(az ad sp list --display-name "$PREFIX" \
  --query "[?ends_with(displayName, '-AgentIdentity')].id" -o tsv 2>/dev/null || true)"

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
if az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$ROLE_MODULE" \
    --parameters \
        agentPrincipalIds="$PRINCIPALS_JSON" \
        cosmosDbAccountName="$COSMOS_NAME" \
        aiSearchName="$SEARCH_NAME" \
        aiServicesName="$FOUNDRY_ACCOUNT" \
        keyVaultName="$KEY_VAULT_NAME" \
        storageAccountName="$STORAGE_ACCOUNT" \
    --only-show-errors >/dev/null; then
  echo "   ✅ Hosted-agent role assignments applied."
  echo "      Data-plane role propagation can take a few minutes before the"
  echo "      agent's first successful model / Cosmos / Search call."
else
  echo "   ⚠️  Role-assignment deployment failed."
  echo "      Verify the deploying principal has Owner or User Access Administrator."
  exit 0
fi
