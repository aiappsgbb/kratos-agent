#!/usr/bin/env node
// salesforce-mcp-server — stdio MCP server that mocks a Salesforce CRM
// against curated JSON fixtures. Tools mirror the most common AE workflows
// (account briefing, pipeline review, contact rolodex, activity timeline,
// case status). All data is fictional.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

type Account = {
  id: string; name: string; industry: string; website: string;
  hq_location: string; employees: number; annual_revenue_usd: number;
  tier: "Strategic" | "Enterprise" | "Mid-Market" | "SMB";
  health: "Green" | "Yellow" | "Red";
  owner_user_id: string; csm_user_id: string | null; se_user_id: string | null;
  customer_since: string; arr_committed_usd: number; renewal_date: string;
  primary_product: string; description: string;
};
type Opportunity = {
  id: string; account_id: string; name: string; stage: string;
  amount_usd: number; probability: number; close_date: string;
  owner_user_id: string; type: string; next_step: string;
  competitors: string[]; created_date: string;
};
type Contact = {
  id: string; account_id: string; first_name: string; last_name: string;
  title: string; email: string; phone: string;
  is_primary: boolean; role: string;
};
type Activity = {
  id: string; account_id: string; type: string; subject: string;
  date: string; owner_user_id: string; summary: string;
};
type Case = {
  id: string; account_id: string; subject: string; priority: string;
  status: string; opened_date: string; owner_user_id: string; summary: string;
};
type User = { id: string; name: string; role: string; email: string };

const load = <T>(file: string): T =>
  JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;

const accounts      = load<Account[]>("accounts.json");
const opportunities = load<Opportunity[]>("opportunities.json");
const contacts      = load<Contact[]>("contacts.json");
const activities    = load<Activity[]>("activities.json");
const cases         = load<Case[]>("cases.json");
const users         = load<User[]>("users.json");

const text = (obj: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
});
const notFound = (kind: string, id: string) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id }) }],
  isError: true,
});

const server = new McpServer({
  name: "salesforce-mcp-server",
  version: "0.1.0",
});

// ── Accounts ──────────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_list_accounts",
  {
    title: "List Salesforce accounts",
    description:
      "List accounts with optional filters. Useful for browsing the book of business " +
      "before drilling into a specific account.",
    inputSchema: {
      tier: z.enum(["Strategic", "Enterprise", "Mid-Market", "SMB"]).optional()
        .describe("Filter by account tier."),
      health: z.enum(["Green", "Yellow", "Red"]).optional()
        .describe("Filter by health status."),
      owner_user_id: z.string().optional()
        .describe("Filter by owning rep user id (e.g. USR-101)."),
      limit: z.number().int().min(1).max(100).optional()
        .describe("Max accounts to return (default 25)."),
    },
  },
  async ({ tier, health, owner_user_id, limit }) => {
    let pool = accounts;
    if (tier) pool = pool.filter((a) => a.tier === tier);
    if (health) pool = pool.filter((a) => a.health === health);
    if (owner_user_id) pool = pool.filter((a) => a.owner_user_id === owner_user_id);
    return text({ accounts: pool.slice(0, limit ?? 25), total: pool.length });
  }
);

server.registerTool(
  "salesforce_search_accounts_by_name",
  {
    title: "Search accounts by name",
    description: "Case-insensitive substring match on account name. Use when the user mentions a company by name.",
    inputSchema: {
      query: z.string().min(1).describe("Substring to match against account name."),
    },
  },
  async ({ query }) => {
    const q = query.toLowerCase();
    const matches = accounts.filter((a) => a.name.toLowerCase().includes(q));
    return text({ matches });
  }
);

server.registerTool(
  "salesforce_get_account",
  {
    title: "Get one account",
    description:
      "Fetch an account by id. Returns the full record including tier, health, owner, " +
      "renewal date, and ARR. Use after a name search to get the full picture.",
    inputSchema: {
      account_id: z.string().describe("Account id, e.g. ACC-001."),
    },
  },
  async ({ account_id }) => {
    const a = accounts.find((x) => x.id === account_id);
    return a ? text(a) : notFound("account", account_id);
  }
);

