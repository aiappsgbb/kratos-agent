#!/usr/bin/env node
// azure-iot-mcp-server — stdio MCP server that mocks Azure IoT Hub / Edge for
// plant-floor demos. Surfaces device twins (spindles, conveyors, robotic arms,
// vision systems), time-series telemetry, downtime events with cause codes,
// and per-line OEE rollups (Availability × Performance × Quality).
//
// Read-only — sensor mutations aren't a write target for L1 floor work; if a
// supervisor needs to act, they raise a ServiceNow work order via the
// servicenow MCP and that skill handles the H-I-T-L gate.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

// ── Types ─────────────────────────────────────────────────────────────────

type Device = {
  id: string;
  display_name: string;
  plant_id: string;
  line: string;
  type: string;
  vendor: string;
  model: string;
  firmware: string;
  status: "Operational" | "Warning" | "Degraded" | "Faulted" | "Offline";
  last_seen_at: string;
  alarm_thresholds: Record<string, number>;
  status_note?: string;
};

type Reading = {
  timestamp: string;
  signals: Record<string, number>;
};

type Telemetry = Record<string, Reading[]>;

type DowntimeEvent = {
  id: string;
  device_id: string;
  plant_id: string;
  line: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  cause_code: string;
  cause_description: string;
  lot_id: string | null;
  related_po_id: string | null;
};

type OeeDay = {
  plant_id: string;
  line: string;
  date: string;
  availability_pct: number;
  performance_pct: number;
  quality_pct: number;
  oee_pct: number;
  target_oee_pct: number;
  units_produced: number;
  units_target: number;
};

const load = <T>(file: string): T =>
  JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;

const devices:   Device[]        = load("devices.json");
const telemetry: Telemetry       = load("telemetry.json");
const downtime:  DowntimeEvent[] = load("downtime.json");
const oee:       OeeDay[]        = load("oee.json");

// ── Helpers ───────────────────────────────────────────────────────────────

const text = (obj: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
});
const notFound = (kind: string, id: string) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id }) }],
  isError: true,
});

// All timestamps in fixture data are ISO-8601 with an explicit offset.
// We compare lexicographically against a normalised UTC instant.
const toEpoch = (iso: string) => new Date(iso).getTime();

// Compute live alarm state for a reading given the device's thresholds.
function alarms(reading: Reading, dev: Device): string[] {
  const out: string[] = [];
  for (const [k, threshold] of Object.entries(dev.alarm_thresholds)) {
    const v = reading.signals[k];
    if (typeof v === "number" && v >= threshold) {
      out.push(`${k} >= ${threshold} (actual ${v})`);
    }
  }
  return out;
}

// ── Server ────────────────────────────────────────────────────────────────

const server = new McpServer({
  name: "azure-iot-mcp-server",
  version: "0.1.0",
});

// ── Devices ───────────────────────────────────────────────────────────────

server.registerTool(
  "iot_list_devices",
  {
    title: "List IoT devices (plant-floor equipment)",
    description:
      "List Azure IoT devices on the plant floor — spindles, conveyors, robotic arms, vision systems. " +
      "Filter by plant or line. Each device carries its current status, vendor/model, firmware, " +
      "configured alarm thresholds, and a free-text status_note when not Operational. " +
      "Plant ids and line strings match `sap_list_plants` exactly so the two MCPs can be joined.",
    inputSchema: {
      plant_id: z.string().optional().describe("Filter to one plant (e.g. P-CLE)."),
      line: z.string().optional().describe('Filter to one production line (e.g. "Line 3 — Precision").'),
      status: z
        .enum(["Operational", "Warning", "Degraded", "Faulted", "Offline"])
        .optional()
        .describe("Filter by current status."),
    },
  },
  async ({ plant_id, line, status }) => {
    let pool = devices;
    if (plant_id) pool = pool.filter((d) => d.plant_id === plant_id);
    if (line)     pool = pool.filter((d) => d.line === line);
    if (status)   pool = pool.filter((d) => d.status === status);
    return text({ devices: pool, total: pool.length });
  },
);

server.registerTool(
  "iot_get_device",
  {
    title: "Get one IoT device",
    description:
      "Fetch one device by id. Returns the device twin: plant/line, vendor/model, firmware, " +
      "current status (with status_note if non-Operational), and the alarm thresholds.",
    inputSchema: { device_id: z.string().describe("Device id, e.g. DEV-3001.") },
  },
  async ({ device_id }) => {
    const d = devices.find((x) => x.id === device_id);
    return d ? text(d) : notFound("device", device_id);
  },
);

// ── Telemetry ─────────────────────────────────────────────────────────────

