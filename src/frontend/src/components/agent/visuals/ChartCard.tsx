"use client";

import { useId, useState } from "react";

export interface ChartSeries {
  name: string;
  values: number[];
}

export interface ChartSpec {
  title?: string;
  subtitle?: string;
  kind?: "bar" | "line" | "donut";
  labels?: string[];
  series?: ChartSeries[];
  unit?: string;
}

// Series colours: the theme accent first, then hues that stay legible on both
// the light and dark Kratos themes.
const PALETTE = ["var(--accent)", "#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#64748b", "#ec4899"];

export function formatValue(value: number, unit = ""): string {
  const abs = Math.abs(value);
  const compact =
    abs >= 1_000_000
      ? `${(value / 1_000_000).toFixed(1)}M`
      : abs >= 10_000
        ? `${(value / 1_000).toFixed(0)}k`
        : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (!unit) return compact;
  if (unit === "%") return `${compact}%`;
  return unit.length <= 1 ? `${unit}${compact}` : `${compact} ${unit}`;
}

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * magnitude >= max / 4) ?? 10;
  return Math.ceil(max / (step * magnitude)) * step * magnitude;
}

function Legend({ series }: { series: ChartSeries[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
      {series.map((s, i) => (
        <li key={s.name} className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
          {s.name}
        </li>
      ))}
    </ul>
  );
}

function Cartesian({ kind, labels, series, unit }: { kind: "bar" | "line"; labels: string[]; series: ChartSeries[]; unit?: string }) {
  const W = 560;
  const H = 240;
  const pad = { top: 12, right: 12, bottom: 34, left: 52 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;
  const values = series.flatMap((s) => s.values).filter(Number.isFinite);
  const min = Math.min(0, ...values);
  const max = niceMax(Math.max(0, ...values));
  const y = (v: number) => pad.top + innerH - ((v - min) / (max - min || 1)) * innerH;
  const band = innerW / Math.max(labels.length, 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + t * (max - min));
  const longest = Math.min(14, Math.max(1, ...labels.map((l) => l.length)));
  const labelStep = Math.max(1, Math.ceil((labels.length * (longest * 6 + 8)) / innerW));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" aria-hidden="true">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.left} x2={W - pad.right} y1={y(t)} y2={y(t)} stroke="var(--border-soft)" strokeWidth={1} />
          <text x={pad.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fill="var(--muted)" fontSize={10}>
            {formatValue(t, unit)}
          </text>
        </g>
      ))}
      {labels.map((label, i) =>
        // Thin long axes so labels never collide; first and last always show.
        i === labels.length - 1 || (i % labelStep === 0 && labels.length - 1 - i >= labelStep * 0.6) ? (
          <text key={label + i} x={pad.left + band * (i + 0.5)} y={H - pad.bottom + 16} textAnchor="middle" fill="var(--muted)" fontSize={10}>
            {label.length > 14 ? `${label.slice(0, 13)}…` : label}
          </text>
        ) : null,
      )}
      {kind === "bar"
        ? series.map((s, si) => {
            const groupW = band * 0.7;
            const barW = groupW / series.length;
            return s.values.map((v, i) => {
              const x = pad.left + band * i + (band - groupW) / 2 + barW * si;
              return (
                <rect
                  key={`${si}-${i}`}
                  x={x + 1}
                  y={y(Math.max(v, 0))}
                  width={Math.max(barW - 2, 1)}
                  height={Math.max(Math.abs(y(v) - y(0)), 0.5)}
                  rx={2}
                  fill={PALETTE[si % PALETTE.length]}
                >
                  <title>{`${s.name} · ${labels[i] ?? ""}: ${formatValue(v, unit)}`}</title>
                </rect>
              );
            });
          })
        : series.map((s, si) => (
            <g key={s.name}>
              <polyline
                points={s.values.map((v, i) => `${pad.left + band * (i + 0.5)},${y(v)}`).join(" ")}
                fill="none"
                stroke={PALETTE[si % PALETTE.length]}
                strokeWidth={2}
                strokeLinejoin="round"
              />
              {s.values.map((v, i) => (
                <circle key={i} cx={pad.left + band * (i + 0.5)} cy={y(v)} r={3} fill={PALETTE[si % PALETTE.length]}>
                  <title>{`${s.name} · ${labels[i] ?? ""}: ${formatValue(v, unit)}`}</title>
                </circle>
              ))}
            </g>
          ))}
    </svg>
  );
}

