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

  return {
    content:
      "This is the offline mock model, so it only answers scripted prompts: ask for the capital of France, a demo approval, or to load the email skill.",
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
