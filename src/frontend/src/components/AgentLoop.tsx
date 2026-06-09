"use client";

import { useState, useCallback, useEffect, useRef } from "react";

/* ─── Step data ──────────────────────────────────────────────────── */

interface Step {
  id: number;
  label: string;
  title: string;
  source: string;
  description: string;
  detail: string;
  icon: React.ReactNode;
  layer: "frontend" | "backend" | "sdk" | "azure";
  isLoop?: boolean;
  visualization: React.ReactNode;
}

const LAYER_COLORS = {
  frontend: {
    dot: "bg-cyan-400",
    badge: "bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-400/10 dark:text-cyan-400 dark:border-cyan-400/20",
    ring: "ring-cyan-400/30",
    text: "text-cyan-600 dark:text-cyan-400",
  },
  backend: {
    dot: "bg-primary-400",
    badge: "bg-primary-50 text-primary-700 border-primary-200 dark:bg-primary-400/10 dark:text-primary-400 dark:border-primary-400/20",
    ring: "ring-primary-400/30",
    text: "text-primary-600 dark:text-primary-400",
  },
  sdk: {
    dot: "bg-violet-400",
    badge: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-400/10 dark:text-violet-400 dark:border-violet-400/20",
    ring: "ring-violet-400/30",
    text: "text-violet-600 dark:text-violet-400",
  },
  azure: {
    dot: "bg-accent-400",
    badge: "bg-accent-50 text-accent-700 border-accent-200 dark:bg-accent-400/10 dark:text-accent-400 dark:border-accent-400/20",
    ring: "ring-accent-400/30",
    text: "text-accent-600 dark:text-accent-400",
  },
} as const;

const LAYER_LABELS: Record<string, string> = {
  frontend: "Frontend",
  backend: "Backend",
  sdk: "Copilot SDK",
  azure: "Azure",
};

/* ─── Loop step indices (0-indexed) ──────────────────────────────── */
const LOOP_START = 8;  // Step 9: Tool Decision
const LOOP_END = 10;   // Step 11: Agentic Loop

/* ─── Step Visualization Components ──────────────────────────────── */

function VizChatInput() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-sm" role="img" aria-label="Chat input visualization">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-3 h-3 rounded-full bg-red-500/80" />
        <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
        <span className="w-3 h-3 rounded-full bg-green-500/80" />
        <span className="ml-2 text-xs text-muted">Kratos Agent</span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-muted">
          <span className="text-cyan-400 text-xs font-semibold px-1.5 py-0.5 rounded bg-cyan-400/10">[user]</span>
          <span className="text-text-strong">Analyze my portfolio performance and draft a summary email</span>
        </div>
        <div className="flex items-start gap-2 text-muted">
          <span className="text-cyan-400/60 text-xs font-semibold px-1.5 py-0.5 rounded bg-cyan-400/5 mt-0.5">📎</span>
          <span className="text-muted text-xs">portfolio_q4.xlsx <span className="text-text">(base64, 142 KB)</span></span>
        </div>
      </div>
    </div>
  );
}

function VizApiRequest() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="API request visualization">
      <div className="mb-2">
        <span className="text-green-400 font-bold">POST</span>{" "}
        <span className="text-text-strong">/chat</span>{" "}
        <span className="text-text">HTTP/1.1</span>
      </div>
      <div className="text-muted mb-3">
        <div>Content-Type: <span className="text-muted">text/event-stream</span></div>
        <div>Connection: <span className="text-muted">keep-alive</span></div>
      </div>
      <div className="border-t border-border pt-2 space-y-1">
        <div className="text-accent">{"{"}</div>
        <div className="pl-4"><span className="text-accent">&quot;message&quot;</span>: <span className="text-amber-300">&quot;Analyze my portfolio...&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;conversationId&quot;</span>: <span className="text-amber-300">&quot;c9f2e...&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;useCase&quot;</span>: <span className="text-amber-300">&quot;wealth-management&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;attachments&quot;</span>: [<span className="text-muted">...</span>]</div>
        <div className="text-accent">{"}"}</div>
      </div>
    </div>
  );
}

