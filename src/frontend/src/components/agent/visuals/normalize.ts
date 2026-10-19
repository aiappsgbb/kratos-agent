/**
 * Models sometimes call the visual tools with a plausible but different shape
 * (Chart.js-style datasets, row objects, `type` instead of `kind`). Map the
 * common variants onto the declared schema instead of failing to render.
 */
import type { ChartSeries, ChartSpec } from "./ChartCard";
import type { MetricsSpec, Metric } from "./MetricsCard";
import type { TableColumn, TableSpec, CellValue } from "./TableCard";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v.replace(/[,%$€£\s]/g, "")) : NaN;
  return Number.isFinite(n) ? n : null;
};
const titleCase = (key: string) => key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const LABEL_KEYS = ["label", "name", "category", "x", "line", "date", "period", "month", "year"];

export function normalizeChart(raw: unknown): ChartSpec {
  if (!isObj(raw)) return {};
  const kindRaw = String(raw.kind ?? raw.type ?? raw.chartType ?? "bar").toLowerCase();
  const kind: ChartSpec["kind"] = kindRaw.includes("line") ? "line" : kindRaw.includes("pie") || kindRaw.includes("donut") || kindRaw.includes("doughnut") ? "donut" : "bar";
  const base = { title: raw.title as string | undefined, subtitle: raw.subtitle as string | undefined, unit: raw.unit as string | undefined, kind };

  let labels = Array.isArray(raw.labels) ? raw.labels.map(String) : undefined;
  let series: ChartSeries[] | undefined;

  if (Array.isArray(raw.series)) {
    series = raw.series.filter(isObj).map((s, i) => ({
      name: String(s.name ?? s.label ?? `Series ${i + 1}`),
      values: (Array.isArray(s.values) ? s.values : Array.isArray(s.data) ? s.data : []).map((v) => num(v) ?? 0),
    }));
  } else if (isObj(raw.data) && Array.isArray((raw.data as Obj).datasets)) {
    // Chart.js: { data: { labels, datasets: [{ label, data }] } }
    const d = raw.data as Obj;
    labels ??= Array.isArray(d.labels) ? d.labels.map(String) : undefined;
    series = (d.datasets as unknown[]).filter(isObj).map((s, i) => ({
      name: String(s.label ?? `Series ${i + 1}`),
      values: (Array.isArray(s.data) ? s.data : []).map((v) => num(v) ?? 0),
    }));
  } else if (Array.isArray(raw.datasets)) {
    series = (raw.datasets as unknown[]).filter(isObj).map((s, i) => ({
      name: String(s.label ?? s.name ?? `Series ${i + 1}`),
      values: (Array.isArray(s.data) ? s.data : Array.isArray(s.values) ? s.values : []).map((v) => num(v) ?? 0),
    }));
  } else if (Array.isArray(raw.data) && raw.data.every(isObj)) {
    // Row objects: [{ label: "Line 1", value: 90.2, target: 90 }]
    const rows = raw.data as Obj[];
    const labelKey = LABEL_KEYS.find((k) => rows.every((r) => r[k] !== undefined)) ?? Object.keys(rows[0] ?? {}).find((k) => num(rows[0][k]) === null);
    labels = rows.map((r) => String(labelKey ? r[labelKey] : ""));
    const valueKeys = Object.keys(rows[0] ?? {}).filter((k) => k !== labelKey && rows.every((r) => num(r[k]) !== null));
    series = valueKeys.map((k) => ({ name: titleCase(k), values: rows.map((r) => num(r[k]) ?? 0) }));
  } else if (Array.isArray(raw.values)) {
    series = [{ name: String(raw.seriesName ?? raw.title ?? "Value"), values: raw.values.map((v) => num(v) ?? 0) }];
  }
  return { ...base, labels, series };
}

export function normalizeTable(raw: unknown): TableSpec {
  if (!isObj(raw)) return {};
  const rowsRaw = Array.isArray(raw.rows) ? raw.rows : Array.isArray(raw.data) ? raw.data : [];
  let columns: TableColumn[] | undefined = Array.isArray(raw.columns)
    ? raw.columns.map((c, i) =>
        isObj(c)
          ? { key: String(c.key ?? c.field ?? c.name ?? c.label ?? i), label: String(c.label ?? c.header ?? c.title ?? c.key ?? c.name ?? i), format: c.format as TableColumn["format"], currency: c.currency as string | undefined }
          : { key: String(c), label: String(c) },
      )
    : Array.isArray(raw.headers)
      ? raw.headers.map((h) => ({ key: String(h), label: String(h) }))
      : undefined;
  const rows: Record<string, CellValue>[] = rowsRaw.map((r) => {
    if (Array.isArray(r) && columns) return Object.fromEntries(columns.map((c, i) => [c.key, (r[i] ?? null) as CellValue]));
    return isObj(r) ? (r as Record<string, CellValue>) : {};
  });
  if (!columns && rows.length) columns = Object.keys(rows[0]).map((k) => ({ key: k, label: titleCase(k) }));
  return { title: raw.title as string | undefined, caption: (raw.caption ?? raw.subtitle) as string | undefined, columns, rows };
}

export function normalizeMetrics(raw: unknown): MetricsSpec {
  if (!isObj(raw)) return {};
  const list = (Array.isArray(raw.metrics) ? raw.metrics : Array.isArray(raw.items) ? raw.items : Array.isArray(raw.kpis) ? raw.kpis : []) as unknown[];
  const metrics: Metric[] = list.filter(isObj).map((m) => ({
    label: String(m.label ?? m.name ?? m.title ?? ""),
    value: (m.value ?? m.current ?? "") as string | number,
    unit: m.unit as string | undefined,
    delta: num(m.delta ?? m.change) ?? undefined,
    deltaLabel: (m.deltaLabel ?? m.changeLabel) as string | undefined,
    status: (["good", "warning", "bad", "neutral"].includes(String(m.status)) ? m.status : undefined) as Metric["status"],
    note: m.note ? String(m.note) : m.target !== undefined ? `Target ${String(m.target)}` : undefined,
  }));
  return { title: raw.title as string | undefined, metrics };
}
