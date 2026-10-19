"use client";

import { useEffect, useMemo, useState } from "react";

export interface AllocationItem {
  name: string;
  current: number;
  proposed: number;
}

export interface AllocationArgs {
  title?: string;
  rationale?: string;
  items?: AllocationItem[];
}

interface Decision {
  decision: "approved" | "rejected";
  edited?: boolean;
  allocation?: { name: string; proposed: number }[];
}

function parseDecision(result?: string): Decision | null {
  if (!result) return null;
  try {
    return JSON.parse(result) as Decision;
  } catch {
    return null;
  }
}

const round1 = (n: number) => Math.round(n * 10) / 10;

/**
 * The agent's rebalance proposal as an editable card (`propose_allocation`, a
 * human-in-the-loop tool). The user adjusts target weights; approving returns
 * the edited allocation to the paused model turn, which continues with it.
 */
export function AllocationCard({
  args,
  status,
  result,
  respond,
}: {
  args: AllocationArgs;
  status: string;
  result?: string;
  respond?: (value: unknown) => Promise<void> | void;
}) {
  const items = useMemo(() => (args.items ?? []).filter((i) => i && typeof i.name === "string"), [args.items]);
  const [targets, setTargets] = useState<number[]>([]);
  const decided = parseDecision(result);
  const live = status === "executing" && !!respond && !decided;
  const streaming = status === "inProgress";

  useEffect(() => {
    // Seed editable targets from the proposal once its arguments have arrived.
    if (!streaming && items.length && targets.length !== items.length) setTargets(items.map((i) => Number(i.proposed) || 0));
  }, [items, streaming, targets.length]);

  const values = targets.length === items.length ? targets : items.map((i) => Number(i.proposed) || 0);
  const total = round1(values.reduce((a, b) => a + b, 0));
  const balanced = Math.abs(total - 100) < 0.6;
  const edited = values.some((v, i) => Math.abs(v - (Number(items[i]?.proposed) || 0)) > 0.05);
  const shown = decided?.allocation
    ? items.map((it) => decided.allocation!.find((a) => a.name === it.name)?.proposed ?? it.proposed)
    : values;

  const send = (decision: "approved" | "rejected") => {
    if (!respond) return;
    void respond(
      JSON.stringify(
        decision === "approved"
          ? { decision, edited, allocation: items.map((it, i) => ({ name: it.name, proposed: round1(values[i]) })) }
          : { decision },
      ),
    );
  };

  return (
    <section
      data-testid="allocation-card"
      data-state={decided ? decided.decision : live ? "pending" : "waiting"}
      className={`w-full max-w-2xl rounded-xl border p-4 transition-colors duration-200 ${
        live ? "bg-ask-bg border-ask shadow-sm" : "bg-surface border-border-soft"
      }`}
    >
      <div className="flex items-start gap-3 mb-1">
        <h3 className="flex-1 text-sm font-semibold text-text-strong">{args.title || "Proposed allocation"}</h3>
        <span
          className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            live ? "bg-ask text-accent-fg" : "bg-surface-2 text-muted"
          }`}
        >
          {live && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
          {decided ? (decided.decision === "approved" ? (decided.edited ? "Approved with your edits" : "Approved") : "Rejected") : live ? "Needs you" : "Drafting"}
        </span>
      </div>
      {args.rationale && <p className="text-[13px] text-muted mb-3 whitespace-pre-wrap">{args.rationale}</p>}

      {items.length === 0 ? (
        <div className="h-24 rounded-lg bg-surface-2 animate-pulse" role="status" aria-label="Proposal loading" />
      ) : (
        <div className="space-y-3">
          {items.map((it, i) => {
            const target = shown[i] ?? 0;
            const delta = round1(target - it.current);
            return (
              <div key={it.name} className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-3">
                <span className="text-[13px] text-text truncate" title={it.name}>
                  {it.name}
                </span>
                <div className="space-y-1">
                  <div className="relative h-2 rounded-full bg-surface-2" aria-hidden="true">
                    <div className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-150" style={{ width: `${Math.min(target, 100)}%` }} />
                    <div
                      className="absolute -top-1 -bottom-1 w-0.5 rounded-full"
                      style={{ left: `calc(${Math.min(it.current, 100)}% - 1px)`, background: "var(--ask-accent)" }}
                      title={`Current ${it.current}%`}
                    />
                  </div>
                  {live && (
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={0.5}
                      value={values[i] ?? 0}
                      aria-label={`${it.name} target weight`}
                      data-testid="allocation-slider"
                      onChange={(e) => setTargets((prev) => prev.map((v, j) => (j === i ? Number(e.target.value) : v)))}
                      className="w-full accent-[var(--accent)]"
                    />
                  )}
                </div>
                <div className="text-right tabular-nums">
                  <div className="text-[13px] text-text-strong">{round1(target)}%</div>
                  <div className={`text-[11px] ${delta > 0 ? "text-emerald-600" : delta < 0 ? "text-red-600" : "text-muted"}`}>
                    {delta > 0 ? "+" : ""}
                    {delta}pp
                  </div>
                </div>
              </div>
            );
          })}
          <p className="text-[11px] text-muted">
            <span className="inline-block w-0.5 h-2.5 align-middle mr-1" style={{ background: "var(--ask-accent)" }} />
            current weight
            <span className="inline-block w-3 h-1.5 rounded-full bg-accent align-middle ml-3 mr-1" />
            target weight.
            {live && (
              <>
                {" "}
                Total{" "}
                <span data-testid="allocation-total" className={balanced ? "text-text-strong" : "text-red-600 font-medium"}>
                  {total}%
                </span>
                {!balanced && " (must add up to 100%)"}
              </>
            )}
          </p>
        </div>
      )}

      {live && (
        <div className="flex flex-wrap gap-2 mt-4">
          <button
            type="button"
            data-testid="allocation-approve"
            disabled={!balanced}
            onClick={() => send("approved")}
            className="px-4 py-2 text-sm bg-accent text-accent-fg rounded-lg hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity font-medium"
          >
            {edited ? "Approve with my edits" : "Approve"}
          </button>
          <button
            type="button"
            data-testid="allocation-reject"
            onClick={() => send("rejected")}
            className="px-4 py-2 text-sm bg-surface text-text border border-border rounded-lg hover:bg-hover transition-colors"
          >
            Reject
          </button>
          {edited && (
            <button
              type="button"
              onClick={() => setTargets(items.map((it) => Number(it.proposed) || 0))}
              className="px-3 py-2 text-sm text-muted hover:text-text transition-colors"
            >
              Reset to proposal
            </button>
          )}
        </div>
      )}
    </section>
  );
}