function VizCosmosWrite() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Cosmos DB write visualization">
      <div className="flex items-center gap-2 mb-3">
        <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
        </svg>
        <span className="text-accent font-semibold text-xs">Cosmos DB — Write-Ahead</span>
      </div>
      <div className="space-y-1">
        <div className="text-muted">container: <span className="text-text-strong">messages</span></div>
        <div className="text-muted">partition: <span className="text-amber-300">&quot;c9f2e...&quot;</span></div>
        <div className="border-t border-border my-2" />
        <div className="text-accent">{"{"}</div>
        <div className="pl-4"><span className="text-accent">&quot;id&quot;</span>: <span className="text-amber-300">&quot;a7b3f...&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;role&quot;</span>: <span className="text-amber-300">&quot;user&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;content&quot;</span>: <span className="text-amber-300">&quot;Analyze my portfolio...&quot;</span>,</div>
        <div className="pl-4"><span className="text-accent">&quot;timestamp&quot;</span>: <span className="text-amber-300">&quot;2025-07-14T09:32:01Z&quot;</span></div>
        <div className="text-accent">{"}"}</div>
      </div>
      <div className="mt-2 text-green-400 text-xs flex items-center gap-1">
        <span>✓</span> Persisted before AI processing
      </div>
    </div>
  );
}

function VizSessionResolve() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Session resolution visualization">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex-1 rounded-lg bg-accent border border-violet-500/20 p-2.5 text-center">
            <div className="text-accent font-semibold text-[10px] uppercase tracking-wide mb-1">conversation_id</div>
            <div className="text-text-strong">c9f2e-4a1b</div>
          </div>
          <div className="text-muted text-lg">→</div>
          <div className="flex-1 rounded-lg bg-accent border border-violet-500/20 p-2.5 text-center">
            <div className="text-accent font-semibold text-[10px] uppercase tracking-wide mb-1">sdk_session_id</div>
            <div className="text-text-strong">sess_8x7k2</div>
          </div>
        </div>
        <div className="border-t border-border pt-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <span className="text-green-400">Existing session found — resuming multi-turn context</span>
          </div>
        </div>
        <div className="text-text text-[10px]">Auth: ManagedIdentityCredential → AzureCLICredential chain</div>
      </div>
    </div>
  );
}

function VizSystemPrompt() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="System prompt assembly visualization">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-amber-400">📄</span>
        <span className="text-muted">Blob Storage</span>
        <span className="text-text">/</span>
        <span className="text-amber-300">wealth-management</span>
        <span className="text-text">/</span>
        <span className="text-text-strong">SYSTEM_PROMPT.md</span>
      </div>
      <div className="rounded-lg bg-slate-900 border border-border p-3 space-y-1.5">
        <div className="text-accent font-semibold text-[10px] uppercase tracking-wide">System Prompt</div>
        <div className="text-text-strong">You are a wealth management advisor AI assistant.</div>
        <div className="text-text-strong">You have access to portfolio analysis tools,</div>
        <div className="text-text-strong">market data, and document generation.</div>
        <div className="text-muted mt-2">Always prefer tool usage over guessing.</div>
        <div className="text-muted">Never fabricate financial data.</div>
      </div>
      <div className="mt-2 flex items-center gap-2 text-muted text-[10px]">
        <span className="text-accent">mode=&apos;replace&apos;</span>
        <span>•</span>
        <span>YAML frontmatter stripped</span>
      </div>
    </div>
  );
}

