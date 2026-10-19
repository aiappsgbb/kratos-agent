"use client";

import { useEffect, useState } from "react";
import type { RunStats, Skill } from "@/types";
import { KIND_STYLES, classifyTool, formatDuration, formatToolLabel, resolveSkillName } from "@/lib/tools";
import { AskUserCard, type PendingDecision } from "./AskUserCard";

export type RunPhase = "connecting" | "ready" | "working" | "waiting" | "error";

export interface ActivityItem {
  id: string;
  kind: "tool" | "text" | "subagent" | "decision";
  name: string;
  args?: Record<string, unknown>;
  /** The tool behind a decision item. */
  toolName?: string;
  startedAt: number;
  endedAt?: number;
  failed?: boolean;
}

const PHASE_LABEL: Record<RunPhase, string> = {
  connecting: "Connecting",
  ready: "Ready",
  working: "Working",
  waiting: "Needs your decision",
  error: "Error",
};

const PHASE_STYLE: Record<RunPhase, string> = {
  connecting: "bg-surface-2 text-muted",
  ready: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  working: "bg-accent-soft text-accent",
  waiting: "bg-ask text-accent-fg",
  error: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

/** Ticks once a second while something is running, so elapsed times stay live. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function ActivityRow({ item, now }: { item: ActivityItem; now: number }) {
  const running = item.endedAt === undefined;
  const elapsed = (item.endedAt ?? now) - item.startedAt;
  let label = item.name;
  let dot = "bg-slate-400";
  let tag = "";
  if (item.kind === "tool") {
    const display = resolveSkillName(item.name, item.args);
    const kind = classifyTool(display);
    label = formatToolLabel(display);
    dot = KIND_STYLES[kind].dot;
    tag = KIND_STYLES[kind].label;
  } else if (item.kind === "subagent") {
    tag = "Agent";
    dot = "bg-amber-500";
  } else if (item.kind === "decision") {
    tag = "You";
    dot = "bg-ask";
  }
  return (
    <li className="flex items-center gap-2.5 py-1.5 text-[13px]" data-testid="activity-item" data-state={running ? "running" : "done"}>
      {running ? (
        <span className="relative flex h-2 w-2 flex-shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
        </span>
      ) : (
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${item.failed ? "bg-red-500" : dot}`} />
      )}
      <span className={`flex-1 min-w-0 truncate ${running ? "text-text-strong" : "text-text"}`}>{label}</span>
      {tag && <span className="text-[10px] uppercase tracking-wide text-muted">{tag}</span>}
      <span className="text-[11px] text-muted tabular-nums w-12 text-right">{formatDuration(Math.max(0, elapsed))}</span>
    </li>
  );
}

export function RunInspector({
  phase,
  decision,
  activity,
  lastRun,
  personaName,
  skills,
  error,
  onClose,
}: {
  phase: RunPhase;
  decision: PendingDecision | null;
  activity: ActivityItem[];
  lastRun: RunStats | null;
  personaName: string;
  skills: Skill[];
  error: string;
  onClose?: () => void;
}) {
  const now = useNow(activity.some((a) => a.endedAt === undefined));
  const enabledSkills = skills.filter((s) => s.enabled);

  return (
    <aside
      aria-label="Run inspector"
      className="h-full flex flex-col bg-surface border-l border-border-soft w-[340px] max-w-full"
      data-testid="run-inspector"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border-soft">
        <h2 className="flex-1 text-sm font-semibold text-text-strong truncate">{personaName}</h2>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors duration-200 ${PHASE_STYLE[phase]}`}
          data-testid="run-status"
          data-phase={phase}
        >
          {(phase === "working" || phase === "waiting") && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
          {PHASE_LABEL[phase]}
        </span>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Close inspector" className="xl:hidden p-1 text-muted hover:text-text rounded-md hover:bg-hover transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        {error && (
          <p role="alert" className="text-xs rounded-lg border border-red-200 bg-red-50 text-red-700 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300 px-3 py-2">
            {error}
          </p>
        )}

        {decision && (
          <section aria-label="Pending decision">
            <AskUserCard
              variant="panel"
              toolCallId={decision.toolCallId}
              args={{ question: decision.question, choices: decision.choices, allowFreeform: decision.allowFreeform }}
              status="executing"
            />
          </section>
        )}

        <section aria-labelledby="activity-heading">
          <h3 id="activity-heading" className="text-xs font-semibold text-text-strong mb-1.5">
            Activity
          </h3>
          {activity.length === 0 ? (
            <p className="text-xs text-muted leading-relaxed">
              Each skill, tool call and decision in the next run shows up here as it happens, with how long it took.
            </p>
          ) : (
            <ol className="divide-y divide-border-soft">
              {activity.map((item) => (
                <ActivityRow key={item.id} item={item} now={now} />
              ))}
            </ol>
          )}
        </section>

        {lastRun && (
          <section aria-labelledby="lastrun-heading">
            <h3 id="lastrun-heading" className="text-xs font-semibold text-text-strong mb-1.5">
              Last run
            </h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px]">
              <dt className="text-muted">Duration</dt>
              <dd className="text-right tabular-nums text-text">{formatDuration(lastRun.totalDurationMs)}</dd>
              <dt className="text-muted">First token</dt>
              <dd className="text-right tabular-nums text-text">{lastRun.timeToFirstTokenMs ? formatDuration(lastRun.timeToFirstTokenMs) : "—"}</dd>
              <dt className="text-muted">Tokens in / out</dt>
              <dd className="text-right tabular-nums text-text">
                {lastRun.promptTokens.toLocaleString()} / {lastRun.completionTokens.toLocaleString()}
              </dd>
              <dt className="text-muted">Tool calls</dt>
              <dd className="text-right tabular-nums text-text">{lastRun.totalToolCalls}</dd>
            </dl>
          </section>
        )}

        {enabledSkills.length > 0 && (
          <section aria-labelledby="skills-heading">
            <h3 id="skills-heading" className="text-xs font-semibold text-text-strong mb-2">
              Skills this agent can use
            </h3>
            <ul className="flex flex-wrap gap-1.5">
              {enabledSkills.map((s) => (
                <li key={s.name} title={s.description} className={`px-2 py-0.5 rounded-md border text-[11px] ${KIND_STYLES.skill.chip}`}>
                  {formatToolLabel(s.name)}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
