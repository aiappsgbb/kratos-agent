/**
 * Naming, classification and formatting for the tools a Kratos agent calls:
 * markdown skills, MCP server tools and runtime built-ins.
 */

/** Reserved names that come from the SDK / Copilot runtime rather than a skill or MCP server. */
const BUILTIN_NAMES = new Set([
  "skill",
  "report_intent",
  "code_interpreter",
  "web_search",
  "web_fetch",
  "think",
  "task",
  "bash",
  "read_bash",
  "write_bash",
  "stop_bash",
  "list_bash",
  "view",
  "create",
  "edit",
  "glob",
  "grep",
  "tool_search_tool",
]);

export type ToolKind = "mcp" | "skill" | "builtin";

export function prettyToolName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Resolve the generic `skill` meta-tool to the skill it invoked. */
export function resolveSkillName(name: string, args?: unknown, result?: string): string {
  if (name !== "skill") return name;
  if (args && typeof args === "object") {
    const a = args as Record<string, unknown>;
    const named = a.skill ?? a.name ?? a.skillName;
    if (typeof named === "string" && named) return named;
  }
  const outputMatch = result?.match(/Skill ["']([^"']+)["']/);
  if (outputMatch) return outputMatch[1];
  return name;
}

/** Classify a tool call by where it came from.
 *  - MCP server tool:   "<server>-<server>_<verb>" or "<server>-<verb>_<noun>"
 *  - Skill (markdown):  "account-briefing" (kebab-case folder name, no underscores)
 *  - Built-in:          reserved runtime names, or snake_case without a server prefix
 */
export function classifyTool(rawName: string): ToolKind {
  const name = rawName.toLowerCase();
  if (BUILTIN_NAMES.has(name)) return "builtin";
  if (name.includes("-")) {
    const afterDash = name.slice(name.indexOf("-") + 1);
    return afterDash.includes("_") ? "mcp" : "skill";
  }
  return name.includes("_") ? "builtin" : "skill";
}

/** Human label: salesforce-salesforce_search_accounts_by_name → "Salesforce · Search Accounts". */
export function formatToolLabel(rawName: string): string {
  if (BUILTIN_NAMES.has(rawName.toLowerCase())) return prettyToolName(rawName);
  // Skills are kebab-case folder names: account-briefing → "Account Briefing".
  if (classifyTool(rawName) === "skill") return prettyToolName(rawName.replace(/-/g, "_"));
  if (rawName.includes("-")) {
    // "<server>-<tool>": the server name may itself contain dashes
    // (fabric-iq-fabric_iq_get_oee), so prefer the split whose tool part
    // repeats the server name, as MCP tool names usually do.
    let dash = rawName.indexOf("-");
    for (let i = dash; i !== -1; i = rawName.indexOf("-", i + 1)) {
      const candidate = rawName.slice(0, i).toLowerCase().replace(/-/g, "_");
      if (rawName.slice(i + 1).toLowerCase().startsWith(`${candidate}_`)) {
        dash = i;
        break;
      }
    }
    const server = rawName.slice(0, dash);
    let rest = rawName.slice(dash + 1);
    const dupePrefix = `${server.replace(/-/g, "_")}_`;
    if (rest.toLowerCase().startsWith(dupePrefix.toLowerCase())) rest = rest.slice(dupePrefix.length);
    rest = rest.replace(/_by_[a-z]+$/i, "");
    return `${prettyToolName(server.replace(/-/g, "_"))} · ${prettyToolName(rest)}`;
  }
  return prettyToolName(rawName);
}

export const KIND_STYLES: Record<ToolKind, { chip: string; dot: string; label: string }> = {
  mcp: {
    chip: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/[0.08] dark:text-sky-300 dark:border-sky-500/30",
    dot: "bg-sky-500",
    label: "MCP",
  },
  skill: {
    chip: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/[0.08] dark:text-violet-300 dark:border-violet-500/30",
    dot: "bg-violet-500",
    label: "Skill",
  },
  builtin: {
    chip: "bg-slate-100 text-slate-600 border-slate-200 dark:bg-white/[0.05] dark:text-slate-300 dark:border-white/[0.08]",
    dot: "bg-slate-400",
    label: "Built-in",
  },
};

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

/** Make raw tool input/output readable: unwrap SDK Result(...) reprs, pretty-print JSON. */
export function formatToolText(raw: string): string {
  let text = raw.trim();
  const resultMatch = text.match(/^Result\(content=['"]([\s\S]*?)['"],\s*contents=/);
  if (resultMatch) {
    text = resultMatch[1].replace(/\\n/g, "\n").replace(/\\t/g, "\t").replace(/\\'/g, "'").replace(/\\"/g, '"');
  }
  if (!text || text === "None" || text === "null") return raw;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed === "object" && parsed !== null) {
      if (typeof parsed.text === "string") return parsed.text;
      return JSON.stringify(parsed, null, 2);
    }
  } catch {
    // not JSON
  }
  return text;
}
