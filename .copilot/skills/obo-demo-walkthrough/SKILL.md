# obo-demo-walkthrough — show, step by step, what happens under the hood

A repo-local skill that captures the **On-Behalf-Of (OBO)** agent flow against a
running environment and renders a **single, self-contained, interactive HTML**
that walks through *exactly what is sent at each hop* — from the browser's
delegated token to the live Microsoft Graph `/me` call performed **as the
signed-in user**.

It is the "explain + prove" companion to the `obo-identity-proof` skill (which
*asserts* the binding in CI). This one *narrates* it for demos and reviews.

## What it produces

`out/report.html` — open it or share the file. It contains:

1. **A numbered ①–⑤ flow diagram** at the top that maps 1:1 to the detail steps
   below — click a node (or use **Prev / Next**) to jump to that step. Manual
   step-through (no auto-play), so each hop is readable at a demo pace.
2. **The 5 hops**, including the **LLM tool-call round-trip**:
   1. You → Backend: `POST /api/agent/chat` with the user token in the body
      under `mcpAccessTokens` (token redacted in the report).
   2. Backend → **Foundry Invocations endpoint** (directly on the AI Services
      resource — **no APIM** in this path).
   3. **Agent ↔ LLM** — the model is sent your question + the available tools and
      replies with a tool call (`graph-obo-get_my_profile`). Shown as request +
      response in the OpenAI chat-completions shape (assembled from the real
      prompt, tool schema and tool call).
   4. **Agent → OBO MCP → Graph** — token injected as the server's header
      (keys-only `kratos_diag`), On-Behalf-Of exchange (real server logs), and the
      live `/me` tool result.
   5. **Agent ↔ LLM → You** — the tool result goes back to the model, which
      streams the final answer.
