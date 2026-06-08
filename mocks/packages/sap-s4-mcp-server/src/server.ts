#!/usr/bin/env node
// sap-s4-mcp-server — stdio MCP server that mocks SAP S/4HANA (Finance + Materials).
// Cost centres, GL accounts, journal entries (with variance + draft surfaces),
// vendors (with sanctioned/credit-rating signals), plants, materials with stock
// + safety-stock, and production orders with scrap-rate issue flags. Includes
// write tools for proposing & posting journal entries — agent must confirm
// with the user before posting.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

// ── Types ─────────────────────────────────────────────────────────────────

type CostCentre = {
  id: string; name: string; function: string;
  owner_user_id: string; budget_usd: number; ytd_actual_usd: number; currency: string;
};
type GLAccount = {
  code: string; name: string;
  type: "Asset" | "Liability" | "Revenue" | "COGS" | "OpEx" | "Other";
  normal_balance: "debit" | "credit";
  ytd_actual_usd: number; prior_year_usd: number;
};
type JELine = {
  gl_account: string; cost_centre: string | null;
  debit_usd: number; credit_usd: number; memo: string;
};
type JournalEntry = {
  id: string; posting_date: string; period: string;
  type: "Standard" | "Accrual" | "Reclass" | "Manual";
  status: "Draft" | "Posted" | "Reversed";
  source: "AP" | "AR" | "MM" | "FI" | "HR";
  currency: string; lines: JELine[];
};
type Vendor = {
  id: string; name: string; country: string;
  sanctioned: boolean; credit_rating: string; payment_terms_days: number;
  tax_id: string; primary_category: string; default_currency: string;
  active: boolean; blocked_for_posting: boolean;
  ytd_spend_usd: number; block_reason?: string;
};
type Plant = {
  id: string; name: string; country: string; city: string;
  lines: string[]; default_currency: string;
};
type Material = {
  id: string; name: string; type: "Raw" | "Component" | "Finished";
  uom: string; stock_qty: number; safety_stock_qty: number;
  preferred_vendor: string | null; unit_cost_usd: number;
};
type ProductionOrder = {
  id: string; plant_id: string; material_id: string;
  qty_ordered: number; qty_produced: number; qty_scrap: number;
  status: "Released" | "In Process" | "Completed" | "Issue" | "Cancelled";
  scheduled_start: string; scheduled_end: string;
  actual_start?: string; actual_end?: string;
  line: string; issue?: string;
};

const load = <T>(file: string): T =>
  JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;

const costCentres:      CostCentre[]      = load("cost_centres.json");
const glAccounts:       GLAccount[]       = load("gl_accounts.json");
const journalEntries:   JournalEntry[]    = load("journal_entries.json");
const vendors:          Vendor[]          = load("vendors.json");
const plants:           Plant[]           = load("plants.json");
const materials:        Material[]        = load("materials.json");
const productionOrders: ProductionOrder[] = load("production_orders.json");

let nextJESeq = 39000;

const text = (obj: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
});
const notFound = (kind: string, id: string) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id }) }],
  isError: true,
});

const server = new McpServer({
  name: "sap-s4-mcp-server",
  version: "0.1.0",
});

// ── Cost centres ──────────────────────────────────────────────────────────

server.registerTool(
  "sap_list_cost_centres",
  {
    title: "List cost centres",
    description:
      "List cost centres. Each carries the owner (workday EMP-* id), the YTD actual " +
      "and the budget. Use to scope variance analysis or close-package generation.",
    inputSchema: {
      function: z.string().optional().describe("Filter by function (e.g. 'Engineering')."),
      owner_user_id: z.string().optional().describe("Filter by owning manager EMP-* id."),
    },
  },
  async ({ function: fn, owner_user_id }) => {
    let pool = costCentres;
    if (fn) pool = pool.filter((c) => c.function === fn);
    if (owner_user_id) pool = pool.filter((c) => c.owner_user_id === owner_user_id);
    return text({ cost_centres: pool, total: pool.length });
  }
);