function VizSkillRegistry() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 text-xs" role="img" aria-label="Skill registry visualization">
      <div className="flex items-center gap-2 mb-3 font-mono">
        <span className="text-accent font-semibold">skills.yaml</span>
        <span className="text-text">→</span>
        <span className="text-muted">wealth-management</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {[
          { name: "web-search", icon: "🔍", active: true },
          { name: "rag-search", icon: "📚", active: true },
          { name: "code-interpreter", icon: "🐍", active: true },
          { name: "data-analysis", icon: "📊", active: true },
          { name: "email-draft", icon: "✉️", active: true },
          { name: "portfolio-review", icon: "💼", active: true },
          { name: "document-summary", icon: "📝", active: true },
          { name: "pdf-report", icon: "📄", active: true },
          { name: "file-sharing", icon: "📁", active: false },
        ].map((skill) => (
          <div
            key={skill.name}
            className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg border font-mono ${
              skill.active
                ? "bg-primary-400/5 border-primary-400/20 text-primary-300"
                : "bg-slate-900 border-slate-800 text-slate-600"
            }`}
          >
            <span className="text-sm">{skill.icon}</span>
            <span className="truncate">{skill.name}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 font-mono text-muted text-[10px]">
        Each skill: <span className="text-accent">@define_tool</span> async function + OpenTelemetry span
      </div>
    </div>
  );
}

function VizSendToSdk() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="SDK dispatch visualization">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="rounded-lg bg-accent border border-accent px-3 py-2 text-center">
            <div className="text-accent font-semibold text-[10px] uppercase tracking-wide">FastAPI</div>
            <div className="text-muted text-[10px]">Backend</div>
          </div>
          <div className="flex-1 px-3 flex flex-col items-center">
            <div className="text-accent text-[10px] mb-1">session.send()</div>
            <div className="w-full h-[1px] bg-accent relative">
              <div className="absolute right-0 -top-1 text-accent">▶</div>
            </div>
            <div className="text-text text-[10px] mt-1">message + attachments</div>
          </div>
          <div className="rounded-lg bg-accent border border-violet-400/20 px-3 py-2 text-center">
            <div className="text-accent font-semibold text-[10px] uppercase tracking-wide">Copilot SDK</div>
            <div className="text-muted text-[10px]">Session</div>
          </div>
        </div>
        <div className="border-t border-border pt-2 text-muted">
          <div>on_event callback → asyncio.Queue → SSE generator</div>
          <div className="text-text mt-1">Registered once per session, captures all SDK events</div>
        </div>
      </div>
    </div>
  );
}

function VizModelInference() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Model inference visualization">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="rounded-lg bg-accent border border-violet-400/20 px-3 py-2 text-center">
            <div className="text-accent font-semibold text-[10px]">Copilot SDK</div>
          </div>
          <div className="flex-1 px-2 flex flex-col items-center">
            <div className="w-full h-[1px] bg-accent to-accent-400 relative">
              <div className="absolute right-0 -top-1 text-accent-400">▶</div>
            </div>
            <div className="text-text text-[10px] mt-0.5 flex items-center gap-1">
              <svg className="w-3 h-3 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Managed Identity — keyless
            </div>
          </div>
          <div className="rounded-lg bg-accent-400/10 border border-accent-400/20 px-3 py-2 text-center">
            <div className="text-accent-400 font-semibold text-[10px]">Azure OpenAI</div>
            <div className="text-muted text-[10px]">GPT-4o</div>
          </div>
        </div>
        <div className="rounded-lg bg-slate-900 border border-border p-2.5 space-y-1">
          <div className="text-accent-400 text-[10px] font-semibold uppercase tracking-wide">Streaming Response</div>
          <div className="text-muted">
            data: {`{"type":"content_block_delta","delta":{"text":"I'll analyze"}}`}
          </div>
          <div className="text-muted">
            data: {`{"type":"content_block_delta","delta":{"text":" your Q4 portfolio"}}`}
          </div>
          <div className="text-text">
            data: {`{"type":"content_block_delta","delta":{"text":"..."}}`}
          </div>
        </div>
      </div>
    </div>
  );
}

function VizToolDecision() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Tool decision visualization">
      <div className="space-y-3">
        <div className="rounded-lg bg-slate-900 border border-border p-3">
          <div className="text-text-strong mb-2">I&apos;ll analyze your portfolio data. Let me use the data analysis tool...</div>
          <div className="rounded-lg bg-accent border border-violet-400/20 p-2.5 space-y-1">
            <div className="text-accent font-semibold">tool_use:</div>
            <div className="pl-3 text-text-strong">name: <span className="text-amber-300">&quot;data_analysis&quot;</span></div>
            <div className="pl-3 text-text-strong">input: <span className="text-amber-300">&quot;Analyze portfolio_q4.xlsx — returns, risk metrics&quot;</span></div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-green-400">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>Tool registered and available — executing</span>
        </div>
      </div>
    </div>
  );
}

function VizToolExecution() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Tool execution visualization">
      <div className="space-y-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            <span className="text-green-400 font-semibold">data_analysis</span>
            <span className="text-text">— execution_start</span>
          </div>
          <div className="rounded-lg bg-slate-900 border border-border p-2.5 ml-4">
            <div className="text-muted text-[10px] mb-1">OpenTelemetry span: gen_ai.tool.name=data_analysis</div>
            <div className="text-text-strong">Analyzing portfolio_q4.xlsx...</div>
            <div className="text-text-strong mt-1">Total return: <span className="text-green-400">+12.4%</span></div>
            <div className="text-text-strong">Sharpe ratio: <span className="text-amber-300">1.82</span></div>
            <div className="text-text-strong">Max drawdown: <span className="text-red-400">-6.1%</span></div>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            <span className="text-green-400">execution_complete</span>
            <span className="text-text">— 1.2s</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function VizAgenticLoop() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Agentic loop visualization">
      <div className="space-y-2">
        {[
          { iteration: 1, tool: "data_analysis", result: "Portfolio metrics computed", status: "complete" as const },
          { iteration: 2, tool: "web_search", result: "Market benchmark data retrieved", status: "complete" as const },
          { iteration: 3, tool: "email_draft", result: "Summary email generated", status: "active" as const },
        ].map((iter) => (
          <div key={iter.iteration} className={`flex items-center gap-3 rounded-lg p-2 ${iter.status === "active" ? "bg-primary-400/5 border border-primary-400/20" : "bg-slate-900/50"}`}>
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
              iter.status === "active" ? "bg-primary-400/20 text-primary-400" : "bg-slate-800 text-slate-500"
            }`}>
              {iter.iteration}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={iter.status === "active" ? "text-primary-300" : "text-slate-400"}>{iter.tool}</span>
                <span className="text-text">→</span>
                <span className="text-muted truncate">{iter.result}</span>
              </div>
            </div>
            {iter.status === "active" ? (
              <div className="flex items-center gap-1 text-accent">
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.012 4.356v4.992" />
                </svg>
              </div>
            ) : (
              <span className="text-green-500 text-[10px]">✓</span>
            )}
          </div>
        ))}
        <div className="flex items-center gap-2 pt-1 text-text">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.012 4.356v4.992" />
          </svg>
          <span>Loop until model emits final text without tool_call blocks</span>
        </div>
      </div>
    </div>
  );
}

