/**
 * AG-UI glue for the Kratos agent: ids, Kratos CUSTOM events, and conversion of
 * persisted conversation history into AG-UI messages for CopilotKit.
 */
import type { Message } from "@ag-ui/core";
import type { RunStats } from "@/types";

/** The single runtime agent; the persona is chosen per run via forwardedProps.useCase. */
export const KRATOS_AGENT_ID = "kratos";

/** CUSTOM events emitted by the Kratos backend alongside the standard AG-UI stream. */
export const RUN_STATS_EVENT = "kratos.run_stats";
export const FOLLOW_UPS_EVENT = "kratos.follow_ups";

/** Frontend tool the persona skills call for approvals and clarifications. */
export const ASK_USER_TOOL = "ask_user";

interface PersistedToolCall {
  id: string;
  name: string;
  args?: string;
  result?: string | null;
}

export interface PersistedMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  metadata?: {
    runStats?: RunStats;
    agui?: { toolCalls?: PersistedToolCall[]; toolCallId?: string };
  };
}

/**
 * Rebuild the AG-UI transcript from Cosmos. Assistant turns carry their tool
 * calls (so tool cards re-render with their results); a frontend tool's answer
 * was stored as its own tool message and is restored as one.
 */
export function historyToAgui(history: PersistedMessage[]): { messages: Message[]; runStats: Record<string, RunStats> } {
  const messages: Message[] = [];
  const runStats: Record<string, RunStats> = {};
  const answered = new Set(
    history.filter((m) => m.role === "tool" && m.metadata?.agui?.toolCallId).map((m) => m.metadata!.agui!.toolCallId!),
  );

  for (const m of history) {
    if (m.role === "user") {
      messages.push({ id: m.id, role: "user", content: m.content });
    } else if (m.role === "assistant") {
      const calls = m.metadata?.agui?.toolCalls ?? [];
      messages.push({
        id: m.id,
        role: "assistant",
        content: m.content,
        ...(calls.length
          ? {
              toolCalls: calls.map((c) => ({
                id: c.id,
                type: "function" as const,
                function: { name: c.name, arguments: c.args || "{}" },
              })),
            }
          : {}),
      });
      for (const c of calls) {
        if (c.result != null && !answered.has(c.id)) {
          messages.push({ id: `result:${c.id}`, role: "tool", toolCallId: c.id, content: c.result });
        }
      }
      if (m.metadata?.runStats) runStats[m.id] = m.metadata.runStats;
    } else if (m.role === "tool" && m.metadata?.agui?.toolCallId) {
      messages.push({ id: m.id, role: "tool", toolCallId: m.metadata.agui.toolCallId, content: m.content });
    }
  }
  return { messages, runStats };
}

export function parseArgs(raw: string | undefined): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}
