/**
 * Embed-mode support.
 *
 * Kratos can be hosted "embedded" under another origin (e.g. agentic-loop-site
 * behind Front Door at `/kratos/*`). When the host opens the app with
 * `?embed=1`, Kratos renders chromeless (no marketing sidebar) and reacts to a
 * small set of URL args so the host can drive it:
 *
 *   ?embed=1            — chromeless layout
 *   &theme=dark         — sync light/dark mode (or a named Kratos theme)
 *   &mode=dark          — sync light/dark mode independently of a named theme
 *                         (lets the host pass &theme=agentic-loop&mode=dark)
 *   &persona=<slug>     — open this persona (post-import landing target)
 *   &prompt=<text>      — auto-start a conversation with this first message
 *   &import=1           — read a relayed manifest from sessionStorage and POST
 *                         it to the import API, then settle on ?persona=<slug>
 *
 * The manifest is relayed **same-origin** via `sessionStorage` (Variant B in the
 * design spec): the host writes `sessionStorage['kratos.import']` then navigates
 * to `/kratos/?embed=1&import=1`. Kratos reads-and-clears it on entry, after its
 * own EasyAuth login, so the authenticated import POST runs inside Kratos with
 * no cross-app fetch / CORS / 401-follow.
 */

export const IMPORT_RELAY_KEY = "kratos.import";

export interface EmbedParams {
  embed: boolean;
  theme: string | null;
  mode: string | null;
  persona: string | null;
  prompt: string | null;
  doImport: boolean;
}

function truthy(value: string | null): boolean {
  return value === "1" || value === "true" || value === "yes";
}

/** Parse embed-relevant args from the current URL. SSR-safe (returns defaults). */
export function readEmbedParams(): EmbedParams {
  if (typeof window === "undefined") {
    return { embed: false, theme: null, mode: null, persona: null, prompt: null, doImport: false };
  }
  const p = new URLSearchParams(window.location.search);
  return {
    embed: truthy(p.get("embed")),
    theme: p.get("theme"),
    mode: p.get("mode"),
    persona: p.get("persona"),
    prompt: p.get("prompt"),
    doImport: truthy(p.get("import")),
  };
}

/**
 * Read **and clear** the relayed import manifest from sessionStorage.
 * Returns the parsed object, or null when absent/invalid.
 */
export function takeImportManifest(): unknown | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(IMPORT_RELAY_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(IMPORT_RELAY_KEY);
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Rewrite the URL to the post-import resting state: drop the one-shot
 * `import`/`prompt` args and pin `persona=<slug>` so a reload re-opens the
 * imported persona instead of re-triggering the import.
 */
export function settlePersonaUrl(persona: string): void {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete("import");
    url.searchParams.delete("prompt");
    url.searchParams.set("persona", persona);
    window.history.replaceState({}, "", url.toString());
  } catch {
    // history.replaceState can throw in sandboxed iframes — non-fatal.
  }
}
