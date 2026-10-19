"use client";

import { useState } from "react";
import { SourceBadge } from "@/components/SourceBadge";
import { KIND_STYLES, classifyTool, formatToolLabel, formatToolText, resolveSkillName } from "@/lib/tools";

export interface ToolCallChipProps {
  name: string;
  toolCallId: string;
  args?: unknown;
  status: string;
  result?: string;
  source?: string;
}

/**
 * Compact, expandable card for one backend tool call (skill, MCP tool or
 * built-in). Registered as CopilotKit's wildcard tool renderer, so every tool
 * the agent calls renders here, live, with its arguments and result.
 */
export function ToolCallChip({ name, toolCallId, args, status, result, source }: ToolCallChipProps) {
  const [open, setOpen] = useState(false);
  const display = resolveSkillName(name, args, result);
  const kind = classifyTool(display);
  const style = KIND_STYLES[kind];
  const running = status !== "complete";
  const argText = args && typeof args === "object" && Object.keys(args as object).length ? JSON.stringify(args, null, 2) : "";

  return (
    <div className="inline-block max-w-full align-top" data-testid="tool-call" data-tool={display} data-status={running ? "running" : "complete"}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`tool-${toolCallId}`}
        title={`${style.label} · ${display}`}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all duration-200 hover:shadow-sm ${
          running ? "bg-accent-soft text-accent border-accent" : style.chip
        }`}
      >
        {running ? (
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
          </span>
        ) : (
          <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
        )}
        <span className="opacity-60 uppercase tracking-wide text-[9px]">{style.label}</span>
        {formatToolLabel(display)}
        <SourceBadge source={source} />
        <svg className={`w-3 h-3 opacity-50 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
      {open && (
        <div id={`tool-${toolCallId}`} className="mt-1.5 rounded-xl border border-border-soft bg-surface-2 p-3 text-[11px] font-mono text-muted space-y-2 max-w-2xl animate-fade-in">
          {argText && (
            <div>
              <div className="uppercase tracking-wider text-[9px] font-sans font-semibold text-text-strong mb-1">Input</div>
              <pre className="whitespace-pre-wrap break-words max-h-48 overflow-auto">{argText}</pre>
            </div>
          )}
          <div>
            <div className="uppercase tracking-wider text-[9px] font-sans font-semibold text-text-strong mb-1">Result</div>
            <pre className="whitespace-pre-wrap break-words max-h-64 overflow-auto">
              {running ? "Running…" : formatToolText(result || "") || "(empty)"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
