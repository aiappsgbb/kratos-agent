"use client";

import { useMemo, useState } from "react";

export type CellValue = string | number | boolean | null;

export interface TableColumn {
  key: string;
  label: string;
  format?: "text" | "number" | "currency" | "percent";
  currency?: string;
}

export interface TableSpec {
  title?: string;
  caption?: string;
  columns?: TableColumn[];
  rows?: Record<string, CellValue>[];
}

function formatCell(value: CellValue, col: TableColumn): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const n = typeof value === "number" ? value : Number(value);
  if (col.format && col.format !== "text" && Number.isFinite(n)) {
    if (col.format === "percent") return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    if (col.format === "currency") {
      try {
        return n.toLocaleString(undefined, { style: "currency", currency: col.currency || "USD", maximumFractionDigits: 2 });
      } catch {
        return `${col.currency ?? ""} ${n.toLocaleString()}`.trim();
      }
    }
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

const numeric = (col: TableColumn) => col.format === "number" || col.format === "currency" || col.format === "percent";

/**
 * A sortable data table the agent renders with the `show_table` browser tool.
 * Arguments stream in, so rows appear as they arrive.
 */
export function TableCard({ spec }: { spec: TableSpec }) {
  const columns = (spec.columns ?? []).filter((c) => c && c.key);
  const rows = useMemo(() => (spec.rows ?? []).filter((r) => r && typeof r === "object"), [spec.rows]);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      const nx = Number(x);
      const ny = Number(y);
      const cmp = Number.isFinite(nx) && Number.isFinite(ny) ? nx - ny : String(x ?? "").localeCompare(String(y ?? ""));
      return cmp * sort.dir;
    });
  }, [rows, sort]);

  const toggle = (key: string) =>
    setSort((s) => (!s || s.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : null));

  return (
    <figure data-testid="table-card" className="w-full max-w-3xl rounded-xl border border-border-soft bg-surface shadow-sm overflow-hidden animate-fade-in">
      <figcaption className="px-4 pt-3 pb-2">
        <p className="text-sm font-semibold text-text-strong">{spec.title || "Preparing table…"}</p>
        {spec.caption && <p className="text-xs text-muted mt-0.5">{spec.caption}</p>}
      </figcaption>
      {columns.length === 0 ? (
        <div className="h-24 mx-4 mb-4 rounded-lg bg-surface-2 animate-pulse" role="status" aria-label="Table loading" />
      ) : (
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-[13px] tabular-nums">
            <thead className="sticky top-0 bg-surface-2">
              <tr>
                {columns.map((col) => {
                  const active = sort?.key === col.key;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : "none"}
                      className={`px-3 py-2 font-medium text-text-strong whitespace-nowrap ${numeric(col) ? "text-right" : "text-left"}`}
                    >
                      <button type="button" onClick={() => toggle(col.key)} className="inline-flex items-center gap-1 hover:text-accent transition-colors">
                        {col.label}
                        <span className={`text-[10px] ${active ? "opacity-100" : "opacity-30"}`} aria-hidden="true">
                          {active && sort!.dir === -1 ? "▼" : "▲"}
                        </span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => (
                <tr key={i} className="border-t border-border-soft hover:bg-hover transition-colors">
                  {columns.map((col) => (
                    <td key={col.key} className={`px-3 py-1.5 text-text ${numeric(col) ? "text-right" : "text-left"}`}>
                      {formatCell(row[col.key], col)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && <p className="px-4 py-2 text-[11px] text-muted border-t border-border-soft">{rows.length} row{rows.length === 1 ? "" : "s"} · click a column to sort</p>}
    </figure>
  );
}
