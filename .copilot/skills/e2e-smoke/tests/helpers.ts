/**
 * Shared helpers + env-derived URLs used by every spec.
 *
 * No deployment endpoints are hardcoded here — this is a public repo. URLs are
 * resolved by `run.sh` from the local `azd` environment (`.azure/`, gitignored)
 * and exported as KRATOS_FRONTEND_URL / KRATOS_BACKEND_URL, or supplied
 * manually. Missing values fail fast rather than silently targeting a stale env.
 */
function requiredUrl(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(
      `${name} is not set. Run this suite via ./run.sh (which resolves endpoints ` +
        `from 'azd env get-values'), or export ${name} explicitly.`,
    );
  }
  return value.replace(/\/+$/, "");
}

export const FRONTEND_URL = requiredUrl("KRATOS_FRONTEND_URL");

export const BACKEND_URL = requiredUrl("KRATOS_BACKEND_URL");

export const USE_CASES = (process.env.KRATOS_USE_CASES || "generic")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

export const CHAT_TIMEOUT_MS = Number(process.env.CHAT_TIMEOUT_MS || 60_000);
export const TRACES_LOOKBACK_HOURS = Number(process.env.TRACES_LOOKBACK_HOURS || 6);

export type ChatEvent = {
  event: string;
  data: Record<string, unknown>;
};

/**
 * Stream-aware POST to /api/agent/chat that aggregates the SSE response into
 * a single concatenated text. The backend yields lines like:
 *   data: {"event":"content","data":{"content":"..."}}
 *   data: {"event":"done"}
 * We collect every content chunk and return the concatenated string.
 */
export async function chatOnce(
  prompt: string,
  useCase: string,
  timeoutMs = CHAT_TIMEOUT_MS,
): Promise<{ text: string; ok: boolean; status: number; events: ChatEvent[] }> {
  const conversationId = `e2e-smoke-${Date.now()}`;
  const ac = new AbortController();
  const to = setTimeout(() => ac.abort(), timeoutMs);

  try {
    const resp = await fetch(`${BACKEND_URL}/api/agent/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        message: prompt,
        useCase: useCase,
        conversationId: conversationId,
      }),
      signal: ac.signal,
    });

    if (!resp.ok || !resp.body) {
      const body = resp.body ? await resp.text() : "";
      return { text: body, ok: false, status: resp.status, events: [] };
    }

    const events = await readSseEvents(resp.body);
    let collected = "";
    for (const evt of events) {
      if (evt.event === "content") {
        collected += stringValue(evt.data.content);
      } else if (evt.event === "done") {
        return { text: collected, ok: true, status: resp.status, events };
      } else if (evt.event === "error") {
        return {
          text: collected + `\n[error: ${stringValue(evt.data.message) || "unknown"}]`,
          ok: false,
          status: resp.status,
          events,
        };
      }
    }
    return { text: collected, ok: collected.length > 0, status: resp.status, events };
  } finally {
    clearTimeout(to);
  }
}

export async function readSseEvents(
  body: ReadableStream<Uint8Array>,
): Promise<ChatEvent[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const events: ChatEvent[] = [];

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const evt = parseSseBlock(block);
      if (evt) events.push(evt);
    }
  }

  buffer += decoder.decode();
  buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const trailing = parseSseBlock(buffer);
  if (trailing) events.push(trailing);
  return events;
}

function parseSseBlock(block: string): ChatEvent | null {
  let eventName = "";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      const value = line.slice("data:".length).trim();
      if (value && value !== "[DONE]") dataLines.push(value);
    }
  }

  if (dataLines.length === 0) return null;
  const rawData = dataLines.join("\n");
  try {
    const parsed = JSON.parse(rawData) as Record<string, unknown>;
    const nestedData = parsed.data;
    if (!eventName) {
      eventName = stringValue(parsed.event) || stringValue(parsed.type);
    }
    return {
      event: eventName || "message",
      data: isRecord(nestedData) ? nestedData : parsed,
    };
  } catch {
    return { event: eventName || "message", data: { content: rawData } };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}