server.registerTool(
  "sap_get_cost_centre",
  {
    title: "Get one cost centre",
    description: "Fetch a cost centre by id including YTD spend vs budget.",
    inputSchema: { cost_centre_id: z.string().describe("Cost centre id, e.g. CC-0011.") },
  },
  async ({ cost_centre_id }) => {
    const c = costCentres.find((x) => x.id === cost_centre_id);
    return c ? text(c) : notFound("cost_centre", cost_centre_id);
  }
);

// ── GL accounts + variance ────────────────────────────────────────────────

server.registerTool(
  "sap_list_gl_accounts",
  {
    title: "List GL accounts",
    description: "List GL accounts with YTD actual and prior-year comparison. Filter by type or text.",
    inputSchema: {
      type: z.enum(["Asset", "Liability", "Revenue", "COGS", "OpEx", "Other"]).optional(),
      query: z.string().optional().describe("Substring match against code or name."),
    },
  },
  async ({ type, query }) => {
    let pool = glAccounts;
    if (type) pool = pool.filter((a) => a.type === type);
    if (query) {
      const q = query.toLowerCase();
      pool = pool.filter((a) => a.code.includes(q) || a.name.toLowerCase().includes(q));
    }
    return text({ gl_accounts: pool, total: pool.length });
  }
);

server.registerTool(
  "sap_get_variance_analysis",
  {
    title: "GL account variance (YTD vs prior year)",
    description:
      "Return YTD-vs-prior-year variance for one or all GL accounts. Includes absolute and " +
      "% variance plus a 'flag' string of 'normal' / 'watch' / 'investigate' based on a 25%/50% threshold. " +
      "Use as the headline lookup for month-end close variance review.",
    inputSchema: {
      gl_code: z.string().optional().describe("Optional GL code to analyse (e.g. '6200'). Omit for all."),
      threshold_watch_pct: z.number().optional().describe("% variance considered 'watch'. Default 25."),
      threshold_investigate_pct: z.number().optional().describe("% variance considered 'investigate'. Default 50."),
    },
  },
  async ({ gl_code, threshold_watch_pct, threshold_investigate_pct }) => {
    const w = threshold_watch_pct ?? 25;
    const i = threshold_investigate_pct ?? 50;
    const pool = gl_code ? glAccounts.filter((a) => a.code === gl_code) : glAccounts;
    if (gl_code && pool.length === 0) return notFound("gl_account", gl_code);
    const rows = pool.map((a) => {
      const prior = a.prior_year_usd;
      const absVar = a.ytd_actual_usd - prior;
      const pctVar = prior !== 0 ? (absVar / Math.abs(prior)) * 100 : 0;
      const absPct = Math.abs(pctVar);
      const flag = absPct >= i ? "investigate" : absPct >= w ? "watch" : "normal";
      return {
        gl_code: a.code, gl_name: a.name, type: a.type,
        ytd_actual_usd: a.ytd_actual_usd, prior_year_usd: prior,
        variance_usd: absVar,
        variance_pct: +pctVar.toFixed(1),
        flag,
      };
    });
    return text({ variances: rows, total: rows.length });
  }
);

// ── Journal entries ───────────────────────────────────────────────────────

