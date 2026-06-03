#!/usr/bin/env node
// workday-mcp-server — stdio MCP server that mocks Workday HCM against
// curated JSON fixtures. Tools cover the employee/org/position model plus
// time-off, shifts, payroll, and the most common write workflows
// (create employee, submit/approve time-off, transfer position). All data
// is fictional; writes mutate in-memory state for the lifetime of the
// process so multi-turn demos see consistent results.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

// ── Types ─────────────────────────────────────────────────────────────────

type Organization = {
  id: string; name: string;
  type: "Company" | "Function" | "Department" | "Team";
  parent_org_id: string | null;
  head_employee_id: string | null;
  cost_centre: string;
};
type Position = {
  id: string; title: string; org_id: string;
  job_family: string; level: string; fte: number;
  status: "Filled" | "Open" | "Closed";
  filled_by: string | null;
  open_since?: string; target_start?: string; hiring_manager_id?: string;
};
type Employee = {
  id: string; first_name: string; last_name: string; preferred_name: string;
  work_email: string; personal_email: string; phone: string;
  position_id: string | null; org_id: string;
  manager_id: string | null; location: string; country: string;
  employment_type: "Regular" | "Contractor" | "Intern";
  status: "Active" | "On Leave" | "Terminated" | "Pre-Hire";
  hire_date: string; termination_date: string | null;
  annual_salary_usd: number; currency: string;
};
type TimeOff = {
  id: string; employee_id: string;
  type: string; start_date: string; end_date: string; days: number;
  status: "Pending" | "Approved" | "Denied" | "Cancelled";
  approver_id: string; submitted_at: string; reason: string;
  decided_at?: string; decision_note?: string;
};
type PayrollRecord = {
  id: string; employee_id: string;
  pay_period_start: string; pay_period_end: string;
  gross_usd: number; net_usd: number;
  deductions_usd: number; taxes_usd: number; benefits_usd: number;
  paid_on: string;
};
type Shift = {
  id: string; employee_id: string;
  date: string; start_time: string; end_time: string;
  location: string; role: string;
  status: "Scheduled" | "Completed" | "Missed" | "Cancelled";
};

// ── Load fixtures into mutable in-memory store ────────────────────────────

const load = <T>(file: string): T =>
  JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;

const organizations: Organization[] = load("organizations.json");
const positions:     Position[]     = load("positions.json");
const employees:     Employee[]     = load("employees.json");
const timeOff:       TimeOff[]      = load("time_off.json");
const payroll:       PayrollRecord[]= load("payroll.json");
const shifts:        Shift[]        = load("shifts.json");

// Per-process ID counters so write tools generate plausible IDs that don't
// collide with the seeded fixtures.
let nextEmpSeq = 9000;
let nextPtoSeq = 9000;

// ── Helpers ───────────────────────────────────────────────────────────────

const text = (obj: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
});
const notFound = (kind: string, id: string) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id }) }],
  isError: true,
});

const today = () => new Date().toISOString().slice(0, 10);

// ── Server ────────────────────────────────────────────────────────────────

const server = new McpServer({
  name: "workday-mcp-server",
  version: "0.1.0",
});

// ── Organizations ─────────────────────────────────────────────────────────

server.registerTool(
  "workday_list_organizations",
  {
    title: "List organizations",
    description: "List org units (company, function, department, team). Useful for org-chart navigation.",
    inputSchema: {
      type: z.enum(["Company", "Function", "Department", "Team"]).optional()
        .describe("Filter to one org type."),
      parent_org_id: z.string().optional()
        .describe("Filter to direct children of a parent org id."),
    },
  },
  async ({ type, parent_org_id }) => {
    let pool = organizations;
    if (type) pool = pool.filter((o) => o.type === type);
    if (parent_org_id) pool = pool.filter((o) => o.parent_org_id === parent_org_id);
    return text({ organizations: pool, total: pool.length });
  }
);

server.registerTool(
  "workday_get_organization",
  {
    title: "Get one organization",
    description: "Fetch an org unit by id including the head employee + cost centre.",
    inputSchema: { org_id: z.string().describe("Organization id, e.g. ORG-011.") },
  },
  async ({ org_id }) => {
    const o = organizations.find((x) => x.id === org_id);
    return o ? text(o) : notFound("organization", org_id);
  }
);

// ── Positions ─────────────────────────────────────────────────────────────

server.registerTool(
  "workday_list_positions",
  {
    title: "List positions (open or filled)",
    description:
      "List positions with optional filters. Use status='Open' to find req's that need hiring; " +
      "pair with org_id or hiring_manager_id to scope.",
    inputSchema: {
      status: z.enum(["Filled", "Open", "Closed"]).optional(),
      org_id: z.string().optional().describe("Restrict to one org."),
      hiring_manager_id: z.string().optional().describe("Open positions owned by a manager."),
    },
  },
  async ({ status, org_id, hiring_manager_id }) => {
    let pool = positions;
    if (status) pool = pool.filter((p) => p.status === status);
    if (org_id) pool = pool.filter((p) => p.org_id === org_id);
    if (hiring_manager_id) pool = pool.filter((p) => p.hiring_manager_id === hiring_manager_id);
    return text({ positions: pool, total: pool.length });
  }
);

