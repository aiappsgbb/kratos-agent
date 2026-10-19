#!/usr/bin/env bash
# kratos-agent e2e-smoke runner.
#
# Installs deps + chromium on first run (cached afterwards), resolves the target
# endpoints, then executes the Playwright suite. Extra args go to `playwright test`.
#
# Endpoints are NEVER hardcoded in this repo (it is public). They are resolved as:
#   1. KRATOS_FRONTEND_URL / KRATOS_BACKEND_URL if already exported, else
#   2. the local azd environment via `azd env get-values` (.azure/, gitignored).
#
# Usage:
#   ./run.sh                       # all specs against the current azd env
#   ./run.sh --grep "chat"         # filter to chat spec
#   SKIP_BROWSER=1 ./run.sh        # API-only mode (no chromium)
#   KRATOS_BACKEND_URL=https://...  KRATOS_FRONTEND_URL=https://... ./run.sh
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(git -C . rev-parse --show-toplevel)"

# --- resolve endpoints from azd when not already provided -------------------
if [[ -z "${KRATOS_FRONTEND_URL:-}" || -z "${KRATOS_BACKEND_URL:-}" ]]; then
  if command -v azd >/dev/null 2>&1; then
    echo "[e2e-smoke] resolving endpoints from azd environment …"
    AZD_VALUES="$(cd "$REPO_ROOT" && azd env get-values 2>/dev/null || true)"
    azd_value() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" <<<"$AZD_VALUES" | head -1; }
    # AZURE_WEB_APP_URL is the web Container App; environments provisioned
    # before it replaced the Static Web App only have the old output.
    : "${KRATOS_FRONTEND_URL:=$(azd_value AZURE_WEB_APP_URL)}"
    : "${KRATOS_FRONTEND_URL:=$(azd_value AZURE_STATIC_WEB_APP_URL)}"
    : "${KRATOS_BACKEND_URL:=$(azd_value AGENT_SERVICE_URL)}"
    export KRATOS_FRONTEND_URL KRATOS_BACKEND_URL
  fi
fi

if [[ -z "${KRATOS_FRONTEND_URL:-}" || -z "${KRATOS_BACKEND_URL:-}" ]]; then
  echo "[e2e-smoke] ERROR: could not resolve target endpoints." >&2
  echo "  Provision/select an azd environment (azd env select <name>), or export" >&2
  echo "  KRATOS_FRONTEND_URL and KRATOS_BACKEND_URL manually." >&2
  exit 1
fi

if [[ ! -d node_modules/@playwright/test ]]; then
  echo "[e2e-smoke] installing npm dependencies …"
  npm install --no-audit --no-fund --silent
fi

if [[ -z "${SKIP_BROWSER:-}" ]]; then
  PW_BIN="./node_modules/.bin/playwright"
  if ! "$PW_BIN" install --dry-run chromium >/dev/null 2>&1; then
    echo "[e2e-smoke] installing chromium for Playwright …"
    "$PW_BIN" install chromium
  fi
fi

# --- default the use-case list to the deployment's curated personas ---------
# These are the only personas the frontend selector exposes, so they are the
# correct target for the UX specs. Discovered at runtime, never hardcoded.
if [[ -z "${KRATOS_USE_CASES:-}" ]]; then
  CURATED="$(curl -fsS "${KRATOS_BACKEND_URL%/}/api/use-cases" 2>/dev/null \
    | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{
        const u=JSON.parse(s).useCases||[];
        const c=u.filter(x=>x.curated===true).map(x=>x.name);
        process.stdout.write((c.length?c:u.map(x=>x.name)).join(","));
      }catch{}})' || true)"
  if [[ -n "$CURATED" ]]; then
    export KRATOS_USE_CASES="$CURATED"
  fi
fi

echo "[e2e-smoke] frontend  = ${KRATOS_FRONTEND_URL}"
echo "[e2e-smoke] backend   = ${KRATOS_BACKEND_URL}"
echo "[e2e-smoke] use-cases = ${KRATOS_USE_CASES:-generic (fallback)}"
echo "[e2e-smoke] skip-browser = ${SKIP_BROWSER:-0}"

exec ./node_modules/.bin/playwright test "$@"
