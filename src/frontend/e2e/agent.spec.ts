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

test("the agent draws a live chart in the chat", async ({ page }) => {
  await startConversation(page, "Show me the demo chart");
  const chart = page.getByTestId("chart-card");
  await expect(chart).toHaveAttribute("data-ready", "true");
  await expect(chart).toHaveAttribute("data-kind", "donut");
  await expect(chart).toContainText("Demo portfolio allocation");
  await chart.getByRole("button", { name: "Show data" }).click();
  await expect(chart.getByRole("table")).toContainText("Equities");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Equities dominate at 55%");
  await page.screenshot({ path: "test-results/chart.png" });
});

test("editing the agent's proposal sends the user's numbers back to the agent", async ({ page }) => {
  await startConversation(page, "Run the demo rebalance");
  const card = page.getByTestId("allocation-card");
  await expect(card).toHaveAttribute("data-state", "pending");
  await expect(status(page)).toHaveAttribute("data-phase", "waiting");

  // Move 5pp from Bonds to Cash: Equities 55, Bonds 30, Cash 15.
  const sliders = card.getByTestId("allocation-slider");
  await sliders.nth(1).fill("30");
  await expect(card.getByTestId("allocation-total")).toHaveText("95%");
  await expect(card.getByTestId("allocation-approve")).toBeDisabled();
  await sliders.nth(2).fill("15");
  await expect(card.getByTestId("allocation-total")).toHaveText("100%");
  await page.screenshot({ path: "test-results/rebalance-edit.png" });

  await card.getByTestId("allocation-approve").click();

  await expect(page.getByTestId("assistant-message").last()).toContainText("Approved with your edits: Equities 55%, Bonds 30%, Cash 15%.");
  await expect(card).toHaveAttribute("data-state", "approved");
  await expect(status(page)).toHaveAttribute("data-phase", "ready");
  await page.screenshot({ path: "test-results/rebalance-approved.png" });
});

test("tables are sortable and metrics show status", async ({ page }) => {
  await startConversation(page, "Show me the demo table");
  const table = page.getByTestId("table-card");
  await expect(table.locator("tbody tr")).toHaveCount(3);
  await table.getByRole("button", { name: /Amount/ }).click();
  await table.getByRole("button", { name: /Amount/ }).click();
  await expect(table.locator("tbody tr").first()).toContainText("Airline");
  await expect(page.getByTestId("assistant-message").last()).toContainText("airline ticket is the largest");

  await page.getByTestId("message-input").fill("Now the demo metrics");
  await page.getByTestId("send-button").click();
  const metrics = page.getByTestId("metrics-card");
  await expect(metrics).toContainText("71.2%");
  await expect(metrics).toContainText("Availability");
  await expect(page.getByTestId("assistant-message").last()).toContainText("OEE is below target");
  await page.screenshot({ path: "test-results/table-metrics.png" });
});

test.describe("push-to-talk", () => {
  test.beforeEach(async ({ page }) => {
    // Stand-in for the browser's speech recognition: it "hears" a sentence in
    // two interim chunks, then a final result, and ends when stopped.
    await page.addInitScript(() => {
      class FakeRecognition {
        lang = "";
        continuous = false;
        interimResults = false;
        onresult: ((e: unknown) => void) | null = null;
        onerror: ((e: unknown) => void) | null = null;
        onend: (() => void) | null = null;
        private timers: number[] = [];
        start() {
          const say = (at: number, text: string, isFinal: boolean) =>
            this.timers.push(
              window.setTimeout(() => this.onresult?.({ resultIndex: 0, results: [{ isFinal, 0: { transcript: text } }] }), at),
            );
          say(100, "What is the", false);
          say(250, "What is the capital of France?", true);
        }
        stop() {
          this.timers.forEach((t) => clearTimeout(t));
          window.setTimeout(() => this.onend?.(), 20);
        }
        abort() {
          this.stop();
        }
      }
      (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = FakeRecognition;
    });
  });

  test("hold the mic to talk; releasing sends what was heard", async ({ page }) => {
    await startConversation(page, "What is the capital of France?");
    await expect(status(page)).toHaveAttribute("data-phase", "ready");

    const mic = page.getByTestId("mic-button");
    await mic.hover();
    await page.mouse.down();
    await expect(page.getByTestId("voice-status")).toContainText("release to send");
    await expect(page.getByTestId("message-input")).toHaveValue("What is the capital of France?");
    await page.waitForTimeout(400); // a hold, not a tap
    await page.mouse.up();

    await expect(page.getByTestId("user-message")).toHaveCount(2);
    await expect(page.getByTestId("user-message").last()).toContainText("What is the capital of France?");
    await expect(page.getByTestId("assistant-message").last()).toContainText("Paris");
    await expect(page.getByTestId("message-input")).toHaveValue("");
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

test("a rebalance proposal survives a page reload and can still be approved", async ({ page }) => {
  await startConversation(page, "Run the demo rebalance");
  await expect(page.getByTestId("allocation-card")).toHaveAttribute("data-state", "pending");
  const title = await page.locator("header h1").first().innerText();

  await page.reload();
  await page.getByText(/^All \(/).first().click();
  await page.locator("select").first().selectOption("generic");
  await page.getByText(title).first().click();

  const card = page.getByTestId("allocation-card");
  await expect(card).toHaveAttribute("data-state", "pending");
  await expect(status(page)).toHaveAttribute("data-phase", "waiting");
  await expect(page.getByTestId("message-input")).toBeDisabled();
  await card.getByTestId("allocation-approve").click();

  await expect(page.getByTestId("assistant-message").last()).toContainText("Approved: Equities 55%, Bonds 35%, Cash 10%.");
  await expect(card).toHaveAttribute("data-state", "approved");
  await expect(page.getByTestId("message-input")).toBeEnabled();
});

test("a chart sent in a non-schema shape still renders", async ({ page }) => {
  await startConversation(page, "Show me the demo odd chart");
  const chart = page.getByTestId("chart-card");
  await expect(chart).toHaveAttribute("data-ready", "true");
  await chart.getByRole("button", { name: "Show data" }).click();
  await expect(chart.getByRole("table")).toContainText("Target");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Line 2 is furthest below target.");
});
