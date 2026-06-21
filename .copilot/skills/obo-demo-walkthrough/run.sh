#!/usr/bin/env bash
# obo-demo-walkthrough — capture the OBO flow end-to-end and emit a sharable,
# interactive HTML that shows, step by step, exactly what is sent at each hop.
#
# Targets (same proof, same HTML; only the OBO server's self-auth differs):
#   TARGET=cloud  (default) — drive the deployed signed-in frontend over CDP and
#                             pull backend + OBO container logs via `az`.
#   TARGET=local            — POST to the local docker-compose backend with a
#                             provided OBO_USER_TOKEN and pull `docker compose` logs.
#
# Usage:
#   TARGET=cloud ./run.sh                 # uses azd env + a signed-in Edge on :9222
#   TARGET=local OBO_USER_TOKEN=<jwt> ./run.sh
#
# Output: out/report.html (self-contained — open or share it).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
TARGET="${TARGET:-cloud}"

if [[ ! -d node_modules/playwright-core && "$TARGET" == "cloud" ]]; then
  echo "[walkthrough] installing playwright-core (connects to your Edge over CDP, no browser download) …"
  npm install --no-audit --no-fund --silent
fi

# ── resolve endpoints ────────────────────────────────────────────────────────
azdval() { (cd "$(git rev-parse --show-toplevel)" && azd env get-value "$1" 2>/dev/null) || true; }
host_label() { echo "$1" | sed -E 's#https?://([^./]+).*#\1#'; }

if [[ "$TARGET" == "cloud" ]]; then
  BACKEND_URL="${KRATOS_BACKEND_URL:-$(azdval AGENT_SERVICE_URL)}"
  FRONTEND_URL="${KRATOS_FRONTEND_URL:-$(azdval AZURE_STATIC_WEB_APP_URL)}"
  OBO_MCP_URL="${OBO_MCP_URL:-$(azdval OBO_MCP_SERVER_MCP_URL)}"
  PROJECT_EP="$(azdval AZURE_AI_PROJECT_ENDPOINT)"
  RG="${AZURE_RESOURCE_GROUP:-$(azdval AZURE_RESOURCE_GROUP)}"
  CA_BACKEND="$(host_label "$BACKEND_URL")"
  CA_OBO="$(host_label "$OBO_MCP_URL")"
  export KRATOS_FRONTEND_URL="$FRONTEND_URL"
  echo "[walkthrough] target=cloud backend=$CA_BACKEND obo=$CA_OBO rg=$RG"
else
  BACKEND_URL="${KRATOS_BACKEND_URL:-http://localhost:8000}"
  FRONTEND_URL="${KRATOS_FRONTEND_URL:-http://localhost:5173}"
  OBO_MCP_URL="${OBO_MCP_URL:-http://localhost:8800/mcp}"
  PROJECT_EP="http://hosted-agent:8088/invocations (local)"
  echo "[walkthrough] target=local backend=$BACKEND_URL obo=$OBO_MCP_URL"
fi

# ── step 1: capture the request token + answer ───────────────────────────────
if [[ "$TARGET" == "cloud" ]]; then
  node capture.mjs   # writes out/browser-capture.json (uses the signed-in Edge)
else
  [[ -n "${OBO_USER_TOKEN:-}" ]] || { echo "ERROR: TARGET=local needs OBO_USER_TOKEN=<fresh SPA user jwt>"; exit 1; }
  CAPTURE_OUT=out/browser-capture.json BACKEND_URL="$BACKEND_URL" node lib/capture-local.mjs
fi

# ── step 2/3: pull backend kratos_diag + OBO server logs + tool result ───────
pull_logs() {  # $1 = container app name (cloud) | service (local)
  if [[ "$TARGET" == "cloud" ]]; then
    az containerapp logs show -n "$1" -g "$RG" --tail 200 --format text 2>/dev/null || true
  else
    docker compose logs --no-color --tail 300 "$1" 2>/dev/null || true
  fi
}

BACKEND_LOGS="$(pull_logs "${CA_BACKEND:-backend}")"
OBO_LOGS="$(pull_logs "${CA_OBO:-obo-mcp-server}")"

DIAG_LINE="$(printf '%s\n' "$BACKEND_LOGS" | grep -E 'kratos_diag|hosted-agent diag' | tail -1 || true)"
OBO_PROOF="$(printf '%s\n' "$OBO_LOGS" | grep -E 'OnBehalfOfCredential|/v1.0/me|returned profile|get_my_profile' | tail -12 || true)"
TOOL_RESULT_JSON="$(printf '%s\n' "$OBO_LOGS" | grep -F 'get_my_profile result:' | tail -1 | sed -E 's/.*get_my_profile result: //' || true)"

# ── assemble raw.json (merge everything) ─────────────────────────────────────
TARGET="$TARGET" BACKEND_URL="$BACKEND_URL" FRONTEND_URL="$FRONTEND_URL" \
OBO_MCP_URL="$OBO_MCP_URL" PROJECT_EP="$PROJECT_EP" \
DIAG_LINE="$DIAG_LINE" OBO_PROOF="$OBO_PROOF" TOOL_RESULT_JSON="$TOOL_RESULT_JSON" \
node lib/merge-raw.mjs out/browser-capture.json out/raw.json

# ── transform + render ───────────────────────────────────────────────────────
node lib/assemble.mjs out/raw.json out/capture.json
node render.mjs out/capture.json out/report.html

echo ""
echo "[walkthrough] ✅ report: $(pwd)/out/report.html"
echo "[walkthrough]    open it in a browser, or share the single self-contained file."