function VizSseStream() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="SSE event stream visualization">
      <div className="space-y-1.5">
        {[
          { type: "ThoughtEvent", data: '"Analyzing portfolio data against benchmarks..."', color: "text-violet-400", bg: "bg-violet-400/5" },
          { type: "ToolCallEvent", data: '"data_analysis — started"', color: "text-amber-400", bg: "bg-amber-400/5" },
          { type: "ToolCallEvent", data: '"data_analysis — completed (1.2s)"', color: "text-green-400", bg: "bg-green-400/5" },
          { type: "ContentEvent", data: '"## Q4 Portfolio Summary\\n\\nYour portfolio..."', color: "text-primary-400", bg: "bg-primary-400/5" },
          { type: "ContentEvent", data: '"returned **+12.4%** with a Sharpe ratio of..."', color: "text-primary-400", bg: "bg-primary-400/5" },
          { type: "UsageEvent", data: '"prompt: 2,847 | completion: 1,203 | reasoning: 456"', color: "text-slate-400", bg: "bg-slate-400/5" },
        ].map((evt, i) => (
          <div key={i} className={`flex items-start gap-2 rounded-lg px-2 py-1 ${evt.bg}`}>
            <span className={`${evt.color} whitespace-nowrap font-semibold`}>event:</span>
            <span className="text-muted whitespace-nowrap">{evt.type}</span>
            <span className="text-text truncate">{evt.data}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 text-text text-[10px]">Real-time delivery via Server-Sent Events — single HTTP connection</div>
    </div>
  );
}

function VizComplete() {
  return (
    <div className="rounded-xl bg-slate-950 p-4 font-mono text-xs" role="img" aria-label="Completion visualization">
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-green-400 font-semibold">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          session.idle
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Save Response", detail: "→ Cosmos DB", icon: "💾", done: true },
            { label: "Token Metrics", detail: "→ App Insights", icon: "📊", done: true },
            { label: "Follow-ups", detail: "→ LLM call", icon: "💡", done: true },
          ].map((task) => (
            <div
              key={task.label}
              className="rounded-lg bg-slate-900 border border-border p-2.5 text-center"
            >
              <div className="text-lg mb-1">{task.icon}</div>
              <div className="text-text-strong font-semibold text-[10px]">{task.label}</div>
              <div className="text-text text-[10px]">{task.detail}</div>
              {task.done && <div className="text-green-400 text-[10px] mt-1">✓ done</div>}
            </div>
          ))}
        </div>
        <div className="border-t border-border pt-2 flex items-center gap-3 text-muted text-[10px]">
          <span>OpenTelemetry: <span className="text-accent">operation_duration</span>, <span className="text-accent">token_usage</span></span>
        </div>
      </div>
    </div>
  );
}

/* SVG icon helpers — small, inline, no dependencies */
const Icons = {
  chat: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.068.157 2.148.279 3.238.364.466.037.893.281 1.153.671L12 21l2.652-3.978c.26-.39.687-.634 1.153-.671 1.09-.086 2.17-.207 3.238-.364 1.584-.233 2.707-1.627 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
    </svg>
  ),
  api: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
    </svg>
  ),
  db: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75" />
    </svg>
  ),
  session: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
    </svg>
  ),
  prompt: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  ),
  skills: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17l-5.34-3.08a.75.75 0 010-1.298l5.34-3.08a2.25 2.25 0 012.16 0l5.34 3.08a.75.75 0 010 1.298l-5.34 3.08a2.25 2.25 0 01-2.16 0zM4.5 14.25l7.5 4.33 7.5-4.33" />
    </svg>
  ),
  send: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
    </svg>
  ),
  model: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
    </svg>
  ),
  tools: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
    </svg>
  ),
  execute: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 9.75L16.5 12l-2.25 2.25m-4.5 0L7.5 12l2.25-2.25M6 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25z" />
    </svg>
  ),
  loop: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.012 4.356v4.992" />
    </svg>
  ),
  stream: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
    </svg>
  ),
  done: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
};

