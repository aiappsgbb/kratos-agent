import { getApiUrl } from "@/lib/config";
import type {
  Attachment,
  EvalScenario,
  EvalRun,
  EvalMode,
  TraceList,
  TraceOperation,
} from "@/types";

/**
 * Send a message to the agent and receive streaming SSE events.
 */
export async function streamAgentChat(
  conversationId: string,
  message: string,
  onEvent: (event: { type: string; data: unknown }) => void,
  onError: (error: Error) => void,
  onDone: () => void,
  attachments?: Attachment[],
  useCase?: string
): Promise<void> {
  try {
    const payload: Record<string, unknown> = { conversationId, message };
    if (attachments && attachments.length > 0) {
      payload.attachments = attachments;
    }
    if (useCase) {
      payload.useCase = useCase;
    }

    const response = await fetch(`${getApiUrl()}/api/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Agent request failed: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          // Ignore — we extract type from the data
          continue;
        }
        if (line.startsWith("data: ")) {
          const jsonStr = line.slice(6);
          try {
            const parsed = JSON.parse(jsonStr);
            onEvent({ type: parsed.type, data: parsed });

            if (parsed.type === "done") {
              onDone();
              return;
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    }

    onDone();
  } catch (err) {
    onError(err instanceof Error ? err : new Error(String(err)));
  }
}

/**
 * Create a new conversation.
 */
export async function createConversation(
  title: string = "New Conversation",
  useCase: string = "generic"
): Promise<{ id: string; title: string; useCase: string }> {
  const response = await fetch(`${getApiUrl()}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, useCase }),
  });

  if (!response.ok) {
    throw new Error(`Failed to create conversation: ${response.status}`);
  }

  return response.json();
}

/**
 * Respond to a user input request from the agent.
 */
export async function respondToUserInput(
  conversationId: string,
  requestId: string,
  answer: string
): Promise<void> {
  const response = await fetch(`${getApiUrl()}/api/agent/user-input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversationId, requestId, answer }),
  });
  if (!response.ok) {
    throw new Error(`Failed to respond to user input: ${response.status}`);
  }
}

/**
 * Update a conversation's title.
 */
export async function updateConversation(
  conversationId: string,
  updates: { title?: string }
): Promise<void> {
  const response = await fetch(
    `${getApiUrl()}/api/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to update conversation: ${response.status}`);
  }
}

/**
 * Delete a conversation.
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(
    `${getApiUrl()}/api/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error(`Failed to delete conversation: ${response.status}`);
  }
}

/**
 * List all conversations.
 */
export async function listConversations(): Promise<{ conversations: unknown[] }> {
  const response = await fetch(`${getApiUrl()}/api/conversations`);
  if (!response.ok) {
    throw new Error(`Failed to list conversations: ${response.status}`);
  }
  return response.json();
}

/**
 * Get messages for a conversation.
 */
export async function getConversationMessages(conversationId: string): Promise<unknown[]> {
  const response = await fetch(`${getApiUrl()}/api/conversations/${encodeURIComponent(conversationId)}/messages`);
  if (!response.ok) {
    throw new Error(`Failed to get messages: ${response.status}`);
  }
  return response.json();
}

// ─── Use Cases API ───

import type { UseCase } from "@/types";

export async function listUseCases(): Promise<UseCase[]> {
  const response = await fetch(`${getApiUrl()}/api/use-cases`);
  if (!response.ok) throw new Error(`Failed to list use-cases: ${response.status}`);
  const data = await response.json();
  return data.useCases;
}

/**
 * Download a use-case as a self-contained Foundry Hosted Agent ZIP.
 *
 * Returns the raw bytes; the caller is responsible for triggering the
 * browser download (e.g. via createObjectURL + anchor click).
 */
