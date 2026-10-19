// Runtime configuration for the browser, read from the server's environment on
// every request. Replaces the config.json the Static Web App deploy hook used to
// write into the static export: the same image now serves every environment.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");
  const config: Record<string, unknown> = {};

  // Behind Front Door the backend is same-origin under <basePath>/api/*.
  // Otherwise the browser calls the agent service directly; in `next dev` that
  // defaults to the local backend, matching the runtime route.
  const apiUrl =
    basePath ||
    process.env.KRATOS_API_URL ||
    process.env.AGENT_BACKEND_URL ||
    (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000");
  if (apiUrl) config.apiUrl = apiUrl.replace(/\/+$/, "");

  const clientId = process.env.OBO_CLIENT_APP_CLIENT_ID;
  const tenantId = process.env.OBO_TENANT_ID;
  const identifierUri = process.env.OBO_SERVER_APP_IDENTIFIER_URI;
  if (clientId && tenantId && identifierUri) {
    config.auth = {
      clientId,
      tenantId,
      mcpScope: `${identifierUri}/${process.env.OBO_SERVER_APP_SCOPE_VALUE || "access_as_user"}`,
      mcpServerName: process.env.OBO_MCP_SERVER_NAME || "graph-obo",
    };
  }

  if (process.env.KRATOS_DEMO_MODE) config.demoMode = process.env.KRATOS_DEMO_MODE;

  return Response.json(config, { headers: { "cache-control": "no-store" } });
}
