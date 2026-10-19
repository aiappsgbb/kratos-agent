# e2e-smoke — Playwright-driven live smoke tests for kratos-agent

A repo-local Playwright skill that exercises a deployed kratos-agent
environment end-to-end: frontend renders, backend /health, scenarios
load per use-case, chat round-trips, evals API, and traces API.

## When to use

- After every `azd deploy backend` / `azd deploy hosted-agent` / `azd deploy web`
  to confirm the deployment is healthy from a real client.
- Before opening a PR that touches `src/backend`, `src/frontend`, `src/hosted-agent`,
  or the eval / traces surface.
- After granting / changing Foundry RBAC, to confirm the hosted agent and the
  agent-service can still talk to the model.
- In CI as the post-deploy gate (recommended).

## When NOT to use

- Local-only frontend dev work — `next dev` + targeted manual click is faster.
- Pure backend unit changes — prefer `uv run pytest` in `src/backend`.
- Static type / lint checks — those have their own runners.

## What it tests

| Spec | Surface | Asserts |
|------|---------|---------|
| `01-health.spec.ts` | API + SWA | `/health` 200, frontend HTML serves, runtime `config.json` points at expected backend |
| `02-scenarios.spec.ts` | `/api/use-cases/{uc}/evals/scenarios` | Every use-case returns ≥1 scenario; required shape (`name`, `prompt`, `expected_signal_keywords`) |
| `03-chat.spec.ts` | `/api/agent/chat` SSE | Sends a tiny prompt, asserts a non-empty assistant response inside `CHAT_TIMEOUT_MS` |
| `04-evals.spec.ts` | `/api/use-cases/{uc}/evals/runs` | At least one completed validation run exists; per-run detail returns scenarios array |
| `05-traces.spec.ts` | `/api/traces/operations` | ≥1 operation in lookback window; per-operation detail returns spans |
| `06-ui.spec.ts` | browser | Frontend loads without console errors (smoke gate) |
| `07-regression.spec.ts` | pre-existing core | `/api/use-cases` schema + all curated use-cases present, `/api/settings` Foundry config, conversation CRUD round-trip, `/api/admin/skills` catalogue + detail, `/api/admin/system-prompt` content. Guards against regressions in surfaces the evals/tracing branch did NOT touch |
| `08-ux.spec.ts` | browser, interactive | **The UX itself.** Persona selector lists the curated use-cases & switches value; landing textarea + Send button starts a chat and the assistant responds; Skills admin opens; every admin tab (Skills / System Prompt / APM / Evals / Traces) renders its header; "Generate Scenarios" modal opens + closes; Traces "Refresh" renders ops/summary/empty-state |

## Inputs (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `KRATOS_FRONTEND_URL` | from `azd env` → `AZURE_WEB_APP_URL` (falls back to `AZURE_STATIC_WEB_APP_URL`) | web Container App URL |
| `KRATOS_BACKEND_URL` | from `azd env` → `AGENT_SERVICE_URL` | Container Apps URL |
| `KRATOS_USE_CASES` | curated personas discovered from `/api/use-cases` | Comma-separated |
| `CHAT_TIMEOUT_MS` | `60000` | Chat round-trip ceiling |
| `TRACES_LOOKBACK_HOURS` | `6` | App Insights query window |
| `SKIP_BROWSER` | unset | Set to `1` to skip browser tests (CI / no-chromium hosts) |

**No deployment endpoints are hardcoded in this repo — it is public.** `run.sh`
resolves the target from the local `azd` environment (`.azure/`, gitignored), so
the suite always follows whichever env is currently selected. Export
`KRATOS_FRONTEND_URL` / `KRATOS_BACKEND_URL` to override, e.g. in CI. If neither
source provides them, the run fails fast instead of silently hitting a stale env.

`KRATOS_USE_CASES` defaults to the deployment's **curated** personas (those with
`curated: true`), because the frontend persona selector only exposes those —
non-curated use-cases exist in the API but are intentionally hidden in the UI.

## Run it

```bash
cd .copilot/skills/e2e-smoke
./run.sh                                  # install (first run) + run all specs
./run.sh --grep "chat"                    # filter
KRATOS_BACKEND_URL=... ./run.sh           # override the azd-resolved target
SKIP_BROWSER=1 ./run.sh                   # API-only mode
```

The wrapper installs `npm` deps + Chromium on first run only (cached in
`node_modules/` + the playwright user dir). Results land in
`playwright-report/` and `test-results/` — both gitignored.

## Conventions

- TypeScript Playwright with `@playwright/test`.
- One spec = one concern; specs are independent (no shared fixture state) so
  Playwright's `fullyParallel: true` works.
- Assertions are content-aware: `/health` checks the actual JSON shape, not
  just status code. Chat assertion requires non-empty body, not just 200.
- Browser tests are gated on `SKIP_BROWSER` for CI on hosts without Chromium.
- Auth is assumed off (`admin_auth_enabled=false` on the deployment); add
  Easy Auth bearer logic here when that changes.

## Known limitations

- Foundry agent cold-start can spike `/api/agent/chat` above 60s on the
  very first call after 15 min idle. The spec already retries once with
  a 30 s warmup ping; bump `CHAT_TIMEOUT_MS` if your environment is colder.
- Traces lookback default is 2h to match the typical pilot session; the
  test gracefully skips assertions if zero operations exist in that
  window (so it doesn't false-fail before any real chat has happened).