export async function exportUseCase(name: string): Promise<Blob> {
  const response = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(name)}/export`,
    { headers: { Accept: "application/zip" } },
  );
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Body wasn't JSON — keep the status code as the error.
    }
    throw new Error(`Failed to export use-case: ${detail}`);
  }
  return response.blob();
}

/** Result of a persona import (mirrors backend `PersonaImportResponse`). */
export interface PersonaImportResult {
  name: string;
  displayName: string;
  description: string;
  skillCount: number;
  created: boolean;
  files: string[];
}

/**
 * Import a persona from a threadlight-design-compatible manifest.
 *
 * The manifest is built by the host (e.g. agentic-loop-site) and relayed
 * same-origin via sessionStorage; here it is POSTed to the auth-gated Kratos
 * import endpoint. Returns the created persona's slug + metadata.
 */
export async function importPersona(
  manifest: unknown,
  opts: { name?: string; overwrite?: boolean; dedupe?: boolean } = {},
): Promise<PersonaImportResult> {
  const payload: Record<string, unknown> = { manifest };
  if (opts.name) payload.name = opts.name;
  if (opts.overwrite !== undefined) payload.overwrite = opts.overwrite;
  if (opts.dedupe !== undefined) payload.dedupe = opts.dedupe;

  const response = await fetch(`${getApiUrl()}/api/use-cases/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Body wasn't JSON — keep the status code as the error.
    }
    throw new Error(`Failed to import persona: ${detail}`);
  }
  return (await response.json()) as PersonaImportResult;
}

// ─── Skills Admin API ───

import type { Skill, SkillCreate, SkillUpdate } from "@/types";

export async function listSkills(useCase: string = "generic"): Promise<Skill[]> {
  const response = await fetch(`${getApiUrl()}/api/admin/skills?use_case=${encodeURIComponent(useCase)}`);
  if (!response.ok) throw new Error(`Failed to list skills: ${response.status}`);
  const data = await response.json();
  return data.skills;
}

export async function getSkill(name: string, useCase: string = "generic"): Promise<Skill> {
  const response = await fetch(`${getApiUrl()}/api/admin/skills/${encodeURIComponent(name)}?use_case=${encodeURIComponent(useCase)}`);
  if (!response.ok) throw new Error(`Failed to get skill: ${response.status}`);
  return response.json();
}

export async function createSkill(skill: SkillCreate, useCase: string = "generic"): Promise<Skill> {
  const response = await fetch(`${getApiUrl()}/api/admin/skills?use_case=${encodeURIComponent(useCase)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(skill),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create skill: ${response.status}`);
  }
  return response.json();
}

export async function updateSkill(name: string, updates: SkillUpdate, useCase: string = "generic"): Promise<Skill> {
  const response = await fetch(`${getApiUrl()}/api/admin/skills/${encodeURIComponent(name)}?use_case=${encodeURIComponent(useCase)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update skill: ${response.status}`);
  }
  return response.json();
}

export async function deleteSkill(name: string, useCase: string = "generic"): Promise<void> {
  const response = await fetch(`${getApiUrl()}/api/admin/skills/${encodeURIComponent(name)}?use_case=${encodeURIComponent(useCase)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete skill: ${response.status}`);
  }
}

// ─── Skill Files API ───

import type { SkillFile } from "@/types";

export async function listSkillFiles(skillName: string, useCase: string = "generic"): Promise<{ files: SkillFile[] }> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/skills/${encodeURIComponent(skillName)}/files?use_case=${encodeURIComponent(useCase)}`
  );
  if (!response.ok) throw new Error(`Failed to list skill files: ${response.status}`);
  return response.json();
}

export async function upsertSkillFile(
  skillName: string,
  filePath: string,
  content: string,
  useCase: string = "generic"
): Promise<void> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/skills/${encodeURIComponent(skillName)}/files/${filePath}?use_case=${encodeURIComponent(useCase)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to upload file: ${response.status}`);
  }
}