server.registerTool(
  "workday_get_position",
  {
    title: "Get one position",
    description: "Fetch a position by id including job family, level, and fill status.",
    inputSchema: { position_id: z.string().describe("Position id, e.g. POS-2103.") },
  },
  async ({ position_id }) => {
    const p = positions.find((x) => x.id === position_id);
    return p ? text(p) : notFound("position", position_id);
  }
);

// ── Employees ─────────────────────────────────────────────────────────────

server.registerTool(
  "workday_search_employees_by_name",
  {
    title: "Search employees by name",
    description: "Case-insensitive substring match on first/last/preferred name + work email.",
    inputSchema: {
      query: z.string().min(1).describe("Substring to match."),
    },
  },
  async ({ query }) => {
    const q = query.toLowerCase();
    const matches = employees.filter((e) =>
      e.first_name.toLowerCase().includes(q) ||
      e.last_name.toLowerCase().includes(q) ||
      e.preferred_name.toLowerCase().includes(q) ||
      e.work_email.toLowerCase().includes(q)
    );
    return text({ matches, total: matches.length });
  }
);

server.registerTool(
  "workday_get_employee",
  {
    title: "Get one employee",
    description: "Fetch an employee by id including position, org, manager, and salary.",
    inputSchema: { employee_id: z.string().describe("Employee id, e.g. EMP-2001.") },
  },
  async ({ employee_id }) => {
    const e = employees.find((x) => x.id === employee_id);
    return e ? text(e) : notFound("employee", employee_id);
  }
);

server.registerTool(
  "workday_list_employees_by_manager",
  {
    title: "List direct reports",
    description: "Return the direct reports of a manager. Use to assemble a team roster.",
    inputSchema: {
      manager_id: z.string().describe("Manager's employee id."),
      include_on_leave: z.boolean().optional().describe("Default true — set false to exclude On Leave."),
    },
  },
  async ({ manager_id, include_on_leave }) => {
    const includeLeave = include_on_leave ?? true;
    const reports = employees.filter((e) =>
      e.manager_id === manager_id &&
      (includeLeave || e.status !== "On Leave")
    );
    return text({ reports, total: reports.length });
  }
);

server.registerTool(
  "workday_create_employee",
  {
    title: "Create a new employee (pre-hire / onboarding)",
    description:
      "Create a Pre-Hire employee record. Returns the seeded EMP-* id which downstream " +
      "tools (IT provisioning, calendar, payroll setup) should reference. The position must " +
      "exist and be Open. The new employee starts in 'Pre-Hire' status until their hire_date.",
    inputSchema: {
      first_name: z.string().min(1),
      last_name: z.string().min(1),
      preferred_name: z.string().optional(),
      personal_email: z.string().email(),
      phone: z.string().optional(),
      position_id: z.string().describe("Open position to fill, e.g. POS-2103."),
      manager_id: z.string().describe("Manager's employee id."),
      hire_date: z.string().describe("Planned first day, ISO date e.g. 2026-06-15."),
      location: z.string().describe("Work location, e.g. 'San Francisco, CA' or 'Remote — Austin, TX'."),
      country: z.string().default("US"),
      annual_salary_usd: z.number().int().positive(),
    },
  },
  async (args) => {
    const pos = positions.find((p) => p.id === args.position_id);
    if (!pos) return notFound("position", args.position_id);
    if (pos.status !== "Open") {
      return {
        content: [{ type: "text", text: JSON.stringify({
          error: "position_not_open", position_id: pos.id, current_status: pos.status,
        }) }],
        isError: true,
      };
    }
    const mgr = employees.find((e) => e.id === args.manager_id);
    if (!mgr) return notFound("manager", args.manager_id);

    const id = `EMP-${++nextEmpSeq}`;
    const work_email = `${args.first_name.toLowerCase()}.${args.last_name.toLowerCase()}@olympus.example.com`;
    const created: Employee = {
      id,
      first_name: args.first_name,
      last_name: args.last_name,
      preferred_name: args.preferred_name ?? args.first_name,
      work_email,
      personal_email: args.personal_email,
      phone: args.phone ?? "",
      position_id: args.position_id,
      org_id: pos.org_id,
      manager_id: args.manager_id,
      location: args.location,
      country: args.country ?? "US",
      employment_type: "Regular",
      status: "Pre-Hire",
      hire_date: args.hire_date,
      termination_date: null,
      annual_salary_usd: args.annual_salary_usd,
      currency: "USD",
    };
    employees.push(created);
    pos.status = "Filled";
    pos.filled_by = id;
    return text({ ok: true, created, position_updated: pos });
  }
);