// ── Opportunities ─────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_list_opportunities",
  {
    title: "List opportunities",
    description:
      "List opportunities, optionally scoped to one account or filtered by stage/owner. " +
      "Use to assess pipeline before a call.",
    inputSchema: {
      account_id: z.string().optional().describe("Restrict to one account."),
      stage: z.string().optional()
        .describe("Filter by stage (Prospecting, Qualification, Proposal, Negotiation, Closed Won, Closed Lost)."),
      owner_user_id: z.string().optional().describe("Filter by rep."),
      open_only: z.boolean().optional()
        .describe("If true, exclude Closed Won / Closed Lost."),
    },
  },
  async ({ account_id, stage, owner_user_id, open_only }) => {
    let pool = opportunities;
    if (account_id) pool = pool.filter((o) => o.account_id === account_id);
    if (stage) pool = pool.filter((o) => o.stage === stage);
    if (owner_user_id) pool = pool.filter((o) => o.owner_user_id === owner_user_id);
    if (open_only) pool = pool.filter((o) => !o.stage.startsWith("Closed"));
    return text({ opportunities: pool, total: pool.length });
  }
);

server.registerTool(
  "salesforce_get_opportunity",
  {
    title: "Get one opportunity",
    description: "Fetch a single opportunity by id including next step and competitors.",
    inputSchema: {
      opportunity_id: z.string().describe("Opportunity id, e.g. OPP-1001."),
    },
  },
  async ({ opportunity_id }) => {
    const o = opportunities.find((x) => x.id === opportunity_id);
    return o ? text(o) : notFound("opportunity", opportunity_id);
  }
);

// ── Contacts ──────────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_list_contacts_by_account",
  {
    title: "List contacts for an account",
    description: "Return the contact rolodex for an account — names, titles, roles, primary flag.",
    inputSchema: {
      account_id: z.string().describe("Account id, e.g. ACC-001."),
    },
  },
  async ({ account_id }) => {
    const matches = contacts.filter((c) => c.account_id === account_id);
    return text({ contacts: matches, total: matches.length });
  }
);

// ── Activities ────────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_list_activities_by_account",
  {
    title: "List recent activities for an account",
    description:
      "Return calls, meetings, and emails logged against an account, newest first. " +
      "Use to brief on what's happened lately before reaching out.",
    inputSchema: {
      account_id: z.string().describe("Account id, e.g. ACC-001."),
      limit: z.number().int().min(1).max(50).optional()
        .describe("Max activities to return (default 10)."),
    },
  },
  async ({ account_id, limit }) => {
    const matches = activities
      .filter((a) => a.account_id === account_id)
      .sort((a, b) => b.date.localeCompare(a.date));
    return text({ activities: matches.slice(0, limit ?? 10), total: matches.length });
  }
);

// ── Cases ─────────────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_list_open_cases_by_account",
  {
    title: "List support cases for an account",
    description:
      "Return support cases (open by default) for an account. Critical for spotting " +
      "at-risk signals before a renewal or expansion conversation.",
    inputSchema: {
      account_id: z.string().describe("Account id, e.g. ACC-001."),
      include_resolved: z.boolean().optional()
        .describe("If true, include resolved cases as well."),
    },
  },
  async ({ account_id, include_resolved }) => {
    let matches = cases.filter((c) => c.account_id === account_id);
    if (!include_resolved) matches = matches.filter((c) => c.status !== "Resolved");
    return text({ cases: matches, total: matches.length });
  }
);

// ── Users ─────────────────────────────────────────────────────────────────

server.registerTool(
  "salesforce_get_user",
  {
    title: "Get a Salesforce user",
    description: "Resolve a user id (rep, CSM, SE, support engineer) to name + role + email.",
    inputSchema: {
      user_id: z.string().describe("User id, e.g. USR-101."),
    },
  },
  async ({ user_id }) => {
    const u = users.find((x) => x.id === user_id);
    return u ? text(u) : notFound("user", user_id);
  }
);

// ── Boot ──────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