export async function deleteSkillFile(
  skillName: string,
  filePath: string,
  useCase: string = "generic"
): Promise<void> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/skills/${encodeURIComponent(skillName)}/files/${filePath}?use_case=${encodeURIComponent(useCase)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete file: ${response.status}`);
  }
}

// ─── System Prompt Admin API ───

import type { SystemPrompt } from "@/types";

export async function getSystemPrompt(useCase?: string): Promise<SystemPrompt> {
  const params = useCase ? `?use_case=${encodeURIComponent(useCase)}` : "";
  const response = await fetch(`${getApiUrl()}/api/admin/system-prompt${params}`);
  if (!response.ok) throw new Error(`Failed to get system prompt: ${response.status}`);
  return response.json();
}

export async function updateSystemPrompt(content: string, useCase?: string): Promise<SystemPrompt> {
  const params = useCase ? `?use_case=${encodeURIComponent(useCase)}` : "";
  const response = await fetch(`${getApiUrl()}/api/admin/system-prompt${params}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update system prompt: ${response.status}`);
  }
  return response.json();
}

export async function resetSystemPrompt(useCase?: string): Promise<void> {
  const params = useCase ? `?use_case=${encodeURIComponent(useCase)}` : "";
  const response = await fetch(`${getApiUrl()}/api/admin/system-prompt${params}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to reset system prompt: ${response.status}`);
  }
}

// ─── MCP Servers Admin API ───

import type { MCPConfig } from "@/types";

export async function getMCPConfig(useCase: string): Promise<MCPConfig> {
  const response = await fetch(`${getApiUrl()}/api/admin/mcp-servers?use_case=${encodeURIComponent(useCase)}`);
  if (!response.ok) throw new Error(`Failed to get MCP config: ${response.status}`);
  return response.json();
}

export async function updateMCPConfig(useCase: string, servers: MCPConfig["servers"]): Promise<MCPConfig> {
  const response = await fetch(`${getApiUrl()}/api/admin/mcp-servers?use_case=${encodeURIComponent(useCase)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ servers }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update MCP config: ${response.status}`);
  }
  return response.json();
}

// ─── Consistency Analysis API ───

import type { AnalysisResult } from "@/types";

export async function analyzeConsistency(
  useCase: string = "generic",
  includeDisabled: boolean = true
): Promise<AnalysisResult> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/analysis/consistency?use_case=${encodeURIComponent(useCase)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ includeDisabled }),
    }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Analysis failed: ${response.status}`);
  }
  return response.json();
}

import type { AnalysisIssue, ApplyFixResult } from "@/types";

// ─── APM Admin API ───

import type { ApmStatusResponse, ApmCommandResponse } from "@/types";

export async function getApmStatus(useCase: string): Promise<ApmStatusResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm`
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const detail = typeof err.detail === "string" ? err.detail : err.detail?.detail;
    throw new Error(detail || `Failed to get APM status: ${response.status}`);
  }
  return response.json();
}

async function readApmError(response: Response, fallback: string): Promise<Error> {
  const err = await response.json().catch(() => ({}));
  // APM failure payloads are { detail: string, stderr?: string, returncode?: number }
  // but FastAPI sometimes wraps object details as { detail: {...} }
  const body = (err && typeof err === "object" ? err : {}) as Record<string, unknown>;
  const detailField = body.detail;
  let message: string;
  let stderr: string | undefined;
  let returncode: number | undefined;
  if (detailField && typeof detailField === "object") {
    const d = detailField as Record<string, unknown>;
    message = (d.detail as string) ?? fallback;
    stderr = d.stderr as string | undefined;
    returncode = d.returncode as number | undefined;
  } else if (typeof detailField === "string") {
    message = detailField;
  } else {
    message = fallback;
  }
  const tail = stderr ? `\n${stderr.split("\n").slice(-10).join("\n")}` : "";
  const rc = returncode !== undefined ? ` (rc=${returncode})` : "";
  return new Error(`${message}${rc}${tail}`);
}

export async function installApmPackage(
  useCase: string,
  body: { package: string; ref?: string; dev?: boolean }
): Promise<ApmCommandResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/install`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) throw await readApmError(response, `Failed to install package: ${response.status}`);
  return response.json();
}

export async function uninstallApmPackage(
  useCase: string,
  pkg: string
): Promise<ApmCommandResponse> {
  // Backend route is DELETE /{package:path}, so slashes must be preserved.
  // Encode each segment separately to avoid %2F while still escaping special chars.
  const encodedPkg = pkg.split("/").map(encodeURIComponent).join("/");
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/${encodedPkg}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw await readApmError(response, `Failed to uninstall package: ${response.status}`);
  return response.json();
}

export async function installApmMcpServer(
  useCase: string,
  body: {
    name: string;
    transport?: "stdio" | "http" | "sse";
    command?: string;
    args?: string[];
    url?: string;
    env?: Record<string, string>;
  }
): Promise<ApmCommandResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/mcp`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) throw await readApmError(response, `Failed to install MCP server: ${response.status}`);
  return response.json();
}

export async function uninstallApmMcpServer(
  useCase: string,
  name: string
): Promise<ApmCommandResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/mcp/${encodeURIComponent(name)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw await readApmError(response, `Failed to uninstall MCP server: ${response.status}`);
  return response.json();
}

export async function syncApm(useCase: string): Promise<ApmCommandResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/sync`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }
  );
  if (!response.ok) throw await readApmError(response, `APM sync failed: ${response.status}`);
  return response.json();
}