const STEPS: Step[] = [
  {
    id: 1,
    label: "Input",
    title: "User Input",
    source: "src/components/ChatWindow.tsx",
    icon: Icons.chat,
    layer: "frontend",
    visualization: <VizChatInput />,
    description:
      "User types a message in the chat UI. File attachments are base64-encoded and bundled with the prompt.",
    detail:
      "The ChatWindow component captures text via a controlled input and any uploaded files through a hidden file input. On submit, it creates a user ChatMessage, adds it to local state, then calls streamAgentChat() which opens an SSE connection to POST /chat. The component also handles auto-titling on the first message of a conversation.",
  },
  {
    id: 2,
    label: "API",
    title: "POST /chat (SSE)",
    source: "app/routers/agent.py",
    icon: Icons.api,
    layer: "backend",
    visualization: <VizApiRequest />,
    description:
      "FastAPI receives the request and opens a Server-Sent Events stream. This single HTTP connection carries all events back to the browser.",
    detail:
      "The agent router validates the AgentRequest body (message, conversationId, useCase, attachments). It sets up an EventSourceResponse with an async generator. File attachments are decoded from base64, written to temp files, and converted to SDK format. The SSE stream stays open until session.idle fires.",
  },
  {
    id: 3,
    label: "Persist",
    title: "Save to Cosmos DB",
    source: "app/services/cosmos_service.py",
    icon: Icons.db,
    layer: "backend",
    visualization: <VizCosmosWrite />,
    description:
      "The user message is persisted to Azure Cosmos DB before any AI processing begins — a write-ahead pattern that prevents data loss even if the model call fails.",
    detail:
      "Messages are stored in the 'messages' container with conversationId as the partition key. Each message gets a UUID and UTC timestamp. This write-ahead pattern means the conversation history is always recoverable. The assistant response is also saved after the full turn completes.",
  },
  {
    id: 4,
    label: "Session",
    title: "Resolve SDK Session",
    source: "app/services/copilot_agent.py",
    icon: Icons.session,
    layer: "sdk",
    visualization: <VizSessionResolve />,
    description:
      "Resolve or create a Copilot SDK session. Existing sessions are resumed from Cosmos DB to preserve multi-turn context without re-sending history.",
    detail:
      "Session IDs are mapped conversation_id → sdk_session_id in Cosmos. Resuming a session means the SDK reconnects to the same server-side context, preserving the full conversation history without re-sending it. New sessions are created with the configured model, tools, skill directories, MCP servers, and a custom system prompt. Auth uses ManagedIdentityCredential → AzureCLICredential chain.",
  },
  {
    id: 5,
    label: "Prompt",
    title: "System Prompt Assembly",
    source: "app/services/skill_registry.py",
    icon: Icons.prompt,
    layer: "backend",
    visualization: <VizSystemPrompt />,
    description:
      "The use-case-specific system prompt is loaded from Blob Storage. Each persona (generic, retail-banking, wealth-management, etc.) has its own SYSTEM_PROMPT.md.",
    detail:
      "The registry reads SYSTEM_PROMPT.md from the use-case's blob container, strips any YAML frontmatter, and passes the body as the session's system message with mode='replace'. A fallback default prompt is stored in Cosmos DB settings and used only when no use-case-specific prompt is found. The prompt instructs the model to always prefer tool usage over guessing.",
  },
  {
    id: 6,
    label: "Skills",
    title: "Skill & Tool Registry",
    source: "app/services/skill_tools.py",
    icon: Icons.skills,
    layer: "backend",
    visualization: <VizSkillRegistry />,
    description:
      "Skill names and descriptions (from SKILL.md frontmatter) are always sent to the LLM. The model decides which skill to fully load into context by calling the SDK's built-in skill tool on demand.",
    detail:
      "Each use-case has a skills/ directory of SKILL.md markdown files with YAML frontmatter (name, description, enabled). The SkillRegistry loads these per use-case and passes the skill directories to the Copilot SDK session. The SDK exposes skill names and descriptions to the LLM, which then invokes the skill tool to pull the full markdown instructions into context when needed. Backing implementations live as @define_tool functions in skill_tools.py.",
  },
  {
    id: 7,
    label: "Send",
    title: "Dispatch to SDK",
    source: "copilot_agent.py → session.send()",
    icon: Icons.send,
    layer: "sdk",
    visualization: <VizSendToSdk />,
    description:
      "The user message and file attachments are dispatched to the Copilot SDK session via session.send(). The SDK handles the full conversation lifecycle from here.",
    detail:
      "session.send() transmits the message payload. The SDK manages context windowing, token limits, and conversation threading. A synchronous on_event callback is registered on the session (once per session, not per turn) to capture all SDK events and route them to an asyncio.Queue for the SSE generator.",
  },
  {
    id: 8,
    label: "Model",
    title: "Model Inference",
    source: "Azure OpenAI via Foundry",
    icon: Icons.model,
    layer: "azure",
    visualization: <VizModelInference />,
    description:
      "The Copilot SDK streams the request to Microsoft Foundry via Managed Identity. No API keys stored or transmitted — auth is fully keyless.",
    detail:
      "The SDK constructs a chat completions request with the full context: system prompt, conversation history, available tool definitions. The provider config points to your Foundry endpoint with Azure AD token authentication (ManagedIdentityCredential → AzureCLICredential chain). The model deployment is configurable (defaults to gpt-54). Responses stream back as token deltas through the Foundry endpoint.",
  },
  {
    id: 9,
    label: "Tools?",
    title: "Tool Decision",
    source: "Copilot SDK (internal)",
    icon: Icons.tools,
    layer: "sdk",
    isLoop: true,
    visualization: <VizToolDecision />,
    description:
      "The model examines the request against available tools. If tool_use blocks are detected, the SDK dispatches execution events. Otherwise, text streams directly.",
    detail:
      "The model's response may contain tool_use content blocks alongside or instead of text. The SDK detects these and dispatches tool.execution_start events for each. If no tools are called, the response flows directly to streaming deltas. This is the entry point of the agentic loop — the model can call multiple tools in sequence or parallel.",
  },
  {
    id: 10,
    label: "Execute",
    title: "Tool Execution",
    source: "app/services/skill_tools.py",
    icon: Icons.execute,
    layer: "backend",
    isLoop: true,
    visualization: <VizToolExecution />,
    description:
      "Skills execute asynchronously with OpenTelemetry tracing: web search, RAG, code interpreter, email drafts, document summaries, data analysis, and more.",
    detail:
      "Each skill runs with its own OpenTelemetry span (gen_ai.tool.name, gen_ai.tool.call.id). Skills can make authenticated Azure API calls via DefaultAzureCredential and return structured results. The code interpreter runs Python in a sandboxed subprocess with a 30-second timeout. The SDK captures tool outputs and feeds them back to the model.",
  },
  {
    id: 11,
    label: "Loop",
    title: "Agentic Loop",
    source: "Copilot SDK session",
    icon: Icons.loop,
    layer: "sdk",
    isLoop: true,
    visualization: <VizAgenticLoop />,
    description:
      "Tool results are fed back to the model. It reasons over outputs and may call additional tools. This loop repeats until the model produces a final text answer.",
    detail:
      "This is the core agentic pattern. Each iteration generates execution_start → execution_complete event pairs. The model can chain tools (e.g. search → analyze → draft email), run the same tool with refined queries, or decide it has enough information to respond. The loop exits when the model emits a text response without further tool_call blocks. The session.idle event signals completion.",
  },
  {
    id: 12,
    label: "Stream",
    title: "SSE Event Stream",
    source: "app/routers/agent.py",
    icon: Icons.stream,
    layer: "backend",
    visualization: <VizSseStream />,
    description:
      "Events stream to the frontend in real-time: thoughts, tool call status, content deltas, and usage metrics — all over a single SSE connection.",
    detail:
      "The on_event callback translates SDK events into typed SSE events: ThoughtEvent (agent reasoning), ToolCallEvent (started/completed/failed with skill name and duration), ContentEvent (streaming text deltas), UsageEvent (token counts), and UserInputRequestEvent (when the agent asks the user a question). The frontend ThoughtChain and MessageBubble components render these in real-time.",
  },
  {
    id: 13,
    label: "Done",
    title: "Complete & Persist",
    source: "session.idle event",
    icon: Icons.done,
    layer: "backend",
    visualization: <VizComplete />,
    description:
      "The session goes idle. The full assistant response is saved to Cosmos DB, token usage is recorded to Application Insights, and follow-up questions are generated.",
    detail:
      "On session.idle, orphaned tool spans are closed, token counts (prompt, completion, reasoning) are aggregated and emitted as a final DoneEvent, the assistant message is persisted to Cosmos DB, and an optional LLM call generates contextual follow-up questions. OpenTelemetry metrics (operation_duration, token_usage) are recorded for monitoring in Application Insights.",
  },
];

