# Post-azd setup and verification

Use this after `azd up` to finish the manual setup and prove the deployed app is working. Do not paste deployment endpoints, subscription IDs, tenant IDs, resource group names, connection strings, tokens, screenshots, traces, or Playwright artifacts into git.

## 1. Confirm the selected environment

```bash
azd env get-value AZURE_ENV_NAME
azd env get-values | grep -E '^(AZURE_STATIC_WEB_APP_URL|AGENT_SERVICE_URL|AZURE_AI_PROJECT_ID)='
git check-ignore -v .azure .env.local .copilot/skills/e2e-smoke/playwright-report .copilot/skills/e2e-smoke/test-results
```

`AZURE_STATIC_WEB_APP_URL` is the frontend. `AGENT_SERVICE_URL` is the backend Container App. The e2e runner reads both from the active `azd` environment unless `KRATOS_FRONTEND_URL` or `KRATOS_BACKEND_URL` is explicitly exported.

## 2. Register the custom agent in Foundry

1. Open Microsoft Foundry.
2. Select the deployed project.
3. Go to **Operate** > **Agents**.
4. Choose **+ Register agent** and **Custom Agent**.
5. Set the name to `kratos-agent`.
6. Set the endpoint to the value of `AGENT_SERVICE_URL`.
7. Set the API path to `kratos-agent`.

This registration makes the custom agent visible in the Foundry Operate experience. Application Insights ingestion is configured by infrastructure separately.

## 3. Confirm deployed API surfaces

```bash
BACKEND="$(azd env get-value AGENT_SERVICE_URL)"

curl -fsS "$BACKEND/health" | jq '{status}'
curl -fsS "$BACKEND/api/use-cases" | jq '{total:(.useCases|length), curated:[.useCases[]|select(.curated==true)|.name]}'
curl -fsS "$BACKEND/api/admin/skills?use_case=generic" | jq '{count:(.skills|length), sample:[.skills[:5][]|{name,enabled,source}]}'
```

The curated personas are the frontend picker target. Non-curated personas may still exist in the API.

## 4. Seed an eval run before the smoke suite

The smoke suite expects at least one eval run across curated personas. A fresh environment can have zero.

```bash
BACKEND="$(azd env get-value AGENT_SERVICE_URL)"

for uc in generic insurance retail-banking wealth-management; do
  curl -fsS "$BACKEND/api/use-cases/$uc/evals/runs" | jq --arg uc "$uc" '{useCase:$uc,count:(.runs|length)}'
done

cd src/backend
BACKEND_URL="$BACKEND" uv run python ../../scripts/run_evals.py --use-case generic --mode validation
```

Then recheck:

```bash
curl -fsS "$BACKEND/api/use-cases/generic/evals/runs" | jq '.runs[0] | {run_id,status,mode}'
```

The run detail endpoint must return a `run_id`. If the run status is `failed`, the eval prerequisite is present but agent health is not proven.

## 5. Verify chat and skill execution

Run a normal chat first:

```bash
BACKEND="$(azd env get-value AGENT_SERVICE_URL)"

curl -N -sS "$BACKEND/api/agent/chat" \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"message":"Reply with one short sentence confirming you are online.","useCase":"generic","conversationId":"manual-chat-check"}'
```

Then use a scenario that expects a tool:

```bash
curl -fsS "$BACKEND/api/use-cases/generic/evals/scenarios" \
  | jq -r '.scenarios[] | select((.expected_tool_calls // []) | length > 0) | [.name, .input_message, (.expected_tool_calls|join(","))] | @tsv' \
  | head -1
```

Send that `input_message` through `/api/agent/chat`. The stream must contain at least one `event: tool_call` frame and no terminating `event: error` frame. A skill catalogue response alone proves registration, not execution.

## 6. Verify telemetry in Application Insights

Generate a chat or eval operation first. Then query the app traces API:

```bash
BACKEND="$(azd env get-value AGENT_SERVICE_URL)"

curl -fsS "$BACKEND/api/traces/operations?hours=1&limit=5" \
  | jq '{error:(.summary.error // ""), operations:(.operations|length), first:(.operations[0] // null)}'
```

Pass requires:

- `summary.error` is empty.
- `operations` is greater than 0.
- A detail query for one operation has a non-empty `spans` array.

A skipped `05-traces.spec.ts` is not proof. It only means there were zero operations in the lookback window.

Use a direct Application Insights query as the independent proof:

```bash
RG="$(azd env get-value AZURE_RESOURCE_GROUP)"
APP_ID="$(az resource list -g "$RG" --resource-type microsoft.insights/components --query '[0].id' -o tsv)"

az monitor app-insights query --ids "$APP_ID" \
  --analytics-query "union dependencies, requests, traces | where timestamp > ago(1h) | summarize rows=count(), operations=dcount(operation_Id), roles=dcount(cloud_RoleName)" \
  -o json
```

For a specific conversation, filter on `customDimensions['kratos.conversation_id']`.

## 7. Run the included Playwright smoke tests

```bash
cd .copilot/skills/e2e-smoke
SKIP_BROWSER=1 ./run.sh
./run.sh
jq '{unexpected:.stats.unexpected, skipped:.stats.skipped}' test-results/results.json
```

API-only mode skips browser specs. The full run should pass without failures. Treat a traces skip as inconclusive for telemetry unless the direct checks above already passed.

## 8. Copilot token, local mode only

Cloud deployment uses Azure Managed Identity and Foundry. It should not need a Copilot token.

For local mode:

1. Create a GitHub token with Copilot access from your GitHub account settings.
2. Copy `.env.local.example` to `.env.local`.
3. Set `COPILOT_GITHUB_TOKEN` in `.env.local`.
4. Keep `.env.local` uncommitted.

## 9. Recovery paths

| Symptom | Action |
|---------|--------|
| Hosted-agent identity not found or roles missing | Re-run `azd deploy kratos-agent` or `azd up`, then run `./hooks/assign-agent-roles.sh` from the repo root. |
| OBO admin consent skipped | Ask an Entra admin to run `az ad app permission admin-consent --id <server-app-client-id>` or grant consent in the app registration portal. |
| Skills upload skipped because blob storage is private | This does not block the baked-in use cases. To upload edited skills without redeploying, run `./hooks/postdeploy.sh` from a host inside the VNet or from the running backend container. |
| Foundry custom agent missing in Operate | Register the custom agent again with name `kratos-agent`, endpoint from `AGENT_SERVICE_URL`, and API path `kratos-agent`. |
| Backend chat SSE returns provider HTTP 401 | Verify the backend Container App system-assigned identity has `Cognitive Services OpenAI User` and `Cognitive Services User` on the AI Services account, then wait for data-plane propagation. Do not set `AZURE_CLIENT_ID` on `agent-service`; its user-assigned identity is for ACR pull only. |
| Hosted-agent chat SSE returns provider HTTP 401 | Re-run `./hooks/assign-agent-roles.sh`, wait for data-plane propagation, then redeploy `kratos-agent` if needed. Capture the SSE `error.code` and backend logs before changing unrelated settings. |
