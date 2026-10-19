/**
 * Runtime configuration for the frontend.
 *
 * In production the static export cannot know the backend URL at build time
 * because `azd package` runs before `azd provision`.  We resolve the API URL
 * at runtime using this priority:
 *
 *  1. Build-time env var  — NEXT_PUBLIC_API_URL (set during `next build`)
 *  2. Runtime config file — <basePath>/config.json  (injected by azd hook)
 *  3. Same-origin fallback — <basePath> (calls go to the same host under the
 *     mount path, e.g. "/kratos/api/..." behind Front Door)
 *  4. Local dev fallback  — http://localhost:8000
 */

let _cachedApiUrl: string | null = null;

/**
 * The sub-path the app is mounted under (e.g. "/kratos"), or "" at the root.
 * Baked in at build time via next.config.js `env.NEXT_PUBLIC_BASE_PATH`.
 */
export function getBasePath(): string {
  return (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");
}

export function getApiUrl(): string {
  if (_cachedApiUrl !== null) return _cachedApiUrl;

  // 1. Build-time env (works for local dev with .env / NEXT_PUBLIC_API_URL)
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) {
    _cachedApiUrl = envUrl.replace(/\/+$/, "");
    return _cachedApiUrl;
  }

  // 2. Runtime config injected into window by config.json / script tag
  if (typeof window !== "undefined" && (window as unknown as Record<string, unknown>).__KRATOS_CONFIG__) {
    const cfg = (window as unknown as Record<string, unknown>).__KRATOS_CONFIG__ as Record<string, string>;
    const url = cfg.apiUrl || cfg.apiBaseUrl;
    if (url) {
      _cachedApiUrl = url.replace(/\/+$/, "");
      return _cachedApiUrl;
    }
  }

  // 3. Same-origin fallback under the mount path (works behind a proxy / APIM /
  //    SWA linked backend / Front Door path-mount). At the root this is "".
  _cachedApiUrl = getBasePath();
  return _cachedApiUrl;
}

/**
 * MSAL / OBO sign-in config for the agent.
 *
 * The signed-in user's token (scoped to the Entra-protected OBO MCP server) is
 * sent to the backend, forwarded to the hosted agent, and injected as the
 * `Authorization` header on the OBO MCP server so its tools run On-Behalf-Of
 * the user. When this config is absent the OBO feature is simply disabled and
 * the rest of the app keeps working (e.g. SWA EasyAuth-only deployments / local
 * dev without an Entra app registration).
 */
export interface AuthConfig {
  clientId: string;
  authority: string;
  /** Full delegated scope, e.g. "api://<server-appid>/access_as_user". */
  scope: string;
  /** MCP server name the token is keyed by (matches the backend OBO server). */
  mcpServerName: string;
  /** App mount sub-path (e.g. "/kratos"), used for the MSAL redirect URI. */
  basePath: string;
}

/**
 * Resolve the OBO sign-in config from runtime config.json (`auth` object) or
 * build-time NEXT_PUBLIC_* env vars. Returns null when not fully configured.
 */
export function getAuthConfig(): AuthConfig | null {
  let clientId = process.env.NEXT_PUBLIC_OBO_CLIENT_ID || "";
  let tenantId = process.env.NEXT_PUBLIC_OBO_TENANT_ID || "";
  let scope = process.env.NEXT_PUBLIC_OBO_SCOPE || "";
  let mcpServerName = process.env.NEXT_PUBLIC_OBO_SERVER_NAME || "graph-obo";

  if (typeof window !== "undefined") {
    const cfg = (window as unknown as Record<string, unknown>).__KRATOS_CONFIG__ as
      | Record<string, unknown>
      | undefined;
    const auth = cfg?.auth as Record<string, string> | undefined;
    if (auth) {
      clientId = auth.clientId || clientId;
      tenantId = auth.tenantId || tenantId;
      scope = auth.mcpScope || scope;
      mcpServerName = auth.mcpServerName || mcpServerName;
    }
  }

  if (!clientId || !tenantId || !scope) return null;

  return {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    scope,
    mcpServerName,
    basePath: getBasePath(),
  };
}

/**
 * Load runtime config from <basePath>/config.json (if present).
 * Call once at app startup before any API calls.
 */
export async function loadRuntimeConfig(): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    const res = await fetch(`${getBasePath()}/config.json`, { cache: "no-store" });
    if (res.ok) {
      const cfg = await res.json();
      (window as unknown as Record<string, unknown>).__KRATOS_CONFIG__ = cfg;
      _cachedApiUrl = null; // reset so getApiUrl() re-evaluates
      // Notify components that read config at mount time (e.g. the OBO sign-in
      // control) that runtime config — including the `auth` block — is now
      // available, so they can re-evaluate instead of staying disabled.
      window.dispatchEvent(new Event("kratos:config-loaded"));
    }
  } catch {
    // No config.json — that's fine, use fallbacks
  }
}

/** "mock" when the stack runs against the deterministic offline model. */
export function getDemoMode(): string {
  if (typeof window === "undefined") return "";
  const cfg = (window as unknown as Record<string, unknown>).__KRATOS_CONFIG__ as Record<string, unknown> | undefined;
  return typeof cfg?.demoMode === "string" ? cfg.demoMode : "";
}