function Donut({ labels, values, unit }: { labels: string[]; values: number[]; unit?: string }) {
  const total = values.reduce((a, b) => a + Math.max(b, 0), 0) || 1;
  const R = 70;
  const C = 2 * Math.PI * R;
  const offsets = values.reduce<number[]>((acc, v, i) => [...acc, (acc[i - 1] ?? 0) + (i ? (Math.max(values[i - 1], 0) / total) * C : 0)], []);
  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <svg viewBox="0 0 200 200" className="w-44 h-44 flex-shrink-0 -rotate-90" aria-hidden="true">
        <circle cx={100} cy={100} r={R} fill="none" stroke="var(--surface-2)" strokeWidth={28} />
        {values.map((v, i) => {
          const len = (Math.max(v, 0) / total) * C;
          return (
            <circle
              key={i}
              cx={100}
              cy={100}
              r={R}
              fill="none"
              stroke={PALETTE[i % PALETTE.length]}
              strokeWidth={28}
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offsets[i]}
            >
              <title>{`${labels[i] ?? ""}: ${formatValue(v, unit)}`}</title>
            </circle>
          );
        })}
      </svg>
      <ul className="flex-1 w-full space-y-1.5 text-[13px]">
        {labels.map((label, i) => (
          <li key={label + i} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="flex-1 text-text truncate">{label}</span>
            <span className="tabular-nums text-text-strong">{formatValue(values[i] ?? 0, unit)}</span>
            <span className="tabular-nums text-muted w-12 text-right">{(((values[i] ?? 0) / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A chart the agent draws by calling the `render_chart` browser tool. The
 * arguments stream in token by token, so it tolerates partial specs and shows a
 * placeholder until the data is complete.
 */
export function ChartCard({ spec, done = false }: { spec: ChartSpec; done?: boolean }) {
  const [showData, setShowData] = useState(false);
  const tableId = useId();
  const labels = spec.labels ?? [];
  const series = (spec.series ?? []).filter((s) => s && Array.isArray(s.values));
  const kind = spec.kind ?? "bar";
  const ready = labels.length > 0 && series.length > 0 && series.every((s) => s.values.length === labels.length);
  const summary = ready
    ? `${spec.title ?? "Chart"}: ${series
        .map((s) => `${s.name} ${s.values.map((v, i) => `${labels[i]} ${formatValue(v, spec.unit)}`).join(", ")}`)
        .join("; ")}`
    : "Chart loading";

  return (
    <figure data-testid="chart-card" data-kind={kind} data-ready={ready} className="w-full max-w-2xl rounded-xl border border-border-soft bg-surface p-4 shadow-sm animate-fade-in">
      <figcaption className="flex items-start gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-text-strong">{spec.title || "Preparing chart…"}</p>
          {spec.subtitle && <p className="text-xs text-muted mt-0.5">{spec.subtitle}</p>}
        </div>
        {ready && (
          <button
            type="button"
            onClick={() => setShowData((v) => !v)}
            aria-expanded={showData}
            aria-controls={tableId}
            className="text-[11px] px-2 py-1 rounded-md border border-border-soft text-muted hover:text-text hover:bg-hover transition-colors"
          >
            {showData ? "Hide data" : "Show data"}
          </button>
        )}
      </figcaption>

      {!ready && done ? (
        <p className="text-xs text-muted rounded-lg bg-surface-2 px-3 py-4" data-testid="chart-unrenderable">
          This chart could not be drawn from the data the agent sent: every series needs one number per label.
        </p>
      ) : !ready ? (
        <div className="h-40 rounded-lg bg-surface-2 animate-pulse" role="status" aria-label="Chart loading" />
      ) : (
        <div role="img" aria-label={summary} className="space-y-3">
          {kind === "donut" ? (
            <Donut labels={labels} values={series[0].values} unit={spec.unit} />
          ) : (
            <Cartesian kind={kind} labels={labels} series={series} unit={spec.unit} />
          )}
          {kind !== "donut" && <Legend series={series} />}
        </div>
      )}

      {ready && showData && (
        <table id={tableId} className="mt-3 w-full text-[12px] tabular-nums">
          <thead>
            <tr className="text-muted text-left">
              <th className="font-medium py-1 pr-3" scope="col">
                <span className="sr-only">Category</span>
              </th>
              {series.map((s) => (
                <th key={s.name} className="font-medium py-1 pr-3 text-right" scope="col">
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, i) => (
              <tr key={label + i} className="border-t border-border-soft">
                <th className="font-normal py-1 pr-3 text-left text-text" scope="row">
                  {label}
                </th>
                {series.map((s) => (
                  <td key={s.name} className="py-1 pr-3 text-right text-text">
                    {formatValue(s.values[i] ?? 0, spec.unit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </figure>
  );
}