server.registerTool(
  "sap_list_journal_entries",
  {
    title: "List journal entries",
    description:
      "List journal entries with filters by period, status, source, type, or referenced GL/cost-centre. " +
      "Default returns newest first.",
    inputSchema: {
      period: z.string().optional().describe("e.g. '2026-05' (YYYY-MM)."),
      status: z.enum(["Draft", "Posted", "Reversed"]).optional(),
      source: z.enum(["AP", "AR", "MM", "FI", "HR"]).optional(),
      type: z.enum(["Standard", "Accrual", "Reclass", "Manual"]).optional(),
      gl_account: z.string().optional().describe("Filter to JEs that touch this GL code."),
      cost_centre: z.string().optional().describe("Filter to JEs that touch this cost centre."),
      limit: z.number().int().min(1).max(200).optional(),
    },
  },
  async ({ period, status, source, type, gl_account, cost_centre, limit }) => {
    let pool = journalEntries;
    if (period) pool = pool.filter((j) => j.period === period);
    if (status) pool = pool.filter((j) => j.status === status);
    if (source) pool = pool.filter((j) => j.source === source);
    if (type) pool = pool.filter((j) => j.type === type);
    if (gl_account) pool = pool.filter((j) => j.lines.some((l) => l.gl_account === gl_account));
    if (cost_centre) pool = pool.filter((j) => j.lines.some((l) => l.cost_centre === cost_centre));
    pool = [...pool].sort((a, b) => b.posting_date.localeCompare(a.posting_date));
    return text({ journal_entries: pool.slice(0, limit ?? 50), total: pool.length });
  }
);

server.registerTool(
  "sap_get_journal_entry",
  {
    title: "Get one journal entry",
    description: "Fetch one journal entry by id with all lines.",
    inputSchema: { je_id: z.string().describe("Journal entry id, e.g. JE-30001.") },
  },
  async ({ je_id }) => {
    const j = journalEntries.find((x) => x.id === je_id);
    return j ? text(j) : notFound("journal_entry", je_id);
  }
);

server.registerTool(
  "sap_propose_journal_entry",
  {
    title: "Propose a journal entry (creates as Draft)",
    description:
      "Propose a new journal entry — creates it in Draft state, validates that debits == credits " +
      "and that referenced GL codes + cost centres exist. The agent should show the proposal to " +
      "the user and ask_user before posting. The Draft JE id is returned so a subsequent " +
      "sap_post_journal_entry call can promote it to Posted.",
    inputSchema: {
      posting_date: z.string().describe("ISO date, e.g. 2026-06-01."),
      period: z.string().describe("YYYY-MM, e.g. 2026-06."),
      type: z.enum(["Standard", "Accrual", "Reclass", "Manual"]),
      source: z.enum(["AP", "AR", "MM", "FI", "HR"]).default("FI"),
      currency: z.string().default("USD"),
      lines: z.array(z.object({
        gl_account: z.string(),
        cost_centre: z.string().nullable(),
        debit_usd: z.number().min(0),
        credit_usd: z.number().min(0),
        memo: z.string(),
      })).min(2),
    },
  },
  async (args) => {
    const totalDr = args.lines.reduce((s, l) => s + l.debit_usd, 0);
    const totalCr = args.lines.reduce((s, l) => s + l.credit_usd, 0);
    if (Math.abs(totalDr - totalCr) > 0.005) {
      return { content: [{ type: "text", text: JSON.stringify({ error: "unbalanced", total_dr: totalDr, total_cr: totalCr }) }], isError: true };
    }
    for (const l of args.lines) {
      if (!glAccounts.find((a) => a.code === l.gl_account)) {
        return { content: [{ type: "text", text: JSON.stringify({ error: "unknown_gl_account", gl_account: l.gl_account }) }], isError: true };
      }
      if (l.cost_centre && !costCentres.find((c) => c.id === l.cost_centre)) {
        return { content: [{ type: "text", text: JSON.stringify({ error: "unknown_cost_centre", cost_centre: l.cost_centre }) }], isError: true };
      }
    }
    const je: JournalEntry = {
      id: `JE-${++nextJESeq}`, posting_date: args.posting_date, period: args.period,
      type: args.type, status: "Draft", source: args.source, currency: args.currency,
      lines: args.lines,
    };
    journalEntries.push(je);
    return text({ ok: true, draft: je });
  }
);

