# AGENTS.md — working agreements for AI agents in this repo

## ⚠️ This repository is PUBLIC

`aiappsgbb/kratos-agent` is a public GitHub repository. Anything committed is
world-readable, permanently, including in git history after a later "fix".

**Never commit into this repo:**

- Deployment endpoints — Static Web App / Container Apps / Foundry / Search /
  Cosmos / Key Vault hostnames, or anything else from `azd env get-values`.
  Resolve these at runtime from the `azd` environment (`.azure/`, gitignored)
  or from env vars; fail fast when they're absent rather than falling back to
  a hardcoded default.
- Subscription IDs, tenant IDs, resource group names, object/principal IDs,
  client IDs, instrumentation keys or App Insights connection strings.
- Keys, tokens, connection strings, or `.env` files of any kind.
- Customer names or customer data, real personal data, or internal-only
  material. Use-case fixtures must stay synthetic.
- Playwright / test artifacts (screenshots, videos, traces, HAR). These can
  capture live application data. They are gitignored — keep it that way.

Infra templates under `infra/` are the exception: they legitimately define
resources, but keep them parameterised — no baked-in environment values.

Before committing, sanity-check the diff:

```bash
git diff --cached | grep -nEi \
  'azurestaticapps\.net|azurecontainerapps\.io|azure-api\.net|cognitiveservices\.azure\.com|search\.windows\.net|vault\.azure\.net|documents\.azure\.com|InstrumentationKey|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
```

Treat any hit as blocking until justified. If something sensitive does land on
`main`, rotate/decommission the resource first — history rewrites on a public
repo are disruptive and the data is already exposed.

## Layout

| Path | What it is |
|------|-----------|
| `src/backend` | Python agent service (FastAPI), deployed as Container App `agent-service` |
| `src/frontend` | Next.js UI, deployed to Azure Static Web Apps |
| `src/hosted-agent` | Foundry hosted-agent variant |
| `src/obo-mcp-server` | On-behalf-of MCP server (optional, `DEPLOY_OBO` flag) |
| `use-cases/` | Persona definitions, skills and synthetic assets |
| `infra/` | Bicep templates |
| `.copilot/skills/` | Repo-local agent skills, incl. `e2e-smoke` |

## Personas: curated vs. non-curated

`/api/use-cases` returns every persona, but the frontend selector only shows
those with `curated: true`. Non-curated personas exist in the API and are
deliberately hidden in the UI, and may have no eval scenarios generated.

Don't hardcode persona lists in tests or tooling — discover them from
`/api/use-cases` and filter on `curated`. A test demanding a non-curated
persona in the UI is a broken test, not a broken app.

## Validation

Run the smallest thing that covers the change.

```bash
# backend
cd src/backend && uv run pytest && uv run ruff check .

# frontend
cd src/frontend && npm run lint && npm run build

# deployed environment, end to end (after any azd deploy)
cd .copilot/skills/e2e-smoke && ./run.sh          # 21 specs
SKIP_BROWSER=1 ./run.sh                           # API-only, no chromium
```

`e2e-smoke/run.sh` resolves its target from the selected `azd` environment,
so it always follows whichever env is active. See its `SKILL.md` for details.
First run installs npm deps and Chromium (cached afterwards).

## Deployment is manual, never automatic

`.github/workflows/ci-cd.yml` runs lint/test/build only. It does **not** deploy.
Deployment lives in `.github/workflows/deploy.yml` and is `workflow_dispatch`
only — pick an environment, optionally provision, optionally upload skills.

Do not re-attach deploy jobs to `push`. A green build does not mean a deploy
can succeed, because the target environment needs all of:

- environment secrets `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` /
  `AZURE_SUBSCRIPTION_ID` (OIDC federated credential), and
- already-provisioned infrastructure for that `azd` env.

As of the last audit `kratos-agent-2` (prod) and `kratos-agent-exp`
(experimentation) are provisioned locally; the `staging` and `production`
GitHub envs have no infra and no secrets.

Gotchas that have bitten before:

- `Azure/setup-azd@v1.0.0` installs from `azdrelease.azureedge.net`, which no
  longer resolves. Use `v2.x`.
- A fresh runner has no `.azure/` dir, so `azd deploy` needs `azd env
  select`/`new` **and** `azd env refresh` to hydrate outputs first.
- The skills blob storage account is `publicNetworkAccess: Disabled`, and a
  subscription policy re-applies that setting within seconds if you flip it —
  `az storage account update --public-network-access Enabled` reports success
  and then silently reverts. So the skills upload cannot run from *any* host
  outside the VNet: not a GitHub-hosted runner, and not a developer laptop.
  `hooks/postdeploy.sh` skips the upload when nothing asked for it, and fails
  with `AuthorizationFailure` / "request may be blocked by network rules" when
  something did. That error is a *network* denial, not a missing role — check
  the private endpoint before touching RBAC.
  `blob-storage.bicep` creates the blob private endpoint and the
  `privatelink.blob.*` DNS zone, so anything inside the VNet can reach it. To
  seed a fresh environment's skills, run the upload from a container app:

  ```bash
  # `script` supplies the PTY that `containerapp exec` requires
  script -q /dev/null az containerapp exec -g <rg> -n <agent-app> \
    --revision <running-revision> --command python
  ```

  Target the *running* revision explicitly — `azd provision` leaves a second,
  briefly-activating revision behind, and exec against it fails with an opaque
  `ClusterExecFailure ... code: 500`.