/* ─── Component ──────────────────────────────────────────────────── */

export default function AgentLoop({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [activeStep, setActiveStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const step = STEPS[activeStep];
  const colors = LAYER_COLORS[step.layer];

  const goTo = useCallback((i: number) => {
    setActiveStep(i);
  }, []);

  // Auto-play
  const play = useCallback(() => {
    if (isPlaying) {
      if (timerRef.current) clearInterval(timerRef.current);
      setIsPlaying(false);
      return;
    }
    setIsPlaying(true);
    setActiveStep(0);
    let i = 0;
    timerRef.current = setInterval(() => {
      i++;
      if (i >= STEPS.length) {
        if (timerRef.current) clearInterval(timerRef.current);
        setIsPlaying(false);
        return;
      }
      setActiveStep(i);
    }, 3000);
  }, [isPlaying]);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  // Scroll card into view on mobile when step changes
  useEffect(() => {
    if (open) cardRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeStep, open]);

  // Keyboard navigation: Escape to close, Arrow keys to navigate
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (isPlaying) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        setActiveStep((s) => Math.min(s + 1, STEPS.length - 1));
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        setActiveStep((s) => Math.max(s - 1, 0));
      }
      if (e.key === " ") {
        e.preventDefault();
        play();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose, isPlaying, play]);

  // Stop autoplay when closing
  useEffect(() => {
    if (!open && timerRef.current) {
      clearInterval(timerRef.current);
      setIsPlaying(false);
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm animate-fade-in" onClick={onClose}>
      <div className="relative w-full max-w-6xl mx-4 my-6 md:my-10 rounded-2xl border border-border-soft bg-surface shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-10 w-9 h-9 flex items-center justify-center rounded-xl border border-border-soft bg-surface text-muted hover:text-text hover:bg-hover transition-all backdrop-blur-sm"
          aria-label="Close"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <div className="px-4 sm:px-6 md:px-10 py-8 md:py-12">
      {/* ── Header ── */}
      <div className="mb-10 md:mb-14">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent-soft border border-accent mb-4">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse-slow" />
          <span className="text-xs font-semibold text-accent tracking-wide uppercase">
            Agentic Pipeline
          </span>
        </div>
        <h2 className="text-3xl md:text-4xl lg:text-5xl font-bold text-text tracking-tight">
          Agentic Loop
        </h2>
      </div>

      {/* ── Timeline ── */}
      <div className="relative mb-16 md:mb-20">
        {/* Track line */}
        <div className="absolute left-0 right-0 top-6 h-[2px] bg-surface-2 rounded-full" />
        {/* Progress fill */}
        <div
          className="absolute left-0 top-6 h-[2px] rounded-full bg-accent transition-all duration-500 ease-out"
          style={{ width: `${(activeStep / (STEPS.length - 1)) * 100}%` }}
        />

        {/* Step nodes */}
        <div className="relative flex justify-between">
          {STEPS.map((s, i) => {
            const isActive = i === activeStep;
            const isPast = i < activeStep;
            const lc = LAYER_COLORS[s.layer];
            const inLoop = i >= LOOP_START && i <= LOOP_END;
            const isLoopActive = activeStep >= LOOP_START && activeStep <= LOOP_END;

            return (
              <button
                key={s.id}
                onClick={() => !isPlaying && goTo(i)}
                disabled={isPlaying}
                className="flex flex-col items-center group outline-none focus-visible:ring-2 focus-visible:ring-primary-400 rounded-xl"
                aria-label={`Step ${s.id}: ${s.title}`}
                aria-current={isActive ? "step" : undefined}
              >
                {/* Circle */}
                <div
                  className={`
                    relative w-12 h-12 rounded-xl flex items-center justify-center
                    transition-all duration-300 border
                    ${isActive
                      ? `bg-white dark:bg-navy-800 border-slate-200 dark:border-white/[0.12] shadow-card-hover dark:shadow-none ring-2 ${lc.ring} scale-105`
                      : isPast
                      ? `bg-primary-50 dark:bg-primary-400/10 border-primary-100 dark:border-primary-400/20 ${lc.text}`
                      : "bg-white dark:bg-navy-850 border-slate-200 dark:border-white/[0.06] text-slate-400 dark:text-slate-500 group-hover:border-slate-300 dark:group-hover:border-white/[0.12] group-hover:shadow-card"
                    }
                  `}
                >
                  <span className={isActive ? lc.text : ""}>
                    {isActive ? s.icon : (
                      <span className="text-xs font-bold">{s.id}</span>
                    )}
                  </span>
                </div>
                {/* Label */}
                <span
                  className={`
                    mt-1.5 text-[11px] font-medium transition-colors whitespace-nowrap
                    ${isActive ? lc.text : "text-slate-400 dark:text-slate-500 group-hover:text-slate-600 dark:group-hover:text-slate-300"}
                  `}
                >
                  {s.label}
                </span>
                {/* Loop bracket connector — first loop step gets the label */}
                {inLoop && (
                  <div className="flex flex-col items-center mt-1.5">
                    <div className={`w-[2px] h-2 rounded-full transition-colors duration-300 ${
                      isLoopActive ? "bg-amber-400" : "bg-slate-200 dark:bg-white/[0.08]"
                    }`} />
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* ── Agentic Loop bracket — rendered below the step nodes ── */}
        {(() => {
          // Calculate the horizontal positions based on step indices
          const total = STEPS.length;
          const leftPct = (LOOP_START / (total - 1)) * 100;
          const rightPct = (LOOP_END / (total - 1)) * 100;
          const widthPct = rightPct - leftPct;
          const isLoopActive = activeStep >= LOOP_START && activeStep <= LOOP_END;
          return (
            <div
              className="absolute hidden md:block pointer-events-none"
              style={{ left: `${leftPct}%`, width: `${widthPct}%`, top: "calc(100% - 6px)" }}
            >
              {/* Bracket shape: ╰──────────╯ */}
              <svg className="w-full" viewBox="0 0 200 28" preserveAspectRatio="none" fill="none" aria-hidden>
                <path
                  d="M 4 0 L 4 14 Q 4 22 12 22 L 188 22 Q 196 22 196 14 L 196 0"
                  stroke="currentColor"
                  className={`transition-colors duration-300 ${
                    isLoopActive ? "text-amber-400" : "text-slate-200 dark:text-white/[0.08]"
                  }`}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  fill="none"
                />
                {/* Small arrow at left end pointing up (return) */}
                <path
                  d="M 1 6 L 4 0 L 7 6"
                  stroke="currentColor"
                  className={`transition-colors duration-300 ${
                    isLoopActive ? "text-amber-400" : "text-slate-200 dark:text-white/[0.08]"
                  }`}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
              </svg>
              {/* Label centered under bracket */}
              <div className="flex items-center justify-center gap-1.5 -mt-0.5">
                <svg className={`w-3 h-3 transition-colors duration-300 ${
                  isLoopActive ? "text-amber-500 dark:text-amber-400" : "text-slate-300 dark:text-slate-600"
                }`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.012 4.356v4.992" />
                </svg>
                <span className={`text-[10px] font-bold tracking-wider uppercase transition-colors duration-300 ${
                  isLoopActive ? "text-amber-500 dark:text-amber-400" : "text-slate-300 dark:text-slate-600"
                }`}>
                  Agentic Loop
                </span>
              </div>
            </div>
          );
        })()}
      </div>

      {/* ── Detail card ── */}
      <div
        ref={cardRef}
        className="rounded-2xl border border-border-soft bg-surface shadow-card dark:shadow-none overflow-hidden animate-fade-in"
        key={activeStep}
      >
        {/* Top accent strip */}
        <div className={`h-1 bg-gradient-to-r from-primary-400 via-violet-400 to-cyan-400`} />

        <div className="p-6 md:p-8">
          {/* Row: number + title + badges */}
          <div className="flex flex-wrap items-start gap-3 mb-4">
            <span className={`inline-flex items-center justify-center w-9 h-9 rounded-xl border text-sm font-bold ${colors.badge}`}>
              {step.id}
            </span>
            <div className="flex-1 min-w-0">
              <h3 className="text-xl md:text-2xl font-bold text-text tracking-tight">
                {step.title}
              </h3>
              <div className="flex items-center gap-2 mt-1">
                <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${colors.text}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
                  {LAYER_LABELS[step.layer]}
                </span>
                <span className="text-text-strong dark:text-white/[0.12]">·</span>
                <code className="text-[11px] font-mono text-muted truncate">
                  {step.source}
                </code>
              </div>
            </div>
            {step.isLoop && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-accent-soft text-accent border border-accent">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.012 4.356v4.992" />
                </svg>
                Agentic Loop
              </span>
            )}
          </div>

          {/* Short description */}
          <p className="text-muted text-sm leading-relaxed mb-5">
            {step.description}
          </p>

          {/* ── Inline Visualization ── */}
          <div className="mb-5">
            {step.visualization}
          </div>

          {/* Detailed explanation */}
          <p className="text-text text-[15px] leading-relaxed mb-5">
            {step.detail}
          </p>

        </div>
      </div>

        </div>
      </div>
    </div>
  );
}
