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
    }
  } catch {
    // No config.json — that's fine, use fallbacks
  }
}
