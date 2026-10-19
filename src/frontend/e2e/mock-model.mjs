// Deterministic OpenAI-compatible model for offline demos and e2e tests.
//
// The real stack runs unchanged (CopilotKit -> runtime route -> backend ->
// hosted agent -> Copilot SDK -> AG-UI adapter); only the model is scripted. The
// hosted agent reaches it through the local-mode BYOK override:
//   OPENAI_BASE_URL=http://127.0.0.1:5567/v1 OPENAI_API_KEY=mock-not-a-secret
//
// Scripted intents (anything else gets a hint rather than a fake answer):
//   "capital of France"     -> plain streamed answer
//   "demo approval"         -> ask_user (Approve / Reject), then a branch-specific answer
//   "load the email skill"  -> real `skill` tool call, then a summary of its result
//   "demo chart"            -> render_chart (generative UI), then an interpretation
//   "demo rebalance"        -> propose_allocation (editable HITL card), then the final weights
//   "demo table" / "demo metrics" -> show_table / show_metrics, then a one-line summary
import { pathToFileURL } from "node:url";
import { LLMock } from "@copilotkit/aimock";

const textOf = (content) =>
  typeof content === "string"
    ? content
    : Array.isArray(content)
      ? content.map((p) => (p?.type === "text" ? p.text : "")).join("\n")
      : "";

/** Tool names can reach the model namespaced (<prefix>__name); echo the offered name. */
const offered = (req, name) =>
  (req.tools ?? []).map((t) => t.function?.name).find((n) => n && n.split("__").at(-1) === name);

function turn(req) {
  const messages = req.messages ?? [];
  // The runtime also injects user-role messages (e.g. a loaded skill's body);
  // the person's own prompts carry its <current_datetime> stamp.
  let userIndex = messages.findLastIndex((m) => m.role === "user" && textOf(m.content).includes("<current_datetime>"));
  if (userIndex < 0) userIndex = messages.findLastIndex((m) => m.role === "user");
  const user = textOf(messages[userIndex]?.content)
    .replace(/<current_datetime>[\s\S]*?<\/current_datetime>/g, "")
    .trim();
  const results = messages.slice(userIndex + 1).filter((m) => m.role === "tool").map((m) => textOf(m.content));
  return { user, results };
}

function call(req, name, args) {
  const toolName = offered(req, name);
  if (!toolName) throw new Error(`Mock model: tool "${name}" was not offered to the model.`);
  return { toolCalls: [{ name: toolName, arguments: JSON.stringify(args) }] };
}

export function respond(req) {
  const { user, results } = turn(req);

  if (/capital of France/i.test(user)) return { content: "The capital of France is **Paris**." };

  if (/demo approval/i.test(user)) {
    if (results.length === 0) {
      return call(req, "ask_user", {
        question: "Apply the demo change to ticket INC-0001?",
        choices: ["Approve", "Reject"],
        allowFreeform: false,
      });
    }
    const answer = results.at(-1) ?? "";
    if (/^approve/i.test(answer.trim())) return { content: "Approved. The demo change to INC-0001 was applied." };
    return { content: "Rejected. Nothing was changed on INC-0001." };
  }

  if (/load the email skill/i.test(user)) {
    if (results.length === 0) return call(req, "skill", { skill: "email-draft" });
    return { content: `Loaded the email-draft skill (${results.at(-1).length} characters of instructions).` };
  }

  if (/demo table/i.test(user)) {
    if (results.length === 0) {
      return call(req, "show_table", {
        title: "Demo transactions",
        caption: "Scripted mock data",
        columns: [
          { key: "date", label: "Date" },
          { key: "merchant", label: "Merchant" },
          { key: "amount", label: "Amount", format: "currency", currency: "USD" },
        ],
        rows: [
          { date: "2026-10-01", merchant: "Grocer", amount: 82.4 },
          { date: "2026-10-03", merchant: "Airline", amount: 412 },
          { date: "2026-10-05", merchant: "Cafe", amount: 6.5 },
        ],
      });
    }
    return { content: "The airline ticket is the largest of the three transactions." };
  }

  if (/demo metrics/i.test(user)) {
    if (results.length === 0) {
      return call(req, "show_metrics", {
        title: "Demo shift health",
        metrics: [
          { label: "OEE", value: 71.2, unit: "%", delta: -4.8, deltaLabel: "pp vs target", status: "bad" },
          { label: "Availability", value: 88, unit: "%", status: "warning" },
          { label: "Quality", value: 99.1, unit: "%", status: "good" },
        ],
      });
    }
    return { content: "OEE is below target, driven by availability." };
  }

  if (/demo odd chart/i.test(user)) {
    // The shape a live model sent when it guessed the schema of a deferred tool.
    if (results.length === 0) {
      return call(req, "render_chart", {
        type: "bar",
        title: "OEE gap to target by line",
        data: [
          { label: "Line 1", value: 90.2, target: 90 },
          { label: "Line 2", value: 74.1, target: 85 },
        ],
      });
    }
    return { content: "Line 2 is furthest below target." };
  }

  if (/demo chart/i.test(user)) {
    if (results.length === 0) {
      return call(req, "render_chart", {
        title: "Demo portfolio allocation",
        subtitle: "Scripted mock data",
        kind: "donut",
        labels: ["Equities", "Bonds", "Cash", "Alternatives"],
        series: [{ name: "Weight", values: [55, 30, 5, 10] }],
        unit: "%",
      });
    }
    return { content: "Equities dominate at 55%, with bonds as the main ballast at 30%." };
  }

  if (/demo rebalance/i.test(user)) {
    if (results.length === 0) {
      return call(req, "propose_allocation", {
        title: "Rebalance toward the target model",
        rationale: "Equities drifted above target after the rally; trimming them restores the agreed risk budget.",
        items: [
          { name: "Equities", current: 62, proposed: 55 },
          { name: "Bonds", current: 28, proposed: 35 },
          { name: "Cash", current: 10, proposed: 10 },
        ],
      });
    }
    const decision = JSON.parse(results.at(-1));
    if (decision.decision !== "approved") return { content: "Understood. The rebalance is cancelled; nothing changes." };
    const weights = decision.allocation.map((a) => `${a.name} ${a.proposed}%`).join(", ");
    return { content: `Approved${decision.edited ? " with your edits" : ""}: ${weights}.` };
  }

  return {
    content:
      "This is the offline mock model, so it only answers scripted prompts: ask for the capital of France, a demo approval, a demo chart, table, metrics or rebalance, or to load the email skill.",
  };
}

export function createMockServer({ port = 5567 } = {}) {
  const mock = new LLMock({ port, host: "127.0.0.1", latency: 5, chunkSize: 24, logLevel: "silent", strict: false });
  mock.addFixture({ match: { endpoint: "chat" }, response: (req) => respond(req) });
  return mock;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.MOCK_PORT || 5567);
  const mock = createMockServer({ port });
  console.log(`[mock-model] ${await mock.start()}/v1 (aimock, deterministic)`);
  for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => void mock.stop().then(() => process.exit(0)));
}