server.registerTool(
  "iot_get_telemetry",
  {
    title: "Get device telemetry (time-series)",
    description:
      "Return time-series sensor readings for one device, optionally bounded by an ISO timestamp window. " +
      "Readings are hourly aggregates. Each reading is annotated with `alarms` listing any signal that " +
      "met-or-exceeded the device's configured alarm threshold — use this to spot the anomaly directly " +
      "rather than re-deriving it. Default window: the full ~3-day fixture.",
    inputSchema: {
      device_id: z.string().describe("Device id, e.g. DEV-3001."),
      since: z
        .string()
        .optional()
        .describe("Inclusive lower bound, ISO-8601 with offset (e.g. 2026-06-08T00:00:00-04:00)."),
      until: z.string().optional().describe("Inclusive upper bound, ISO-8601 with offset."),
      limit: z
        .number()
        .int()
        .positive()
        .optional()
        .describe("Truncate to the most recent N readings (after window filter)."),
    },
  },
  async ({ device_id, since, until, limit }) => {
    const dev = devices.find((x) => x.id === device_id);
    if (!dev) return notFound("device", device_id);
    const all = telemetry[device_id] ?? [];
    const lo = since ? toEpoch(since) : -Infinity;
    const hi = until ? toEpoch(until) : Infinity;
    let pool = all.filter((r) => {
      const t = toEpoch(r.timestamp);
      return t >= lo && t <= hi;
    });
    if (limit && pool.length > limit) pool = pool.slice(-limit);
    const annotated = pool.map((r) => ({ ...r, alarms: alarms(r, dev) }));
    return text({
      device_id,
      device_name: dev.display_name,
      line: dev.line,
      thresholds: dev.alarm_thresholds,
      readings: annotated,
      total: annotated.length,
    });
  },
);

// ── Downtime events ───────────────────────────────────────────────────────

server.registerTool(
  "iot_list_downtime_events",
  {
    title: "List downtime events (with cause codes)",
    description:
      "List downtime events. Each event has a cause_code (e.g. VIB_ALARM, MATERIAL_HOLD_QA, CAL_DRIFT, " +
      "PLANNED_MAINT), a free-text cause_description, optional lot_id and related_po_id linking the " +
      "stop to a production order in sap-s4. Filter by plant, line, device, or ISO time window.",
    inputSchema: {
      plant_id: z.string().optional(),
      line: z.string().optional(),
      device_id: z.string().optional(),
      since: z.string().optional().describe("Inclusive lower bound, ISO-8601 with offset."),
      until: z.string().optional().describe("Inclusive upper bound, ISO-8601 with offset."),
    },
  },
  async ({ plant_id, line, device_id, since, until }) => {
    let pool = downtime;
    if (plant_id)  pool = pool.filter((e) => e.plant_id === plant_id);
    if (line)      pool = pool.filter((e) => e.line === line);
    if (device_id) pool = pool.filter((e) => e.device_id === device_id);
    if (since)     pool = pool.filter((e) => toEpoch(e.ended_at)   >= toEpoch(since));
    if (until)     pool = pool.filter((e) => toEpoch(e.started_at) <= toEpoch(until));
    pool = [...pool].sort((a, b) => (a.started_at < b.started_at ? 1 : -1));
    const total_seconds = pool.reduce((s, e) => s + e.duration_seconds, 0);
    return text({ events: pool, total: pool.length, total_seconds });
  },
);

// ── OEE rollups ──────────────────────────────────────────────────────────

server.registerTool(
  "iot_get_oee",
  {
    title: "Get OEE (Availability × Performance × Quality) per line per day",
    description:
      "Return per-line per-day OEE rollups with a `vs_target_pct` field showing the gap to the " +
      "line's target. Filter by plant, line, and date window (inclusive). " +
      "OEE = Availability × Performance × Quality, each as a fraction 0–1, reported as percent.",
    inputSchema: {
      plant_id: z.string().optional(),
      line: z.string().optional(),
      date_from: z.string().optional().describe("Inclusive lower bound, YYYY-MM-DD."),
      date_to: z.string().optional().describe("Inclusive upper bound, YYYY-MM-DD."),
    },
  },
  async ({ plant_id, line, date_from, date_to }) => {
    let pool = oee;
    if (plant_id)  pool = pool.filter((r) => r.plant_id === plant_id);
    if (line)      pool = pool.filter((r) => r.line === line);
    if (date_from) pool = pool.filter((r) => r.date >= date_from);
    if (date_to)   pool = pool.filter((r) => r.date <= date_to);
    const rows = pool.map((r) => ({
      ...r,
      vs_target_pct: +(r.oee_pct - r.target_oee_pct).toFixed(1),
      flag:
        r.oee_pct - r.target_oee_pct >= 0
          ? "on_target"
          : r.oee_pct - r.target_oee_pct >= -5
            ? "watch"
            : "investigate",
    }));
    return text({ oee: rows, total: rows.length });
  },
);

// ── Boot ──────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
