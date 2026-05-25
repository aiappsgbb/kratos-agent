"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { listTraceOperations, getTraceOperation } from "@/lib/api";
import type { SpanCategory, TraceList, TraceOperation, TraceSpan } from "@/types";

interface Props {
  useCase: string;
}

const spanCategoryColors: Record<SpanCategory, string> = {
  llm: "bg-blue-500",
  agent: "bg-indigo-500",
  agent_internal: "bg-indigo-400",
  tool: "bg-emerald-500",
  skill: "bg-teal-500",
  http: "bg-amber-500",
  platform: "bg-violet-500",
  error: "bg-red-500",
  other: "bg-slate-400",
};

const spanCategoryTextColors: Record<SpanCategory, string> = {
  llm: "text-blue-600 dark:text-blue-400",
  agent: "text-indigo-600 dark:text-indigo-400",
  agent_internal: "text-indigo-500 dark:text-indigo-400",
  tool: "text-emerald-600 dark:text-emerald-400",
  skill: "text-teal-600 dark:text-teal-400",
  http: "text-amber-600 dark:text-amber-400",
  platform: "text-violet-600 dark:text-violet-400",
  error: "text-red-600 dark:text-red-400",
  other: "text-slate-500 dark:text-slate-400",
};

const spanCategoryEmoji: Record<SpanCategory, string> = {
  llm: "🧠",
  agent: "✨",
  agent_internal: "✨",
  tool: "🔧",
  skill: "📋",
  http: "🌐",
  platform: "⚙️",
  error: "⚠️",
  other: "•",
};

// Attributes we surface in a labeled grid (in order). Anything not in this list
// falls into the "Other" raw-attribute section.
const SPAN_HIGHLIGHT_KEYS: Array<{ key: string; label: string }> = [
  { key: "gen_ai.response.model", label: "Model" },
  { key: "gen_ai.operation.name", label: "Operation" },
  { key: "gen_ai.usage.input_tokens", label: "Input tokens" },
  { key: "gen_ai.usage.output_tokens", label: "Output tokens" },
  { key: "gen_ai.tool.name", label: "Tool" },
  { key: "gen_ai.tool.kind", label: "Tool kind" },
  { key: "kratos.skill.name", label: "Skill" },
  { key: "kratos.use_case", label: "Use case" },
  { key: "kratos.conversation_id", label: "Conversation" },
  { key: "kratos.eval_run_id", label: "Eval run" },
  { key: "error.type", label: "Error" },
];

function _attr(span: TraceSpan, key: string): string {
  const v = span.attributes?.[key];
  if (v === undefined || v === null || v === "") return "";
  return String(v);
}

