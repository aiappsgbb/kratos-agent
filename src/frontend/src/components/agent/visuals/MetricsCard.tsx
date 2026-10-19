"use client";

export interface Metric {
  label: string;
  value: string | number;
  unit?: string;
  delta?: number;
  deltaLabel?: string;
  status?: "good" | "warning" | "bad" | "neutral";
  note?: string;
}

export interface MetricsSpec {
  title?: string;
  metrics?: Metric[];
}

const STATUS: Record<NonNullable<Metric["status"]>, { dot: string; label: string }> = {
  good: { dot: "bg-emerald-500", label: "On track" },
  warning: { dot: "bg-amber-500", label: "Watch" },
  bad: { dot: "bg-red-500", label: "Off track" },
  neutral: { dot: "bg-slate-400", label: "" },
};

const CURRENCY_UNITS = new Set(["$", "€", "£", "¥", "CHF", "USD", "EUR", "GBP", "JPY"]);

function display(m: Metric): string {
  const money = !!m.unit && CURRENCY_UNITS.has(m.unit) && typeof m.value === "number" && !Number.isInteger(m.value);
  const v =
    typeof m.value === "number"
      ? m.value.toLocaleString(undefined, { minimumFractionDigits: money ? 2 : 0, maximumFractionDigits: 2 })
      : m.value;
  if (!m.unit) return String(v);
  return m.unit === "%" ? `${v}%` : m.unit.length <= 1 ? `${m.unit}${v}` : `${v} ${m.unit}`;
}

/**
 * Key figures at a glance, rendered by the `show_metrics` browser tool: one
 * compact tile per metric with an optional change and a status.
 */
export function MetricsCard({ spec }: { spec: MetricsSpec }) {
  const metrics = (spec.metrics ?? []).filter((m) => m && m.label);
  return (
    <section data-testid="metrics-card" aria-label={spec.title || "Key metrics"} className="w-full max-w-3xl animate-fade-in">
      {spec.title && <p className="text-sm font-semibold text-text-strong mb-2">{spec.title}</p>}
      {metrics.length === 0 ? (
        <div className="h-20 rounded-xl bg-surface-2 animate-pulse" role="status" aria-label="Metrics loading" />
      ) : (
        <dl className="grid grid-cols-2 sm:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-2">
          {metrics.map((m) => {
            const status = STATUS[m.status ?? "neutral"] ?? STATUS.neutral;
            const up = (m.delta ?? 0) > 0;
            const down = (m.delta ?? 0) < 0;
            return (
              <div key={m.label} className="rounded-xl border border-border-soft bg-surface px-3.5 py-3 shadow-sm">
                <dt className="flex items-center gap-1.5 text-[11px] text-muted">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${status.dot}`} title={status.label || undefined} />
                  <span className="truncate">{m.label}</span>
                </dt>
                <dd className="mt-1">
                  <span className="text-lg font-semibold text-text-strong tabular-nums">{display(m)}</span>
                  {m.delta !== undefined && m.delta !== null && (
                    <span className={`ml-2 text-[11px] tabular-nums ${up ? "text-emerald-600" : down ? "text-red-600" : "text-muted"}`}>
                      {up ? "▲" : down ? "▼" : ""} {Math.abs(m.delta).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {m.deltaLabel ? ` ${m.deltaLabel}` : ""}
                    </span>
                  )}
                  {m.note && <p className="text-[11px] text-muted mt-0.5 leading-snug">{m.note}</p>}
                  {status.label && <span className="sr-only">Status: {status.label}</span>}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}