3. **Proof panel** — persona-first:
   - **This is really you** — your live directory profile (`jobTitle`,
     `department`, `officeLocation`, `preferredLanguage`, `givenName`, `surname`)
     plus your live **profile photo**. These can never appear in an access token
     (job/dept/office aren't even on the optional-claims list), so they prove a
     live delegated Graph read. A `null` field is shown as genuinely empty, not
     an error.
   - **What the login token contains:** `aud`, `scp`, `oid`, `name`,
     `preferred_username` — identity only.
   - **Technical proof of a live call:** `graphRequestId` (a correlation id
     *Graph* stamped on this response) + `fetchedAtUtc`.
   - **oid binding:** `token.oid == graph./me.id` (dispositive — Graph `/me` only
     resolves in a delegated user context).

> Why the persona fields matter: the original demo reported `displayName` /
> `userPrincipalName` / `oid`, which all live **in the token** — a skeptic could
> claim the model just decoded the JWT. Job title / department / office (and the
> photo) close that loophole in a way anyone can grasp at a glance.

## Architecture note (important, and a correction)

**APIM is not in the agent path.** Agent invocations go straight to the Foundry
project endpoint (`…cognitiveservices.azure.com/api/projects/…/agents/
kratos-agent/…/invocations`). The "gateway" in the code/logs is **Foundry's own
Invocations gateway** (warm-pool / session manager), *not* APIM. The APIM
AI-gateway (`oai-…-gateway.azure-api.net`) is an optional **LLM** governance
layer; in this deployment `FOUNDRY_ENDPOINT` targets the AI Services resource
directly, so APIM is provisioned but **bypassed**. The report says so explicitly.

## Run it

### Cloud (deployed) — authentic full-stack capture
Needs a signed-in Edge reachable over CDP (so MSAL/MFA is interactive) and `az`
logged in to the subscription.

```bash
cd .copilot/skills/obo-demo-walkthrough
# Edge must be started with --remote-debugging-port=9222 and signed in to the app
TARGET=cloud ./run.sh
open out/report.html      # macOS (or just share the file)
```

`run.sh` reads endpoints from the azd environment (`AGENT_SERVICE_URL`,
`AZURE_STATIC_WEB_APP_URL`, `OBO_MCP_SERVER_MCP_URL`, `AZURE_AI_PROJECT_ENDPOINT`),
drives the real frontend to capture the token + answer, then pulls `kratos_diag`
from the backend Container App and the OBO exchange + Graph `/me` lines (and the
full tool result) from the OBO Container App.

### Local (docker compose) — same flow, same HTML
Real Entra is used locally too; only the OBO server's **self-auth** differs
(client secret instead of the cloud's managed-identity federated credential).

```bash
# 1. one-time: a dev client secret on the OBO server app registration
az ad app credential reset --id <OBO_SERVER_APP_CLIENT_ID> --display-name local-dev --years 1
#    put the value (and COPILOT_GITHUB_TOKEN) in the repo-root .env (see .env.sample)

# 2. bring up the stack (now includes obo-mcp-server + OBO env on the hosted agent)
docker compose up --build -d

# 3. capture + render (needs a fresh SPA user token, aud=api://<obo-server>)
cd .copilot/skills/obo-demo-walkthrough
TARGET=local OBO_USER_TOKEN=<jwt> ./run.sh
```

Acquire `OBO_USER_TOKEN` from the signed-in frontend (DevTools → the
`mcpAccessTokens` value on a `/api/agent/chat` request), or from the deployed
site — the token's audience is the OBO server app, so it validates regardless of
where the OBO server runs.

## Inputs (env)

| Var | Target | Purpose |
|-----|--------|---------|
| `TARGET` | both | `cloud` (default) or `local`. |
| `KRATOS_FRONTEND_URL` | cloud | Deployed SWA URL (default from `AZURE_STATIC_WEB_APP_URL`). |
| `KRATOS_BACKEND_URL` | both | Backend URL (default from `AGENT_SERVICE_URL`; `http://localhost:8000` local). |
| `OBO_MCP_URL` | both | OBO MCP `/mcp` URL (default from `OBO_MCP_SERVER_MCP_URL`). |
| `OBO_CDP_URL` | cloud | CDP endpoint of the signed-in Edge. Default `http://localhost:9222`. |
| `OBO_USER_TOKEN` | local | Fresh SPA user token for the local POST capture. |
| `AZURE_RESOURCE_GROUP` | cloud | RG for `az containerapp logs` (default from azd env). |
| `DEMO_PROMPT` | both | Override the demo prompt. |
| `CHAT_TIMEOUT_MS` | both | Per round-trip ceiling. Default `150000`. |

## Files

| File | Role |
|------|------|
| `run.sh` | Orchestrator: resolve endpoints → capture → pull logs → assemble → render. |
| `capture.mjs` | Cloud capture over CDP (token the **frontend** attaches + rendered answer). |
| `lib/capture-local.mjs` | Local capture: POST to the compose backend with `OBO_USER_TOKEN`. |
| `lib/merge-raw.mjs` | Merge capture + `kratos_diag` + OBO logs + tool result → `out/raw.json`. |
| `lib/assemble.mjs` | Build the walkthrough dataset (5 hops, proof contrast, notes). |
| `render.mjs` | Inject the dataset into `report-template.html` → `out/report.html`. |
| `report-template.html` | Self-contained, Clawpilot-themed interactive report. |
| `sample-report.html` | A committed example render (real cloud capture, token redacted). |

## Notes & limitations

- The user token is **redacted** in the report (`header.payload.signature` length
  only) — it is never embedded. Only decoded, non-secret claims are shown.
- Cloud capture relies on the operator's Edge being signed in; the script clicks
  the OBO sign-in button if present and waits up to 120s for a signed-in state.
- Hosted-agent logs do not reach Log Analytics; the backend `kratos_diag` SSE
  (logged in the backend Container App) is the window into token receipt.
- If `az`/`docker compose` logs are unavailable, the report still renders — the
  affected hop shows the captured/derived data it has.