- Hooks must not prompt mid-run. `azd` repaints its progress table over hook
  output, which silently ate the skills menu and its prompt. Questions belong
  in `hooks/select-use-cases.sh` at preprovision, before that table starts;
  `hooks/postdeploy.sh` reads the answer and never prompts.
  Two mechanisms enforce that, so don't drop either: `azure.yaml` passes
  `--from-deploy`, which disables prompting in the script outright, and the
  `postdeploy` hook is deliberately **not** `interactive`, so azd hands it no
  terminal to read from. Run `./hooks/postdeploy.sh` by hand (no flag) and the
  menu comes back.
- Never use `|| true` on a test that is meant to gate a release.
- Every hook needs **both** a `posix:` and a `windows:` variant. azd resolves
  `sh` from PATH, and a default Git for Windows install puts only `Git\cmd`
  there (git.exe) — `sh.exe` lives in `Git\usr\bin`, which is not on PATH. A
  hook with only `shell: sh` therefore fails outright on Windows, and every
  hook was in that state until the `.ps1` ports landed. Adding a hook, or
  changing one, means changing both branches. Verify with
  `azd hooks run <name> --platform windows` and `--platform posix` — no deploy
  needed. Note that when both branches are present, azd forbids `run`, `shell`,
  `kind`, `dir`, `interactive`, `continueOnError`, `secrets` and `config` at the
  parent level.
  The `hooks-lint` job in `ci.yml` (`.github/scripts/check-hooks.py`) enforces
  the static half of this: both variants present, a `.ps1` for every `.sh`,
  every `.sh` committed executable, `shellcheck` clean, and every `.ps1` and
  inline `windows:` block parseable. It cannot tell you the two branches
  *behave* the same — that still needs the `azd hooks run` check above.
- `*.sh` must stay LF. `.gitattributes` pins this because a Windows clone with
  the default `core.autocrlf=true` otherwise checks the hooks out as CRLF,
  which breaks them before they run (`#!/usr/bin/env bash\r` → `bash\r: No such
  file or directory`). Don't remove those rules, and don't commit a `.sh` with
  CRLF.
- The Windows `preprovision` hook never prompts. The POSIX one drives its menu
  through `/dev/tty`, which Windows has not got, and a hook blocking on stdin
  while azd owns the console hangs the deploy with no way to answer. Windows
  records `none` and defers to `KRATOS_UPLOAD_USE_CASES`.
- Entra directory operations are not Azure RBAC. Granting admin consent
  (`oauth2PermissionGrants` with `AllPrincipals`) needs a directory role —
  Global Administrator, Privileged Role Administrator, or Cloud Application
  Administrator — which subscription Owner does **not** confer. It lived in
  `infra/modules/obo-entra-app.bicep` and failed the whole provision with a bare
  `Authorization_RequestDenied` for anyone whose tenant admin-gates consent.
  Bicep cannot continue past a forbidden resource, so it now lives in
  `hooks/grant-obo-consent.sh` (postprovision, best-effort). Keep privileged
  directory writes out of Bicep for this reason — the app registration may still
  *request* permissions declaratively, which needs no special rights.

## Container images build in ACR, not locally

All three container services set `remoteBuild: true` under `docker:` in
`azure.yaml`. Their images install from pypi and the npm registry at build
time, and some corporate networks filter `files.pythonhosted.org` and
`registry.npmjs.org`, which makes a local `docker build` impossible. Building
in ACR sidesteps that and means deploying needs no local Docker daemon.

Do not "simplify" this back to local builds.

## Optional services need a `condition:`

`obo-mcp-server` is only provisioned when `deployObo` is true, so `azure.yaml`
gives it `condition: ${DEPLOY_OBO=true}` — the same variable and the same
default that `infra/main.parameters.json` feeds to Bicep. Keep those two in
sync. Without the condition, `azd up` fails on any environment with OBO off,
because azd tries to deploy a resource that was deliberately never created.

`condition:` needs azd >= 1.28.

## CI builds every image

`ci-cd.yml` builds all three Dockerfiles. This is deliberate: it used to build
only the backend, which let a dependency bump reach `main` with an
unresolvable `requirements.txt` (`pydantic` pins `pydantic-core` to an exact
version; they were bumped separately). Nothing caught it until a real deploy
failed.

Packages that pin each other exactly — `pydantic`/`pydantic-core`,
`react`/`react-dom` — must be grouped in `.github/dependabot.yml` so they are
never bumped apart. Both pairs have already broken this repo once.

## Conventions

- Python: `ruff` for lint and format; `mypy` is configured.
- Don't hand-edit `azd`-generated values or anything under `.azure/`.
- Prefer `azd env get-values` over reading `.azure/` files directly.