// ── Time off ──────────────────────────────────────────────────────────────

server.registerTool(
  "workday_list_time_off",
  {
    title: "List time-off requests",
    description: "List time-off requests, optionally filtered by employee, approver, or status.",
    inputSchema: {
      employee_id: z.string().optional(),
      approver_id: z.string().optional().describe("Approver/manager id."),
      status: z.enum(["Pending", "Approved", "Denied", "Cancelled"]).optional(),
    },
  },
  async ({ employee_id, approver_id, status }) => {
    let pool = timeOff;
    if (employee_id) pool = pool.filter((t) => t.employee_id === employee_id);
    if (approver_id) pool = pool.filter((t) => t.approver_id === approver_id);
    if (status) pool = pool.filter((t) => t.status === status);
    return text({ requests: pool, total: pool.length });
  }
);

server.registerTool(
  "workday_submit_time_off_request",
  {
    title: "Submit a time-off request",
    description: "Submit a new time-off request on behalf of an employee. Status starts as Pending.",
    inputSchema: {
      employee_id: z.string(),
      type: z.string().describe("e.g. 'Vacation', 'Sick Leave', 'Parental Leave'."),
      start_date: z.string().describe("ISO date."),
      end_date: z.string().describe("ISO date (inclusive)."),
      reason: z.string().optional(),
    },
  },
  async ({ employee_id, type, start_date, end_date, reason }) => {
    const emp = employees.find((e) => e.id === employee_id);
    if (!emp) return notFound("employee", employee_id);
    const approver = emp.manager_id ?? "";
    const days = Math.max(1, Math.round(
      (new Date(end_date).getTime() - new Date(start_date).getTime()) / 86_400_000
    ) + 1);
    const id = `PTO-${++nextPtoSeq}`;
    const req: TimeOff = {
      id, employee_id, type, start_date, end_date, days,
      status: "Pending",
      approver_id: approver,
      submitted_at: today(),
      reason: reason ?? "",
    };
    timeOff.push(req);
    return text({ ok: true, request: req });
  }
);

server.registerTool(
  "workday_approve_time_off_request",
  {
    title: "Approve or deny a time-off request",
    description:
      "Approve or deny a Pending time-off request. Use this for the manager-approval step in a " +
      "review workflow; the agent should confirm with the user before calling for write actions.",
    inputSchema: {
      request_id: z.string().describe("PTO-* id from workday_list_time_off."),
      decision: z.enum(["Approved", "Denied"]),
      note: z.string().optional().describe("Optional note shown to the employee."),
    },
  },
  async ({ request_id, decision, note }) => {
    const req = timeOff.find((t) => t.id === request_id);
    if (!req) return notFound("time_off_request", request_id);
    if (req.status !== "Pending") {
      return {
        content: [{ type: "text", text: JSON.stringify({
          error: "not_pending", request_id, current_status: req.status,
        }) }],
        isError: true,
      };
    }
    req.status = decision;
    req.decided_at = today();
    if (note) req.decision_note = note;
    return text({ ok: true, request: req });
  }
);

// ── Payroll ───────────────────────────────────────────────────────────────

server.registerTool(
  "workday_list_payroll_records",
  {
    title: "List payroll records",
    description: "Most-recent payroll records for an employee or for everyone (limit 50).",
    inputSchema: {
      employee_id: z.string().optional(),
      limit: z.number().int().min(1).max(50).optional(),
    },
  },
  async ({ employee_id, limit }) => {
    let pool = payroll;
    if (employee_id) pool = pool.filter((p) => p.employee_id === employee_id);
    pool = [...pool].sort((a, b) => b.paid_on.localeCompare(a.paid_on));
    return text({ records: pool.slice(0, limit ?? 25), total: pool.length });
  }
);

// ── Shifts ────────────────────────────────────────────────────────────────

server.registerTool(
  "workday_list_shifts",
  {
    title: "List scheduled shifts",
    description: "Scheduled / completed shifts for a date range, optionally filtered by employee or location substring.",
    inputSchema: {
      from_date: z.string().describe("ISO date inclusive."),
      to_date: z.string().describe("ISO date inclusive."),
      employee_id: z.string().optional(),
      location_query: z.string().optional().describe("Substring match against location."),
    },
  },
  async ({ from_date, to_date, employee_id, location_query }) => {
    let pool = shifts.filter((s) => s.date >= from_date && s.date <= to_date);
    if (employee_id) pool = pool.filter((s) => s.employee_id === employee_id);
    if (location_query) {
      const q = location_query.toLowerCase();
      pool = pool.filter((s) => s.location.toLowerCase().includes(q));
    }
    return text({ shifts: pool, total: pool.length });
  }
);

// ── Boot ──────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
