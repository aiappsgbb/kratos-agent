#!/usr/bin/env node
// capture.mjs — drive the real signed-in frontend over CDP and capture the
// authentic artifacts for the walkthrough:
//   * the user access token the FRONTEND attaches under mcpAccessTokens
//   * which keys it attached
//   * the rendered agent answer
//
// Writes out/browser-capture.json. Connects to an already-running Edge so the
// operator can complete interactive MSAL/MFA. Uses playwright-core (no bundled
// browsers — we attach to the operator's Edge over CDP).
import { writeFileSync } from "node:fs";
import { chromium } from "playwright-core";

const FRONTEND_URL = process.env.KRATOS_FRONTEND_URL || process.env.OBO_FRONTEND_URL || "";
const CDP_URL = process.env.OBO_CDP_URL || "http://localhost:9222";
const TIMEOUT = Number(process.env.CHAT_TIMEOUT_MS || 150000);
const OUT = process.env.CAPTURE_OUT || "out/browser-capture.json";
const PROMPT =
  process.env.DEMO_PROMPT ||
  "Use your Microsoft Graph profile tool to look me up. Strictly from the tool result, " +
    "report for the signed-in user: displayName, userPrincipalName, Entra object id (id), " +
    "department, jobTitle, officeLocation, preferredLanguage, and the tool's graphRequestId " +
    "and fetchedAtUtc values. Present them as a simple list.";

if (!FRONTEND_URL) {
  console.error("[capture] set KRATOS_FRONTEND_URL to the deployed frontend");
  process.exit(2);
}

const browser = await chromium.connectOverCDP(CDP_URL);
const context = browser.contexts()[0] ?? (await browser.newContext());

let capturedToken;
let capturedKeys = [];
context.on("request", (req) => {
  if (req.method() === "POST" && req.url().includes("/api/agent/chat")) {
    try {
      const data = JSON.parse(req.postData() || "{}");
      const tokens = data.mcpAccessTokens || {};
      capturedKeys = Object.keys(tokens);
      capturedToken = tokens["graph-obo"] || Object.values(tokens)[0];
    } catch {
      /* ignore */
    }
  }
});

const page = context.pages().find((p) => p.url().startsWith(FRONTEND_URL)) ?? (await context.newPage());
await page.goto(FRONTEND_URL, { waitUntil: "domcontentloaded" });

const signInBtn = page.getByRole("button", { name: /sign in.*(on-behalf|obo)/i });
if (await signInBtn.isVisible().catch(() => false)) {
  console.error("[capture] clicking OBO sign-in …");
  await signInBtn.click().catch(() => undefined);
}
await page
  .getByText(/signed in:/i)
  .first()
  .waitFor({ timeout: 120000 })
  .catch(() => undefined);
const signedInText = await page
  .getByText(/signed in:/i)
  .first()
  .innerText()
  .catch(() => "");

const input = page.getByRole("textbox").or(page.locator("textarea, [contenteditable='true']")).first();
await input.waitFor({ timeout: 30000 });
await input.click();
await input.fill(PROMPT);
await input.press("Enter");
console.error("[capture] prompt sent; waiting for answer …");

await page
  .getByText(/@/)
  .last()
  .waitFor({ timeout: TIMEOUT })
  .catch(() => undefined);
// settle for streaming to finish
await page.waitForTimeout(4000);

const bodyText = await page.locator("body").innerText().catch(() => "");
// crude: the answer is the longest block mentioning a UPN-ish '@'
const answer = (() => {
  const lines = bodyText.split("\n").map((l) => l.trim()).filter(Boolean);
  const idx = lines.map((l, i) => (/@/.test(l) ? i : -1)).filter((i) => i >= 0).pop();
  if (idx == null) return bodyText.slice(-1500);
  return lines.slice(Math.max(0, idx - 12), idx + 6).join("\n");
})();

const out = {
  target: "cloud",
  frontend: FRONTEND_URL,
  prompt: PROMPT,
  userToken: capturedToken || "",
  requestBodyKeys: capturedKeys,
  signedIn: signedInText,
  answer,
  tokenVisibleOnPage: capturedToken ? bodyText.toLowerCase().includes(capturedToken.toLowerCase()) : false,
};
writeFileSync(OUT, JSON.stringify(out, null, 2));
console.error(
  `[capture] token=${capturedToken ? "captured" : "MISSING"} keys=[${capturedKeys}] tokenLeak=${out.tokenVisibleOnPage} -> ${OUT}`,
);
// NB: do NOT close the browser — this is a CDP-attached Edge owned by the
// operator. Just exit; the process exit drops our CDP connection cleanly
// without tearing down their tabs/session.
process.exit(0);
