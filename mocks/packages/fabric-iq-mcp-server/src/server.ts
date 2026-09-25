#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

type Site = { id: string; name: string; region: string; status: "Healthy" | "Watch" | "Critical" | "Offline"; timezone: string; output_target_units_per_day: number; notes: string; };
type Line = { id: string; site_id: string; name: string; product_family: string; status: "Healthy" | "Watch" | "Critical" | "Offline"; availability_pct: number; performance_pct: number; quality_pct: number; oee_pct: number; throughput_per_hr: number; target_output_per_hr: number; last_updated: string; };
type Asset = { id: string; site_id: string; line_id: string; name: string; asset_type: string; manufacturer: string; model: string; criticality: "Critical" | "High" | "Medium"; status: "Healthy" | "Watch" | "Critical" | "Offline"; health_pct: number; last_service_at: string; next_service_at: string; tags: string[]; };
type TelemetrySample = { timestamp: string; asset_id: string; metrics: { temperature_c: number; vibration_mm_s: number; pressure_bar: number; flow_lpm: number; current_amp: number; efficiency_pct: number; }; };
type AlarmEvent = { id: string; site_id: string; line_id: string; asset_id: string; code: string; severity: "Info" | "Low" | "Medium" | "High" | "Critical"; status: "Active" | "Acknowledged" | "Cleared"; started_at: string; cleared_at: string | null; description: string; recommended_action: string; };
type OeeDay = { date: string; line_id: string; site_id: string; availability_pct: number; performance_pct: number; quality_pct: number; oee_pct: number; target_oee_pct: number; units_produced: number; };

const load = <T>(file: string): T => JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;
const sites: Site[] = load("sites.json");
const lines: Line[] = load("lines.json");
const assets: Asset[] = load("assets.json");
const telemetry: TelemetrySample[] = load("telemetry.json");
const alarms: AlarmEvent[] = load("alarms.json");
const oee: OeeDay[] = load("oee.json");

const withSimulationNote = <T>(obj: T) => ({ ...(obj as object), simulation_only: true });
const text = (obj: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(withSimulationNote(obj), null, 2) }] });
const notFound = (kind: string, id: string) => ({ content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id, simulation_only: true }, null, 2) }], isError: true });
const toEpoch = (iso: string) => new Date(iso).getTime();
const server = new McpServer({ name: "fabric-iq-mcp-server", version: "0.1.0" });

server.registerTool(
  "fabric_iq_list_lines",
  {
    title: "List synthetic production lines",
    description: "List synthetic plant lines with line health and site context. Output is simulation-only fixture data.",
    inputSchema: {
      site_id: z.string().optional().describe("Filter to a single site."),
      status: z.enum(["Healthy", "Watch", "Critical", "Offline"]).optional().describe("Filter by line status."),
      product_family: z.string().optional().describe("Case-insensitive filter by product family."),
    },
  },
  async ({ site_id, status, product_family }) => {
    let pool = lines;
    if (site_id) pool = pool.filter((line) => line.site_id === site_id);
    if (status) pool = pool.filter((line) => line.status === status);
    if (product_family) pool = pool.filter((line) => line.product_family.toLowerCase().includes(product_family.toLowerCase()));
    return text({
      lines: pool.map((line) => ({
        ...line,
        site: sites.find((site) => site.id === line.site_id) ?? null,
      })),
      total: pool.length,
    });
  },
);

server.registerTool(
  "fabric_iq_get_oee",
  {
    title: "Get synthetic OEE rollups",
    description: "Return OEE for a line or site within a date window. Output is simulation-only fixture data.",
    inputSchema: {
      line_id: z.string().optional().describe("Filter to one line."),
      site_id: z.string().optional().describe("Filter to one site."),
      date_from: z.string().optional().describe("Inclusive start date (YYYY-MM-DD)."),
      date_to: z.string().optional().describe("Inclusive end date (YYYY-MM-DD)."),
    },
  },
  async ({ line_id, site_id, date_from, date_to }) => {
    let pool = oee;
    if (line_id) pool = pool.filter((entry) => entry.line_id === line_id);
    if (site_id) pool = pool.filter((entry) => entry.site_id === site_id);
    if (date_from) pool = pool.filter((entry) => entry.date >= date_from);
    if (date_to) pool = pool.filter((entry) => entry.date <= date_to);
    return text({ oee: pool, total: pool.length });
  },
);

server.registerTool(
  "fabric_iq_get_asset_status",
  {
    title: "Get asset health and maintenance status",
    description: "Retrieve the current synthetic status, maintenance windows, and site context for one asset.",
    inputSchema: { asset_id: z.string().describe("Asset id, e.g. ASSET-1204.") },
  },
  async ({ asset_id }) => {
    const asset = assets.find((entry) => entry.id === asset_id);
    if (!asset) return notFound("asset", asset_id);
    const line = lines.find((entry) => entry.id === asset.line_id);
    const site = sites.find((entry) => entry.id === asset.site_id);
    return text({ asset, line, site });
  },
);

server.registerTool(
  "fabric_iq_get_telemetry",
  {
    title: "Get synthetic telemetry",
    description: "Return time-series telemetry for one asset, with optional window and limit filters.",
    inputSchema: {
      asset_id: z.string().describe("Asset id."),
      since: z.string().optional().describe("Inclusive lower bound ISO-8601 timestamp."),
      until: z.string().optional().describe("Inclusive upper bound ISO-8601 timestamp."),
      limit: z.number().int().positive().optional().describe("Maximum readings to return."),
    },
  },
  async ({ asset_id, since, until, limit }) => {
    const asset = assets.find((entry) => entry.id === asset_id);
    if (!asset) return notFound("asset", asset_id);
    let pool = telemetry.filter((sample) => sample.asset_id === asset_id);
    if (since) pool = pool.filter((sample) => toEpoch(sample.timestamp) >= toEpoch(since));
    if (until) pool = pool.filter((sample) => toEpoch(sample.timestamp) <= toEpoch(until));
    if (limit) pool = pool.slice(-limit);
    return text({ asset_id, asset_name: asset.name, total: pool.length, readings: pool });
  },
);

server.registerTool(
  "fabric_iq_list_alarms",
  {
    title: "List synthetic alarms",
    description: "List alarm events with severity, status, and recommended action. Output is simulation-only fixture data.",
    inputSchema: {
      site_id: z.string().optional(),
      line_id: z.string().optional(),
      asset_id: z.string().optional(),
      status: z.enum(["Active", "Acknowledged", "Cleared"]).optional(),
      severity: z.enum(["Info", "Low", "Medium", "High", "Critical"]).optional(),
      since: z.string().optional(),
      until: z.string().optional(),
    },
  },
  async ({ site_id, line_id, asset_id, status, severity, since, until }) => {
    let pool = alarms;
    if (site_id) pool = pool.filter((entry) => entry.site_id === site_id);
    if (line_id) pool = pool.filter((entry) => entry.line_id === line_id);
    if (asset_id) pool = pool.filter((entry) => entry.asset_id === asset_id);
    if (status) pool = pool.filter((entry) => entry.status === status);
    if (severity) pool = pool.filter((entry) => entry.severity === severity);
    if (since) pool = pool.filter((entry) => toEpoch(entry.started_at) >= toEpoch(since));
    if (until) pool = pool.filter((entry) => entry.cleared_at ? toEpoch(entry.cleared_at) <= toEpoch(until) : true);
    return text({ alarms: pool, total: pool.length });
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
