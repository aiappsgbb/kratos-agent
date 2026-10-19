import { test, expect, request } from "@playwright/test";
import { BACKEND_URL, CHAT_TIMEOUT_MS, FRONTEND_URL } from "./helpers";

/**
 * The AG-UI path the UI uses: browser -> web /copilotkit/kratos (CopilotKit
 * runtime) -> backend /api/agui -> Foundry hosted agent (Copilot SDK adapter).
 */
test.describe("AG-UI agent path", () => {
  test.setTimeout(CHAT_TIMEOUT_MS * 2 + 30_000);

  test("web CopilotKit runtime exposes the kratos agent", async () => {
    const api = await request.newContext();
    const resp = await api.post(`${FRONTEND_URL}/copilotkit/kratos`, { data: { method: "info" } });
    expect(resp.status(), "runtime info status").toBe(200);
    const info = await resp.json();
    expect(Object.keys(info.agents ?? {}), "runtime agents").toContain("kratos");
  });

  test("backend /api/agui streams a complete AG-UI run", async () => {
    const threadId = `e2e-agui-${Date.now().toString(36)}`;
    const resp = await fetch(`${BACKEND_URL}/api/agui`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify({
        threadId,
        runId: "r1",
        state: {},
        messages: [{ id: "u1", role: "user", content: "Reply with exactly: ok" }],
        tools: [],
        context: [],
        forwardedProps: { useCase: "generic" },
      }),
      signal: AbortSignal.timeout(CHAT_TIMEOUT_MS * 2),
    });
    expect(resp.status, "agui status").toBe(200);

    const events = (await resp.text())
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => JSON.parse(line.slice(6)) as { type: string; delta?: string; message?: string });
    const types = events.map((e) => e.type);
    const error = events.find((e) => e.type === "RUN_ERROR");
    expect(error?.message, "no RUN_ERROR").toBeUndefined();
    expect(types[0], "first event").toBe("RUN_STARTED");
    expect(types.at(-1), "last event").toBe("RUN_FINISHED");
    const text = events.filter((e) => e.type === "TEXT_MESSAGE_CONTENT").map((e) => e.delta).join("");
    expect(text.trim().length, "assistant text streamed").toBeGreaterThan(0);
  });
});
