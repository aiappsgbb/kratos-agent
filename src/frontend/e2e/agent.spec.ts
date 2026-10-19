import { expect, test, type Page } from "@playwright/test";

// Runs against the scripted model in e2e/mock-model.mjs; prompts must match its intents.

async function startConversation(page: Page, prompt: string) {
  await page.goto("/");
  await page.getByText(/^All \(/).first().click();
  await page.locator("select").first().selectOption("generic");
  const box = page.getByPlaceholder("Ask me anything...").first();
  await box.fill(prompt);
  await box.press("Enter");
  await expect(page.getByTestId("agent-workspace")).toBeVisible();
  await expect(page.getByTestId("mock-badge")).toBeVisible();
  await expect(page.getByTestId("user-message").first()).toContainText(prompt);
}

const status = (page: Page) => page.getByTestId("run-status");

test("streams an answer with run stats", async ({ page }) => {
  await startConversation(page, "What is the capital of France?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Paris");
  await expect(status(page)).toHaveAttribute("data-phase", "ready");
  await expect(page.getByTestId("run-stats").last()).toContainText("tokens");
  await expect(page.getByTestId("activity-item").first()).toHaveAttribute("data-state", "done");
});

test("approval in chat resumes the paused turn with the user's answer", async ({ page }) => {
  await startConversation(page, "Run the demo approval flow");
  await expect(status(page)).toHaveAttribute("data-phase", "waiting");
  const card = page.getByTestId("decision-card");
  await expect(card).toHaveAttribute("data-state", "pending");
  await expect(card).toContainText("Apply the demo change to ticket INC-0001?");
  await expect(page.getByTestId("decision-panel")).toBeVisible();
  await expect(page.getByTestId("message-input")).toHaveAttribute("placeholder", /Answer the agent's question/);

  await card.getByTestId("decision-choice").filter({ hasText: "Approve" }).click();

  await expect(page.getByTestId("assistant-message").last()).toContainText("Approved. The demo change to INC-0001 was applied.");
  await expect(card).toHaveAttribute("data-state", "answered");
  await expect(card.getByTestId("decision-answer")).toContainText("Approve");
  await expect(page.getByTestId("decision-panel")).toHaveCount(0);
  await expect(status(page)).toHaveAttribute("data-phase", "ready");
  await page.screenshot({ path: "test-results/approval-approved.png" });
});

test("rejecting from the run inspector reaches the model as a rejection", async ({ page }) => {
  await startConversation(page, "Run the demo approval flow");
  const panel = page.getByTestId("decision-panel");
  await expect(panel).toBeVisible();

  await panel.getByTestId("decision-choice").filter({ hasText: "Reject" }).click();

  await expect(page.getByTestId("assistant-message").last()).toContainText("Rejected. Nothing was changed on INC-0001.");
  await expect(page.getByText("Approved. The demo change")).toHaveCount(0);
});

test("backend tool calls render as live cards and survive a reload", async ({ page }) => {
  await startConversation(page, "Please load the email skill");
  const chip = page.locator('[data-testid="tool-call"][data-tool="email-draft"]');
  await expect(chip).toHaveAttribute("data-status", "complete");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Loaded the email-draft skill");
  const title = await page.locator("header h1").first().innerText();

  await page.reload();
  await page.getByText(/^All \(/).first().click();
  await page.locator("select").first().selectOption("generic");
  await page.getByText(title).first().click();

  await expect(page.locator('[data-testid="tool-call"][data-tool="email-draft"]')).toHaveAttribute("data-status", "complete");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Loaded the email-draft skill");
  await chip.first().getByRole("button").click();
  await expect(page.locator('[id^="tool-"]').first()).toContainText("Result");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("a pending decision opens the inspector, which can answer it", async ({ page }) => {
    // The sidebar is off-canvas here; the scripted prompts work with any persona.
    await page.goto("/");
    const box = page.getByPlaceholder("Ask me anything...").first();
    await box.fill("Run the demo approval flow");
    await box.press("Enter");

    const panel = page.getByTestId("decision-panel");
    await expect(panel).toBeVisible();
    await page.screenshot({ path: "test-results/mobile-decision.png" });
    await panel.getByTestId("decision-choice").filter({ hasText: "Approve" }).click();
    await page.getByRole("button", { name: "Close inspector" }).click();

    await expect(page.getByTestId("assistant-message").last()).toContainText("Approved.");
    await expect(page.getByTestId("toggle-inspector")).toBeVisible();
    await page.screenshot({ path: "test-results/mobile-answered.png" });
  });
});

test("an approval survives a page reload and can still be answered", async ({ page }) => {
  await startConversation(page, "Run the demo approval flow");
  await expect(page.getByTestId("decision-card")).toHaveAttribute("data-state", "pending");
  const title = await page.locator("header h1").first().innerText();

  await page.reload();
  await page.getByText(/^All \(/).first().click();
  await page.locator("select").first().selectOption("generic");
  await page.getByText(title).first().click();

  const card = page.getByTestId("decision-card");
  await expect(card).toHaveAttribute("data-state", "pending");
  await expect(status(page)).toHaveAttribute("data-phase", "waiting");
  await expect(page.getByTestId("message-input")).toBeDisabled();
  await card.getByTestId("decision-choice").filter({ hasText: "Approve" }).click();

  await expect(page.getByTestId("assistant-message").last()).toContainText("Approved. The demo change to INC-0001 was applied.");
  await expect(page.getByTestId("message-input")).toBeEnabled();
});
