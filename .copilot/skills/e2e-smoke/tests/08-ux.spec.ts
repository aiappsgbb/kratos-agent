/**
 * UX smoke — the parts that ACTUALLY matter to users: real clicks, real
 * typing, real navigation. API contract is covered by 01-07; this spec
 * exercises the rendered surface end-to-end through Chromium so a CSS
 * regression, wrong selector, broken modal, or dead button can't ship.
 *
 * Runs only when SKIP_BROWSER is unset (default).
 */
import { test, expect, type Page } from "@playwright/test";
import { FRONTEND_URL, USE_CASES } from "./helpers";

async function gotoHome(page: Page) {
  await page.goto(FRONTEND_URL, { waitUntil: "domcontentloaded" });
  // Wait for runtime config + use-cases to land — landing input is the gate.
  await page
    .getByPlaceholder("Ask me anything...")
    .waitFor({ state: "visible", timeout: 30_000 });
  // Give Next.js client hydration time to attach React event handlers.
  await page
    .waitForLoadState("networkidle", { timeout: 20_000 })
    .catch(() => undefined);
}

async function openSkillsAdmin(page: Page) {
  // Sidebar may be collapsed on narrow viewports; ensure visible first.
  const sidebar = page.locator('aside[aria-label="Conversation sidebar"]');
  await sidebar.waitFor({ state: "visible" });
  // The sidebar footer button that opens the admin panel is labeled
  // "Agent Manager" (not "Skills" — that's the FIRST TAB inside the panel).
  const agentManagerBtn = page.getByRole("button", { name: "Agent Manager" });
  await agentManagerBtn.waitFor({ state: "visible", timeout: 10_000 });
  await agentManagerBtn.click();
  // Wait for the admin shell — the nav rendering "Evals" tab is a unique marker.
  // If the click didn't propagate due to a hydration race, retry once via JS.
  try {
    await page.getByRole("button", { name: /^Evals$/ }).waitFor({ timeout: 5_000 });
  } catch {
    await agentManagerBtn.click({ force: true });
    await page.getByRole("button", { name: /^Evals$/ }).waitFor({ timeout: 10_000 });
  }
}

test.describe("UX — interactive flows", () => {
  test("home loads with the configured use-cases in the persona selector", async ({ page }) => {
    await gotoHome(page);
    const persona = page.locator('select[aria-label="Select agent persona"]');
    await expect(persona, "persona <select> visible").toBeVisible();
    const optionValues = await persona.locator("option").evaluateAll((opts) =>
      opts.map((o) => (o as HTMLOptionElement).value),
    );
    for (const uc of USE_CASES) {
      expect(optionValues, `option for '${uc}' present`).toContain(uc);
    }
  });

  test("switching persona updates the persona selector value", async ({ page }) => {
    await gotoHome(page);
    const persona = page.locator('select[aria-label="Select agent persona"]');
    await expect(persona).toBeVisible();
    const optionValues = await persona.locator("option").evaluateAll((opts) =>
      opts.map((o) => (o as HTMLOptionElement).value).filter(Boolean),
    );
    expect(optionValues.length, "at least two personas to switch between").toBeGreaterThan(1);
    for (const value of optionValues.slice(0, 2)) {
      await persona.selectOption(value);
      await expect(persona).toHaveValue(value);
    }
  });

  test("landing textarea + send button triggers a chat and an assistant reply renders", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await gotoHome(page);

    const persona = page.locator('select[aria-label="Select agent persona"]');
    await persona.selectOption("generic");

    const input = page.getByPlaceholder("Ask me anything...");
    const probe = `e2e-${Date.now().toString(36)} reply with exactly: ok`;
    await input.fill(probe);

    // The send button uses aria-label="Send message" inside the landing card.
    await page.getByRole("button", { name: "Send message" }).first().click();

    // Once the chat starts, the same prompt appears in BOTH the sidebar
    // (truncated conversation title) and the main chat bubble — use .last()
    // to target the most recent rendering, which is the chat bubble.
    await expect(
      page.getByText(probe, { exact: false }).last(),
      "user message bubble rendered",
    ).toBeVisible({ timeout: 15_000 });

    // The run inspector's status pill is the unambiguous "done" signal: it
    // leaves "ready" while the agent runs and returns once the reply lands.
    await expect(page.getByTestId("assistant-message").first(), "assistant reply rendered").toBeVisible({
      timeout: 120_000,
    });
    await expect(
      page.locator('[data-testid="run-status"]').first(),
      "run status returns to ready after the assistant reply",
    ).toHaveAttribute("data-phase", "ready", { timeout: 120_000 });

    // Sanity: <main> should have grown well beyond just the user prompt.
    const mainText = await page.locator("main").innerText();
    expect(
      mainText.length,
      `main should contain more than the user prompt (got ${mainText.length} chars)`,
    ).toBeGreaterThan(probe.length + 5);
  });

  test("Skills admin panel: every tab renders its heading", async ({ page }) => {
    await gotoHome(page);
    await openSkillsAdmin(page);

    const expectedTabs: { label: string; heading: RegExp }[] = [
      { label: "Skills", heading: /^Skills$|Create Skill/i },
      { label: "System Prompt", heading: /System Prompt/i },
      { label: "APM", heading: /APM/i },
      { label: "Evals", heading: /Evaluations|Evals/i },
      { label: "Traces", heading: /Traces/i },
    ];

    for (const { label, heading } of expectedTabs) {
      await page.getByRole("button", { name: new RegExp(`^${label}$`) }).click();
      // Header h1/h2 should reflect the current tab — tolerate either.
      await expect(
        page.locator("h1, h2").filter({ hasText: heading }).first(),
        `tab '${label}' header should match ${heading}`,
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  test("Evals tab: 'Generate Scenarios' button opens modal then dismisses", async ({
    page,
  }) => {
    await gotoHome(page);
    await openSkillsAdmin(page);
    await page.getByRole("button", { name: /^Evals$/ }).click();

    // Wait for the toolbar to render the Generate Scenarios button.
    const generateBtn = page
      .getByRole("button", { name: /Generate Scenarios/i })
      .first();
    await generateBtn.waitFor({ state: "visible", timeout: 10_000 });
    await generateBtn.click();

    // Modal must surface a way to close (Cancel button, X aria-label="Close",
    // or clicking outside). Assert any of those reveals a Close affordance.
    const closeAffordances = page.getByRole("button", {
      name: /^(Close|Cancel|×)$/i,
    });
    await expect(
      closeAffordances.first(),
      "modal should expose a Close/Cancel affordance",
    ).toBeVisible({ timeout: 5_000 });

    await closeAffordances.first().click();
    // After close, the Generate Scenarios button should still be visible
    // (we're back on the Evals tab).
    await expect(generateBtn, "back on Evals tab after closing modal").toBeVisible();
  });

  test("Traces tab: Refresh button executes and renders either ops or empty state", async ({
    page,
  }) => {
    await gotoHome(page);
    await openSkillsAdmin(page);
    await page.getByRole("button", { name: /^Traces$/ }).click();

    const refreshBtn = page.getByRole("button", { name: /^Refresh$/ }).first();
    await refreshBtn.waitFor({ state: "visible", timeout: 10_000 });
    await refreshBtn.click();

    // Acceptable outcome (any of):
    //   - at least one operation row rendered (matches operation id chip / time)
    //   - the explicit empty state "No operations found"
    //   - a summary card with token / latency stats visible
    await expect(
      page
        .getByText(/No operations found|operations|total operations|avg latency/i)
        .first(),
      "Traces panel must render either ops, summary, or empty state",
    ).toBeVisible({ timeout: 20_000 });
  });
});
