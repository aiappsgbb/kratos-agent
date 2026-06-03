# Kratos Mocks

In-repo stdio MCP servers that mock enterprise systems with curated fixtures.
Each package is a standard stdio MCP server (built on
[`@modelcontextprotocol/sdk`](https://github.com/modelcontextprotocol/typescript-sdk))
that the Copilot SDK launches per use-case via `.mcp.json`.

The Faker MCP (`faker-mcp-server`, npm) is the reference. These mocks follow the
same shape: a single binary on PATH, no HTTP, no auth, JSON-RPC over stdio.

## Packages

| Package | Mocks | Used by |
|---|---|---|
| `salesforce-mcp-server` | Salesforce CRM — accounts, opportunities, contacts, activities, cases | `use-cases/sales-account-review` |
| `workday-mcp-server` | Workday HCM — orgs, positions, employees, time-off, payroll, shifts (+ write tools for create-employee and approve-time-off) | `use-cases/hr-onboarding` |
| `servicenow-mcp-server` | ServiceNow ITSM — users, incidents/requests/change, work notes, KB articles, CMDB (+ write tools for create-incident, update-state, assign, add-work-note) | `use-cases/it-service-desk` |

## Build

```bash
cd mocks
npm install
npm run build
```

This installs workspace deps and compiles each package's TypeScript to `dist/`.

## Wiring into Kratos

1. **Docker (default)** — both `src/backend/Dockerfile` and `src/hosted-agent/Dockerfile`
   copy `mocks/` into the image and run `npm install -g ./mocks/packages/*` so the
   `<system>-mcp-server` binary is on PATH.
2. **Native (`.venv` flow)** — run `npm link` inside each package after `npm run build`,
   then the binary is on your host PATH and `uvicorn` can launch it.

A use-case enables a mock by adding it to `use-cases/<uc>/.mcp.json`:

```json
{
  "salesforce": {
    "type": "local",
    "command": "salesforce-mcp-server",
    "args": [],
    "tools": ["*"]
  }
}
```

## Authoring a new mock

1. Create `packages/<system>-mcp-server/` (copy Salesforce as the template).
2. Set `bin` in `package.json` to `<system>-mcp-server` pointing to `dist/server.js`.
3. Define tools with `server.registerTool(...)` — name them `<system>_<verb>_<noun>`.
4. Put fixtures in `src/data/*.json`. Keep IDs consistent across files so the
   data graph stays coherent (an `accountId` returned by one tool must resolve
   in another).
5. Add the package to the table above and to both Dockerfiles.

## Testing a mock standalone

```bash
npx @modelcontextprotocol/inspector node packages/salesforce-mcp-server/dist/server.js
```

The inspector gives you a UI to list tools, call them with arguments, and see the
JSON-RPC traffic.