function _attrNum(span: TraceSpan, key: string): number {
  const v = span.attributes?.[key];
  if (typeof v === "number") return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function _fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function SpanIcon({ category }: { category: SpanCategory }) {
  return (
    <span className={`text-sm flex-shrink-0 ${spanCategoryTextColors[category] ?? "text-slate-400"}`} aria-hidden>
      {spanCategoryEmoji[category] ?? "•"}
    </span>
  );
}

function SpanRow({ span, maxEndMs }: { span: TraceSpan; maxEndMs: number }) {
  const [expanded, setExpanded] = useState(false);
  const indent = span.depth * 16;
  const left = maxEndMs > 0 ? (span.offset_ms / maxEndMs) * 100 : 0;
  const width = maxEndMs > 0 ? Math.max((span.duration_ms / maxEndMs) * 100, 0.5) : 0.5;
  const barColor = spanCategoryColors[span.category] ?? "bg-slate-400";

  const model = _attr(span, "gen_ai.response.model");
  const toolName = _attr(span, "gen_ai.tool.name") || _attr(span, "kratos.skill.name");
  const inTok = _attrNum(span, "gen_ai.usage.input_tokens");
  const outTok = _attrNum(span, "gen_ai.usage.output_tokens");
  const errType = _attr(span, "error.type");

  const highlights = SPAN_HIGHLIGHT_KEYS.filter((h) => _attr(span, h.key) !== "");
  const highlightKeySet = new Set(highlights.map((h) => h.key));
  const otherAttrs = Object.entries(span.attributes ?? {}).filter(([k]) => !highlightKeySet.has(k));

  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-2 hover:bg-slate-50/50 dark:hover:bg-white/[0.02] transition-colors text-left group"
      >
        <div style={{ width: indent, flexShrink: 0 }} />
        <SpanIcon category={span.category} />
        <span className="text-xs text-slate-700 dark:text-slate-300 truncate flex-shrink-0 font-medium" style={{ maxWidth: "200px" }}>
          {span.name}
        </span>
        {/* Inline gen_ai chips */}
        {toolName && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-mono flex-shrink-0 border border-emerald-200/60 dark:border-emerald-500/20">
            {toolName}
          </span>
        )}
        {model && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 font-mono flex-shrink-0 border border-blue-200/60 dark:border-blue-500/20">
            {model}
          </span>
        )}
        {(inTok > 0 || outTok > 0) && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-slate-400 font-mono flex-shrink-0">
            {_fmtTokens(inTok)} → {_fmtTokens(outTok)} tok
          </span>
        )}
        {errType && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 font-mono flex-shrink-0 border border-red-200/60 dark:border-red-500/20">
            {errType}
          </span>
        )}
        {/* Waterfall bar */}
        <div className="flex-1 relative h-4 bg-slate-100 dark:bg-white/[0.04] rounded overflow-hidden mx-2 min-w-[40px]">
          <div
            className={`absolute top-0 h-full ${barColor} rounded opacity-80`}
            style={{ left: `${left}%`, width: `${width}%` }}
          />
        </div>
        <span className="text-xs text-slate-400 font-mono flex-shrink-0 w-16 text-right">
          {span.duration_ms}ms
        </span>
        {!span.success && (
          <span className="text-[10px] text-red-500 flex-shrink-0">✗</span>
        )}
      </button>
      {expanded && (
        <div className="mx-4 mb-2 rounded-xl bg-slate-50 dark:bg-white/[0.03] border border-slate-100 dark:border-white/[0.04] px-4 py-3 space-y-3" style={{ marginLeft: indent + 32 }}>
          {highlights.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Span Details</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                {highlights.map((h) => (
                  <div key={h.key} className="flex items-start gap-2">
                    <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400 flex-shrink-0 pt-0.5 w-28 truncate">{h.label}</span>
                    <span className="text-[11px] text-slate-700 dark:text-slate-300 font-mono break-all">{_attr(span, h.key)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {otherAttrs.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Other Attributes</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                {otherAttrs.map(([k, v]) => (
                  <div key={k} className="flex items-start gap-2">
                    <span className="text-[10px] font-mono text-slate-400 flex-shrink-0 pt-0.5 truncate max-w-[120px]">{k}</span>
                    <span className="text-[10px] text-slate-600 dark:text-slate-400 break-all">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {highlights.length === 0 && otherAttrs.length === 0 && (
            <p className="text-[11px] text-slate-400 italic">No attributes</p>
          )}
        </div>
      )}
    </div>
  );
}

interface OperationStats {
  totalInputTokens: number;
  totalOutputTokens: number;
  modelsTouched: string[];
  toolCount: number;
  errorCount: number;
  categoryCounts: Partial<Record<SpanCategory, number>>;
}

function computeOperationStats(spans: TraceSpan[]): OperationStats {
  let inTok = 0;
  let outTok = 0;
  const models = new Set<string>();
  let toolCount = 0;
  let errorCount = 0;
  const cats: Partial<Record<SpanCategory, number>> = {};
  for (const sp of spans) {
    inTok += _attrNum(sp, "gen_ai.usage.input_tokens");
    outTok += _attrNum(sp, "gen_ai.usage.output_tokens");
    const m = _attr(sp, "gen_ai.response.model");
    if (m) models.add(m);
    if (sp.category === "tool" || sp.category === "skill") toolCount += 1;
    if (!sp.success || _attr(sp, "error.type")) errorCount += 1;
    cats[sp.category] = (cats[sp.category] ?? 0) + 1;
  }
  return {
    totalInputTokens: inTok,
    totalOutputTokens: outTok,
    modelsTouched: [...models],
    toolCount,
    errorCount,
    categoryCounts: cats,
  };
}

function OperationRow({ op, lookbackHours }: { op: TraceOperation; lookbackHours: number }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<TraceOperation | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeFilter, setActiveFilter] = useState<SpanCategory | null>(null);

  const handleExpand = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail) {
      setLoading(true);
      try {
        const d = await getTraceOperation(op.operation_id, lookbackHours);
        setDetail(d);
      } catch {
        setDetail(op);
      } finally {
        setLoading(false);
      }
    }
  };

  const opData = detail ?? op;
  const allSpans: TraceSpan[] = opData.spans ?? [];
  const stats = useMemo(() => computeOperationStats(allSpans), [allSpans]);
  const spans = activeFilter ? allSpans.filter((s) => s.category === activeFilter) : allSpans;
  const maxEndMs = allSpans.reduce((m, s) => Math.max(m, s.offset_ms + s.duration_ms), 0);

  const now = Date.now();
  const opDate = new Date(op.timestamp);
  const diffMs = now - opDate.getTime();
  const relativeTime =
    diffMs < 60000
      ? `${Math.round(diffMs / 1000)}s ago`
      : diffMs < 3600000
      ? `${Math.round(diffMs / 60000)}m ago`
      : diffMs < 86400000
      ? `${Math.round(diffMs / 3600000)}h ago`
      : opDate.toLocaleDateString();

  return (
    <div className="border-b border-slate-100 dark:border-white/[0.04] last:border-b-0">
      <button
        onClick={handleExpand}
        className="w-full flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50/50 dark:hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-slate-600 dark:text-slate-400 truncate">
              {op.operation_id.slice(0, 16)}…
            </span>
            {op.eval_run_id && (
              <span className="text-[10px] px-1.5 py-0.5 bg-primary-50 dark:bg-primary-500/10 text-primary-600 dark:text-primary-400 rounded font-mono flex-shrink-0">
                eval
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-400 mt-0.5">{relativeTime}</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-500 flex-shrink-0">
          <span className="font-mono">{op.total_duration_ms}ms</span>
          <span className="text-slate-400">{op.span_count} spans</span>
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 transition-transform flex-shrink-0 ${expanded ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 dark:border-white/[0.04] bg-slate-50/30 dark:bg-white/[0.01]">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary-200 border-t-primary-600" />
            </div>
          ) : (
            <>
              {/* Per-operation summary header */}
              {allSpans.length > 0 && (
                <div className="px-5 py-3 border-b border-slate-100 dark:border-white/[0.04] space-y-3">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                    {(stats.totalInputTokens > 0 || stats.totalOutputTokens > 0) && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">Tokens</span>
                        <span className="font-mono text-slate-700 dark:text-slate-200 font-medium">
                          {_fmtTokens(stats.totalInputTokens)} → {_fmtTokens(stats.totalOutputTokens)}
                        </span>
                      </div>
                    )}
                    {stats.modelsTouched.length > 0 && (
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-slate-400">Models</span>
                        {stats.modelsTouched.map((m) => (
                          <span key={m} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 font-mono border border-blue-200/60 dark:border-blue-500/20">
                            {m}
                          </span>
                        ))}
                      </div>
                    )}
                    {stats.toolCount > 0 && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">🔧 Tools</span>
                        <span className="font-mono text-emerald-700 dark:text-emerald-400 font-medium">{stats.toolCount}</span>
                      </div>
                    )}
                    {stats.errorCount > 0 && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">Errors</span>
                        <span className="font-mono text-red-600 dark:text-red-400 font-medium">{stats.errorCount}</span>
                      </div>
                    )}
                  </div>
                  {/* Category filter chips */}
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      onClick={() => setActiveFilter(null)}
                      className={`text-[10px] px-2 py-1 rounded-full font-medium transition-colors border ${
                        activeFilter === null
                          ? "bg-primary-50 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border-primary-200 dark:border-primary-500/30"
                          : "bg-white dark:bg-white/[0.04] text-slate-500 dark:text-slate-400 border-slate-200 dark:border-white/[0.08] hover:border-slate-300"
                      }`}
                    >
                      all · {allSpans.length}
                    </button>
                    {(Object.entries(stats.categoryCounts) as [SpanCategory, number][])
                      .sort((a, b) => b[1] - a[1])
                      .map(([cat, cnt]) => (
                        <button
                          key={cat}
                          onClick={() => setActiveFilter((cur) => (cur === cat ? null : cat))}
                          className={`text-[10px] px-2 py-1 rounded-full font-medium transition-colors flex items-center gap-1 border ${
                            activeFilter === cat
                              ? "bg-primary-50 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border-primary-200 dark:border-primary-500/30"
                              : "bg-white dark:bg-white/[0.04] text-slate-500 dark:text-slate-400 border-slate-200 dark:border-white/[0.08] hover:border-slate-300"
                          }`}
                        >
                          <span>{spanCategoryEmoji[cat]}</span>
                          <span>{cat}</span>
                          <span className="font-mono text-slate-400">·</span>
                          <span className="font-mono">{cnt}</span>
                        </button>
                      ))}
                  </div>
                </div>
              )}

              {/* Spans waterfall */}
              {spans.length > 0 ? (
                <div className="py-2">
                  {spans.map((span) => (
                    <SpanRow key={span.id} span={span} maxEndMs={maxEndMs} />
                  ))}
                </div>
              ) : allSpans.length > 0 ? (
                <p className="text-xs text-slate-400 text-center py-6">No spans match the active filter</p>
              ) : (
                <p className="text-xs text-slate-400 text-center py-6">No span data available</p>
              )}

              {/* Logs */}
              {opData.logs && opData.logs.length > 0 && (
                <div className="px-5 pb-4 space-y-2 border-t border-slate-100 dark:border-white/[0.04] pt-4">
                  <h5 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Logs</h5>
                  {[...opData.logs]
                    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
                    .map((log, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className={`text-[10px] font-mono flex-shrink-0 pt-0.5 ${
                          log.severity >= 400 ? "text-red-500" : log.severity >= 300 ? "text-amber-500" : "text-slate-400"
                        }`}>
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </span>
                        <span className="text-xs text-slate-600 dark:text-slate-400 break-words">{log.message}</span>
                      </div>
                    ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function TracesAdminPanel({ useCase }: Props): JSX.Element {
  const [conversationId, setConversationId] = useState("");
  const [evalRunId, setEvalRunId] = useState("");
  const [lookbackHours, setLookbackHours] = useState(24);
  const [traceData, setTraceData] = useState<TraceList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listTraceOperations({
        useCase,
        conversationId: conversationId || undefined,
        evalRunId: evalRunId || undefined,
        lookbackHours,
      });
      setTraceData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load traces");
    } finally {
      setLoading(false);
    }
  }, [useCase, conversationId, evalRunId, lookbackHours]);

  useEffect(() => {
    handleRefresh();
  }, [handleRefresh]);

  const summary = traceData?.summary;
  const operations = traceData?.operations ?? [];

  return (
    <div className="max-w-4xl space-y-6">
      {/* Toolbar */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Conversation ID</label>
          <input
            type="text"
            value={conversationId}
            onChange={(e) => setConversationId(e.target.value)}
            placeholder="Filter by conversation…"
            className="w-48 px-3 py-2 bg-white dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.08] rounded-xl text-sm text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-400 transition-all placeholder:text-slate-400"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Eval Run ID</label>
          <input
            type="text"
            value={evalRunId}
            onChange={(e) => setEvalRunId(e.target.value)}
            placeholder="Filter by eval run…"
            className="w-48 px-3 py-2 bg-white dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.08] rounded-xl text-sm text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-400 transition-all placeholder:text-slate-400"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Lookback (hours)</label>
          <input
            type="number"
            min={1}
            max={720}
            value={lookbackHours}
            onChange={(e) => setLookbackHours(Math.max(1, parseInt(e.target.value, 10) || 24))}
            className="w-24 px-3 py-2 bg-white dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.08] rounded-xl text-sm text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-400 transition-all"
          />
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 text-sm text-white bg-gradient-to-r from-primary-600 to-primary-500 rounded-xl hover:from-primary-700 hover:to-primary-600 transition-all shadow-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white" />
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
          )}
          Refresh
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-3 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-sm rounded-xl border border-red-100 dark:border-red-500/20 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600 transition-colors ml-3">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && !traceData && (
        <div className="flex items-center justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary-200 border-t-primary-600" />
        </div>
      )}

      {/* Summary card */}
      {summary && !summary.error && (
        <div className="bg-white dark:bg-white/[0.03] border border-slate-200 dark:border-white/[0.08] rounded-2xl p-5">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{summary.total_operations}</p>
              <p className="text-xs text-slate-500 mt-0.5">Operations</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {summary.avg_latency_ms > 0 ? `${Math.round(summary.avg_latency_ms)}ms` : "—"}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">Avg Latency</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {summary.total_tokens > 0 ? summary.total_tokens.toLocaleString() : "—"}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">Total Tokens</p>
            </div>
            <div className="text-center">
              <div className="flex flex-wrap items-center justify-center gap-1.5 min-h-[2rem]">
                {summary.models_used.length > 0 ? (
                  summary.models_used.map((m) => (
                    <span key={m} className="text-[10px] px-2 py-0.5 bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-slate-400 rounded-full font-mono">
                      {m}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-400">—</span>
                )}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">Models</p>
            </div>
          </div>
        </div>
      )}

      {/* Summary error */}
      {summary?.error && (
        <div className="px-4 py-3 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 text-sm rounded-xl border border-amber-100 dark:border-amber-500/20">
          <p className="font-medium mb-0.5">App Insights Notice</p>
          <p className="text-xs">{summary.error}</p>
        </div>
      )}

      {/* Operations list */}
      {traceData && (
        operations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-slate-100 to-slate-50 dark:from-white/[0.06] dark:to-white/[0.02] flex items-center justify-center mb-4">
              <svg className="w-7 h-7 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <h4 className="text-sm font-semibold text-slate-600 dark:text-slate-300 mb-1">No traces found</h4>
            <p className="text-xs text-slate-400 max-w-xs leading-relaxed">
              {summary?.error
                ? "App Insights is not configured or returned no data."
                : `No operations found in the last ${lookbackHours}h for this use-case.`}
            </p>
          </div>
        ) : (
          <div className="bg-white dark:bg-white/[0.03] border border-slate-200 dark:border-white/[0.08] rounded-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-white/[0.06]">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-white">Operations</h3>
              <span className="text-xs font-mono text-slate-400 bg-slate-100 dark:bg-white/[0.06] px-2 py-0.5 rounded-full">
                {operations.length}
              </span>
            </div>

            {/* Category legend */}
            <div className="flex flex-wrap gap-3 px-5 py-3 border-b border-slate-100 dark:border-white/[0.04] bg-slate-50/30 dark:bg-white/[0.01]">
              {(Object.entries(spanCategoryColors) as [SpanCategory, string][]).map(([cat, color]) => (
                <div key={cat} className="flex items-center gap-1.5">
                  <div className={`w-2.5 h-2.5 rounded-sm ${color}`} />
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">{cat}</span>
                </div>
              ))}
            </div>

            <div>
              {operations.map((op) => (
                <OperationRow key={op.operation_id} op={op} lookbackHours={lookbackHours} />
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}
