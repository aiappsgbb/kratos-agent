import { test, expect, request } from "@playwright/test";
import { BACKEND_URL, chatOnce, CHAT_TIMEOUT_MS, stringValue } from "./helpers";

const INTERNAL_TOOLS = new Set(["ask-user", "report-intent", "skill", "sql"]);

test.describe("chat round-trip", () => {
  test.setTimeout(CHAT_TIMEOUT_MS * 2 + 30_000);

  test("agent responds to a tiny prompt for the 'generic' use-case", async () => {
    // Best-effort warmup; tolerate cold-start.
    await chatOnce("ping", "generic", 30_000).catch(() => undefined);

    const { text, ok, status } = await chatOnce(
      "Reply with exactly one short sentence confirming you are online.",
      "generic",
    );

    expect(
      ok,
      `chat should succeed (status=${status}, text snippet="${text.slice(0, 200)}")`,
    ).toBe(true);
    expect(
      text.trim().length,
      "assistant response should be non-empty",
    ).toBeGreaterThan(0);
  });

  test("agent emits a skill tool_call for a scenario that expects a tool", async () => {
    const api = await request.newContext();
    const scenariosResp = await api.get(`${BACKEND_URL}/api/use-cases/generic/evals/scenarios`);
    expect(scenariosResp.status(), "generic scenarios status").toBe(200);
    const scenariosBody = await scenariosResp.json();
    const scenarios: Record<string, unknown>[] = scenariosBody.scenarios ?? [];
    const scenario = scenarios.find((candidate) => stringValue(candidate.name) === "code-interpreter-math");

    expect(
      scenario,
      "generic should include the code-interpreter-math scenario",
    ).toBeTruthy();

    const expectedTools = (scenario!.expected_tool_calls as unknown[])
      .map((tool) => stringValue(tool))
      .map(normalizeToolName)
      .filter(Boolean);
    const prompt = stringValue(scenario!.input_message);
    expect(prompt, "scenario input_message").toBeTruthy();
    console.log(
      `skill scenario=${stringValue(scenario!.name)} expected=${expectedTools.join(",")}`,
    );

    const { events, ok, status, text } = await chatOnce(prompt, "generic");
    const eventNames = events.map((event) => event.event);
    const toolNames = events
      .filter((event) => event.event === "tool_call")
      .map((event) =>
        stringValue(event.data.skillName) ||
        stringValue(event.data.skill_name) ||
        stringValue(event.data.name) ||
        stringValue(event.data.tool_name) ||
        stringValue(event.data.tool),
      )
      .filter(Boolean);
    const normalizedToolNames = [...new Set(toolNames.map(normalizeToolName))];
    const userFacingToolNames = normalizedToolNames.filter((tool) => !INTERNAL_TOOLS.has(tool));

    console.log(`observed events=${eventNames.join(",") || "(none)"}`);
    console.log(`observed tools=${toolNames.join(",") || "(none)"}`);
    console.log(`observed user-facing tools=${userFacingToolNames.join(",") || "(none)"}`);

    const errorEvents = events.filter((event) => event.event === "error");
    expect(
      errorEvents.map((event) => stringValue(event.data.code) || stringValue(event.data.message)),
      `chat should not emit error events (status=${status}, text snippet="${text.slice(0, 200)}")`,
    ).toEqual([]);
    expect(ok, `chat should complete successfully (status=${status})`).toBe(true);
    expect(userFacingToolNames.length, "should observe at least one user-facing tool_call event").toBeGreaterThan(0);
    expect(
      userFacingToolNames.some((tool) => expectedTools.includes(tool)),
      `expected one of ${expectedTools.join(",")} in observed tools ${userFacingToolNames.join(",")}`,
    ).toBe(true);
  });
});

function normalizeToolName(name: string): string {
  return name
    .toLowerCase()
    .replace(/^mcp-tools-/, "")
    .replace(/_/g, "-")
    .replace(/^mcp-tools-/, "");
}