server.registerTool(
  "sap_post_journal_entry",
  {
    title: "Post a Draft journal entry",
    description:
      "Promote a Draft journal entry to Posted. Agent must have shown the JE and received " +
      "explicit ask_user confirmation before calling this tool.",
    inputSchema: { je_id: z.string() },
  },
  async ({ je_id }) => {
    const j = journalEntries.find((x) => x.id === je_id);
    if (!j) return notFound("journal_entry", je_id);
    if (j.status !== "Draft") {
      return { content: [{ type: "text", text: JSON.stringify({ error: "not_draft", current_status: j.status }) }], isError: true };
    }
    j.status = "Posted";
    return text({ ok: true, posted: j });
  }
);

// ── Vendors ───────────────────────────────────────────────────────────────

server.registerTool(
  "sap_search_vendors_by_name",
  {
    title: "Search vendors by name",
    description: "Case-insensitive substring match on vendor name. Use to resolve a supplier before drilling in.",
    inputSchema: { query: z.string().min(1) },
  },
  async ({ query }) => {
    const q = query.toLowerCase();
    const matches = vendors.filter((v) => v.name.toLowerCase().includes(q));
    return text({ matches, total: matches.length });
  }
);

server.registerTool(
  "sap_get_vendor",
  {
    title: "Get one vendor",
    description: "Fetch a vendor by id including sanctioned flag, credit rating, posting block status, and YTD spend.",
    inputSchema: { vendor_id: z.string().describe("Vendor id, e.g. V-1001.") },
  },
  async ({ vendor_id }) => {
    const v = vendors.find((x) => x.id === vendor_id);
    return v ? text(v) : notFound("vendor", vendor_id);
  }
);

// ── Plants + materials + production ───────────────────────────────────────

server.registerTool(
  "sap_list_plants",
  {
    title: "List plants",
    description: "List all plants with their lines.",
    inputSchema: {},
  },
  async () => text({ plants, total: plants.length })
);

server.registerTool(
  "sap_list_materials",
  {
    title: "List materials",
    description:
      "List materials. Each row carries stock_qty + safety_stock_qty so the agent can flag " +
      "items below safety stock as risks.",
    inputSchema: {
      type: z.enum(["Raw", "Component", "Finished"]).optional(),
      below_safety_stock_only: z.boolean().optional().describe("If true, only return materials where stock < safety stock."),
    },
  },
  async ({ type, below_safety_stock_only }) => {
    let pool = materials;
    if (type) pool = pool.filter((m) => m.type === type);
    if (below_safety_stock_only) pool = pool.filter((m) => m.stock_qty < m.safety_stock_qty);
    return text({ materials: pool, total: pool.length });
  }
);

server.registerTool(
  "sap_list_production_orders",
  {
    title: "List production orders",
    description:
      "List production orders with optional filter by plant, status, or scheduled-end date range. " +
      "Use to find orders with quality issues (status='Issue').",
    inputSchema: {
      plant_id: z.string().optional(),
      status: z.enum(["Released", "In Process", "Completed", "Issue", "Cancelled"]).optional(),
      end_from: z.string().optional().describe("ISO date inclusive."),
      end_to: z.string().optional().describe("ISO date inclusive."),
    },
  },
  async ({ plant_id, status, end_from, end_to }) => {
    let pool = productionOrders;
    if (plant_id) pool = pool.filter((p) => p.plant_id === plant_id);
    if (status)   pool = pool.filter((p) => p.status === status);
    if (end_from) pool = pool.filter((p) => p.scheduled_end >= end_from);
    if (end_to)   pool = pool.filter((p) => p.scheduled_end <= end_to);
    return text({ production_orders: pool, total: pool.length });
  }
);

server.registerTool(
  "sap_get_production_order",
  {
    title: "Get one production order",
    description: "Fetch a production order by id including any 'issue' text.",
    inputSchema: { po_id: z.string().describe("Production order id, e.g. PO-9001.") },
  },
  async ({ po_id }) => {
    const p = productionOrders.find((x) => x.id === po_id);
    return p ? text(p) : notFound("production_order", po_id);
  }
);

// ── Boot ──────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
