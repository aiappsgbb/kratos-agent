# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read AGENTS.md first

[AGENTS.md](AGENTS.md) holds the binding working agreements: **this repo is public** (never commit
endpoints, subscription/tenant/object IDs, keys, customer data, or Playwright artifacts), plus
hard-won deployment gotchas. It is not duplicated here — read it before committing or deploying.

## Commands

```bash
# Backend (Python 3.11, uv)
cd src/backend
uv run pytest                          # all tests
uv run pytest tests/test_skill_registry.py::test_name -v   # a single test
uv run ruff check . && uv run ruff format --check .
uv run mypy app/ --ignore-missing-imports

# Frontend (Next.js 15, static export)
cd src/frontend
npm run lint && npm run build          # `build` == `export`; output lands in out/
npm run dev                            # localhost:3000

# Mocks (TypeScript stdio MCP servers)
cd mocks && npm install && npm run build

# Full local stack — no Azure needed (SQLite + Azurite + a Copilot token)
cp .env.local.example .env.local       # set COPILOT_GITHUB_TOKEN=ghu_...
./run-local.sh                         # or .\run-local.ps1

# Deployed environment, end to end (after any azd deploy) — 21 specs, ~55s
cd .copilot/skills/e2e-smoke && ./run.sh
SKIP_BROWSER=1 ./run.sh                # API-only, skips the Chromium download

# Evals / traces CLI
python scripts/run_evals.py --use-case insurance --mode validation   # or --mode foundry
python scripts/generate_evals.py --use-case insurance --count 5 --save
python scripts/fetch_traces.py --conversation-id abc123
```

`azd` commands follow the **globally selected** environment. Confirm with
`azd env get-value AZURE_ENV_NAME`, or name the target per command (`azd deploy -e <env>`)
before deploying or destroying anything.

## Architecture

### Dual compute: the backend is a proxy, the agent runs in Foundry

Two runtimes share the same engine code (`CopilotClient` + `SkillRegistry` + `CosmosService`):

| Layer | Entry point | Runtime |
|---|---|---|
| **Hosted agent** | [src/hosted-agent/main.py](src/hosted-agent/main.py) — `InvocationAgentServerHost`, port 8088 | Microsoft Foundry, auto-provisioned sandboxes |
| **Backend proxy** | [src/backend/app/main.py](src/backend/app/main.py) — FastAPI, port 8000 | Azure Container Apps |

Chat does **not** execute in the backend. `POST /api/agent/chat` forwards to the Foundry hosted
agent through the Invocations REST API ([foundry_agent_proxy.py](src/backend/app/services/foundry_agent_proxy.py))
and streams SSE events back. The backend owns conversation persistence, file serving, skills/APM
admin, evals and traces. When changing agent *behaviour*, the code usually lives in
[copilot_agent.py](src/backend/app/services/copilot_agent.py) and runs in the hosted agent —
so it needs `azd deploy kratos-agent`, not a backend deploy, to take effect.

**Session pinning:** Foundry returns `x-agent-session-id` on first invocation; the backend stores
the mapping in Cosmos (`sessions`, partitioned by `conversationId`) and appends
`?agent_session_id=<id>` to later turns so multi-turn state survives. The backend also keeps a
warm pool of unclaimed sandboxes (`keep_warm_enabled`, `warm_pool_size` in
[config.py](src/backend/app/config.py)).

Foundry reserves all `FOUNDRY_*` env vars, so `hosted-agent/main.py` remaps injected platform
names (`MODEL_DEPLOYMENT_NAME`, `FOUNDRY_PROJECT_ENDPOINT`) onto the `Settings` names at import
time. Adding a Foundry-facing setting means touching that remap block **and** `azure.yaml`'s
`kratos-agent.config.env`.

### One agent, N personas

A "use case" is a persona directory under [use-cases/](use-cases/): `SYSTEM_PROMPT.md`,
`skills/*/SKILL.md`, `.mcp.json`, `apm.yml`, `evals/`. There is no multi-agent orchestration —
one agent swaps skills and prompt per conversation, selected by the `useCase` request field.

Skills load in priority order (see [skill_registry.py](src/backend/app/services/skill_registry.py)):
blob storage → local filesystem → APM packages, with local/blob winning name conflicts. New skills
go live via `POST /api/admin/skills?use_case=...` with **no redeploy**.

Personas are marked `curated: true/false`. `/api/use-cases` returns all of them; the UI only shows
curated ones. Discover personas from the API and filter on `curated` — never hardcode the list.

### Local mode

`LOCAL_MODE` auto-activates whenever `COSMOS_DB_ENDPOINT` is empty (`Settings.is_local_mode()`).
SQLite replaces Cosmos, Azurite replaces Blob, and a GitHub Copilot token replaces
Foundry/Managed Identity. Same code path in both worlds — don't branch on environment beyond
the existing `is_local_mode()` checks.

### Mocks

[mocks/packages/](mocks/packages/) holds in-repo stdio MCP servers (Salesforce, Workday,
ServiceNow, core banking, Epic FHIR, SAP, M365 Graph, Azure IoT) that back the demo personas
with **synthetic** fixtures. Both backend Dockerfiles `npm install -g ./mocks/packages/*` so the
binaries land on PATH; a persona opts in via its `.mcp.json`.

### Export

`GET /api/use-cases/{uc}/export` packages a persona as a standalone, deployable Foundry hosted
agent ZIP. The templates live in [src/backend/app/exporter_templates/](src/backend/app/exporter_templates/)
and ship inside the wheel via `package-data` — they are `.template` files excluded from ruff, so
changes there need [test_project_exporter.py](src/backend/tests/test_project_exporter.py) to pass,
not lint.

## Conventions

- **API JSON is camelCase** (Pydantic alias generator): `{message, useCase, conversationId}`.
  The exception is the on-disk eval scenario format, which is snake_case
  (`input_message`, `expected_behavior`, `expected_tool_calls`) so it stays readable in git.
- Python: `ruff` (lint + format, line length 120) and `mypy` are both gating in CI. Per-module
  mypy relaxations are documented in `pyproject.toml` — extend that list rather than sprinkling
  `# type: ignore`.
- Container images build in ACR (`remoteBuild: true`), never locally. Don't "simplify" this back.
- Every azd hook carries both a `posix:` and a `windows:` variant (`hooks/*.sh` + `hooks/*.ps1`),
  and `*.sh` is pinned to LF in `.gitattributes`. Both are load-bearing on Windows — see the
  hook rules in [AGENTS.md](AGENTS.md). Test either side with
  `azd hooks run <name> --platform windows|posix`.
- Optional services need a `condition:` in `azure.yaml` kept in sync with
  `infra/main.parameters.json` (see `obo-mcp-server` / `DEPLOY_OBO`).
- Packages that pin each other exactly (`pydantic`/`pydantic-core`, `react`/`react-dom`) must stay
  grouped in `.github/dependabot.yml`.
- Don't hand-edit anything under `.azure/`; prefer `azd env get-values` over reading those files.