export async function updateApm(
  useCase: string,
  body: { package?: string } = {}
): Promise<ApmCommandResponse> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/use-cases/${encodeURIComponent(useCase)}/apm/update`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) throw await readApmError(response, `APM update failed: ${response.status}`);
  return response.json();
}

export async function applyAnalysisFix(
  issue: AnalysisIssue,
  useCase: string = "generic"
): Promise<ApplyFixResult> {
  const response = await fetch(
    `${getApiUrl()}/api/admin/analysis/apply-fix?use_case=${encodeURIComponent(useCase)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category: issue.category,
        title: issue.title,
        description: issue.description,
        recommendation: issue.recommendation,
        affectedSkills: issue.affectedSkills,
      }),
    }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Apply fix failed: ${response.status}`);
  }
  return response.json();
}

// ─── Evals ─────────────────────────────────────────────────────────────────

async function readJson<T>(response: Response, errPrefix: string): Promise<T> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${errPrefix} (${response.status})${body ? `: ${body}` : ""}`);
  }
  return response.json();
}

export async function listEvalScenarios(useCase: string): Promise<EvalScenario[]> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/scenarios`,
  );
  const data = await readJson<{ scenarios: EvalScenario[] }>(r, "List scenarios failed");
  return data.scenarios ?? [];
}

export async function generateEvalScenarios(
  useCase: string,
  body: { count?: number; persist?: boolean; instructions?: string } = {},
): Promise<{ scenarios: EvalScenario[]; persisted: boolean }> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/scenarios/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 10, persist: false, instructions: "", ...body }),
    },
  );
  return readJson(r, "Generate scenarios failed");
}

export async function upsertEvalScenario(
  useCase: string,
  scenario: EvalScenario,
): Promise<EvalScenario> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/scenarios/${encodeURIComponent(scenario.name)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    },
  );
  return readJson(r, "Save scenario failed");
}

export async function deleteEvalScenario(useCase: string, name: string): Promise<void> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/scenarios/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  if (!r.ok && r.status !== 404) {
    throw new Error(`Delete scenario failed: ${r.status}`);
  }
}

export async function startEvalRun(
  useCase: string,
  body: { mode: EvalMode; scenarios?: string[] },
): Promise<EvalRun> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson(r, "Start eval run failed");
}

export async function listEvalRuns(useCase: string): Promise<EvalRun[]> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/runs`,
  );
  const data = await readJson<{ runs: EvalRun[] }>(r, "List runs failed");
  return data.runs ?? [];
}

export async function getEvalRun(useCase: string, runId: string): Promise<EvalRun> {
  const r = await fetch(
    `${getApiUrl()}/api/use-cases/${encodeURIComponent(useCase)}/evals/runs/${encodeURIComponent(runId)}`,
  );
  return readJson(r, "Get run failed");
}

// ─── Traces ────────────────────────────────────────────────────────────────

export async function listTraceOperations(filters: {
  useCase?: string;
  conversationId?: string;
  evalRunId?: string;
  lookbackHours?: number;
  maxOperations?: number;
}): Promise<TraceList> {
  const params = new URLSearchParams();
  if (filters.useCase) params.set("use_case", filters.useCase);
  if (filters.conversationId) params.set("conversation_id", filters.conversationId);
  if (filters.evalRunId) params.set("eval_run_id", filters.evalRunId);
  if (filters.lookbackHours) params.set("hours", String(filters.lookbackHours));
  if (filters.maxOperations) params.set("limit", String(filters.maxOperations));
  const qs = params.toString();
  const r = await fetch(`${getApiUrl()}/api/traces/operations${qs ? `?${qs}` : ""}`);
  return readJson(r, "List trace operations failed");
}

export async function getTraceOperation(
  operationId: string,
  lookbackHours = 168,
): Promise<TraceOperation> {
  const r = await fetch(
    `${getApiUrl()}/api/traces/operations/${encodeURIComponent(operationId)}?hours=${lookbackHours}`,
  );
  return readJson(r, "Get trace operation failed");
}
