"use client";

import { useState } from "react";
import type { Message, ToolMessage } from "@ag-ui/core";
import { useRenderToolCall } from "@copilotkit/react-core/v2";
import { MessageBubble } from "@/components/MessageBubble";
import type { Attachment, ChatMessage, RunStats } from "@/types";
import { formatDuration } from "@/lib/tools";

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((p) => p && typeof p === "object" && (p as { type?: string }).type === "text")
      .map((p) => (p as { text: string }).text)
      .join("\n");
  }
  return "";
}

function attachmentsOf(content: unknown): Attachment[] {
  if (!Array.isArray(content)) return [];
  return content
    .filter((p) => p && typeof p === "object" && (p as { type?: string }).type !== "text")
    .map((p, i) => {
      const part = p as { filename?: string; mimeType?: string };
      const name = part.filename || `attachment-${i + 1}`;
      return { type: "file" as const, path: name, displayName: name };
    });
}

function asBubble(m: Message, conversationId: string): ChatMessage {
  return {
    id: m.id,
    conversationId,
    role: m.role === "user" ? "user" : "assistant",
    content: textOf((m as { content?: unknown }).content),
    attachments: m.role === "user" ? attachmentsOf(m.content) : undefined,
    createdAt: "",
  };
}

function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;
  return (
    <div className="ml-11">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-text transition-colors"
      >
        <svg className={`w-3 h-3 transition-transform ${open ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
        Reasoning
      </button>
      {open && <p className="mt-1.5 pl-4 border-l border-border-soft text-xs text-muted whitespace-pre-wrap max-w-3xl">{text}</p>}
    </div>
  );
}

export function RunStatsLine({ stats }: { stats: RunStats }) {
  const parts = [
    formatDuration(stats.totalDurationMs),
    stats.timeToFirstTokenMs ? `first token ${formatDuration(stats.timeToFirstTokenMs)}` : "",
    stats.totalTokens ? `${stats.totalTokens.toLocaleString()} tokens` : "",
    stats.totalToolCalls ? `${stats.totalToolCalls} tool call${stats.totalToolCalls === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return <p className="ml-11 mt-1.5 text-[11px] text-muted tabular-nums" data-testid="run-stats">{parts.join(" · ")}</p>;
}

export function MessageList({
  messages,
  conversationId,
  runStats,
}: {
  messages: Message[];
  conversationId: string;
  runStats: Record<string, RunStats>;
}) {
  const renderToolCall = useRenderToolCall();
  const toolResults = new Map<string, ToolMessage>();
  for (const m of messages) if (m.role === "tool") toolResults.set(m.toolCallId, m);

  return (
    <>
      {messages.map((m) => {
        if (m.role === "user") {
          return (
            <div key={m.id} data-testid="user-message">
              <MessageBubble message={asBubble(m, conversationId)} />
            </div>
          );
        }
        if (m.role === "reasoning") {
          return <Reasoning key={m.id} text={textOf(m.content)} />;
        }
        if (m.role !== "assistant") return null;

        const text = textOf(m.content);
        const calls = m.toolCalls ?? [];
        return (
          <div key={m.id} className="space-y-2">
            {text && (
              <div data-testid="assistant-message">
                <MessageBubble message={asBubble(m, conversationId)} />
              </div>
            )}
            {calls.length > 0 && (
              <div className="ml-11 flex flex-wrap gap-1.5 items-start">
                {calls.map((call) => (
                  <div key={call.id} className="contents">
                    {renderToolCall({ toolCall: call, toolMessage: toolResults.get(call.id) })}
                  </div>
                ))}
              </div>
            )}
            {runStats[m.id] && <RunStatsLine stats={runStats[m.id]} />}
          </div>
        );
      })}
    </>
  );
}
