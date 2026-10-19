"use client";

import { useContext } from "react";
import { useFrontendTool, useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { KRATOS_AGENT_ID } from "@/lib/agui";
import { ResumeContext } from "../AskUserCard";
import { AllocationCard, type AllocationArgs } from "./AllocationCard";
import { ChartCard } from "./ChartCard";
import { MetricsCard } from "./MetricsCard";
import { normalizeChart, normalizeMetrics, normalizeTable } from "./normalize";
import { TableCard } from "./TableCard";

export const RENDER_CHART_TOOL = "render_chart";
export const PROPOSE_ALLOCATION_TOOL = "propose_allocation";
export const SHOW_TABLE_TOOL = "show_table";
export const SHOW_METRICS_TOOL = "show_metrics";

const chartParameters = z.object({
  title: z.string().describe("Short chart title."),
  subtitle: z.string().optional().describe("Optional context line, e.g. the data source and date."),
  kind: z.enum(["bar", "line", "donut"]).describe("bar to compare categories, line for a trend over time, donut for parts of a whole."),
  labels: z.array(z.string()).describe("Category or time labels, one per data point."),
  series: z
    .array(z.object({ name: z.string(), values: z.array(z.number()) }))
    .describe("One or more data series; each has exactly one value per label. Donut charts use the first series."),
  unit: z.string().optional().describe('Unit for values, e.g. "%", "$", "CHF", "units".'),
});

const cell = z.union([z.string(), z.number(), z.boolean(), z.null()]);
const tableParameters = z.object({
  title: z.string().describe("Short table title."),
  caption: z.string().optional().describe("Optional context line, e.g. the source system and as-of date."),
  columns: z
    .array(
      z.object({
        key: z.string().describe("Field name used in each row."),
        label: z.string().describe("Column header."),
        format: z.enum(["text", "number", "currency", "percent"]).optional(),
        currency: z.string().optional().describe("ISO currency code for currency columns, e.g. USD."),
      }),
    )
    .describe("Columns in display order."),
  rows: z.array(z.record(z.string(), cell)).describe("Rows keyed by column key. Use raw numbers for numeric columns."),
});

const metricsParameters = z.object({
  title: z.string().optional().describe("Optional heading for the group of metrics."),
  metrics: z
    .array(
      z.object({
        label: z.string(),
        value: z.union([z.string(), z.number()]),
        unit: z.string().optional().describe('e.g. "%", "$", "units".'),
        delta: z.number().optional().describe("Change versus the comparison period, as a signed number."),
        deltaLabel: z.string().optional().describe('What the change compares to, e.g. "vs last week" or "pp".'),
        status: z.enum(["good", "warning", "bad", "neutral"]).optional().describe("Whether the value is on track."),
        note: z.string().optional().describe("One short line of context."),
      }),
    )
    .describe("Two to six headline figures."),
});

const allocationParameters = z.object({
  title: z.string().describe("Short title for the proposal."),
  rationale: z.string().describe("Two or three sentences on why this rebalance."),
  items: z
    .array(z.object({ name: z.string(), current: z.number(), proposed: z.number() }))
    .describe("Asset classes or holdings with current and proposed weights in percent; proposed weights add up to 100."),
});

/**
 * Generative UI the agent can use in any persona: it calls these tools and the
 * browser renders real components. Nothing is configured on the backend; the
 * tools travel to the agent with each AG-UI run.
 */
export function useKratosVisuals(deps: unknown[]) {
  useFrontendTool(
    {
      agentId: KRATOS_AGENT_ID,
      name: RENDER_CHART_TOOL,
      description:
        "Show the user a chart rendered live in the chat. Prefer this over describing numbers in text or generating chart images whenever comparing values, showing a trend, or showing a breakdown. Use real numbers from tools; never invent data. After calling it, briefly interpret the chart in text. Arguments: {kind, title, labels: [..], series: [{name, values: [..]}], unit}; each series has one number per label.",
      parameters: chartParameters,
      handler: async () => "The chart is now displayed to the user.",
      render: (p: { args: Partial<z.infer<typeof chartParameters>>; status: string }) => (
        <div className="basis-full">
          <ChartCard spec={normalizeChart(p.args)} done={p.status !== "inProgress"} />
        </div>
      ),
    },
    deps,
  );

  useFrontendTool(
    {
      agentId: KRATOS_AGENT_ID,
      name: SHOW_TABLE_TOOL,
      description:
        "Show the user a sortable table rendered live in the chat. Use it for lists of records the user will scan or compare (transactions, tickets, policies, holdings, schedules) instead of a markdown table. Use real data from tools. After calling it, summarise what matters in one or two sentences instead of repeating the rows. Arguments: {title, columns: [{key, label, format}], rows: [{<key>: value}]}.",
      parameters: tableParameters,
      handler: async () => "The table is now displayed to the user.",
      render: (p: { args: Partial<z.infer<typeof tableParameters>> }) => (
        <div className="basis-full">
          <TableCard spec={normalizeTable(p.args)} />
        </div>
      ),
    },
    deps,
  );

  useFrontendTool(
    {
      agentId: KRATOS_AGENT_ID,
      name: SHOW_METRICS_TOOL,
      description:
        "Show the user two to six headline figures as metric tiles (value, change, on-track status). Use it at the top of a status or summary answer, e.g. balances, KPIs, shift health, claim totals. Use real numbers from tools. Then explain what stands out. Arguments: {title, metrics: [{label, value, unit, delta, deltaLabel, status}]}.",
      parameters: metricsParameters,
      handler: async () => "The metrics are now displayed to the user.",
      render: (p: { args: Partial<z.infer<typeof metricsParameters>> }) => (
        <div className="basis-full">
          <MetricsCard spec={normalizeMetrics(p.args)} />
        </div>
      ),
    },
    deps,
  );

  useHumanInTheLoop(
    {
      agentId: KRATOS_AGENT_ID,
      name: PROPOSE_ALLOCATION_TOOL,
      description:
        "Propose a portfolio rebalance for the user to review. The user can adjust each target weight before approving or rejecting. Wait for the result: it is JSON with decision approved or rejected and, when approved, the final allocation, which may differ from your proposal. Continue with the user's final numbers and say what they changed.",
      parameters: allocationParameters,
      render: (p: {
        toolCallId: string;
        args: Partial<z.infer<typeof allocationParameters>>;
        status: string;
        result?: string;
        respond?: (v: unknown) => Promise<void>;
      }) => <AllocationTool {...p} />,
    },
    deps,
  );
}

/** Wires a restored, still-paused proposal to the resume path after a reload. */
function AllocationTool(p: {
  toolCallId: string;
  args: Partial<z.infer<typeof allocationParameters>>;
  status: string;
  result?: string;
  respond?: (v: unknown) => Promise<void>;
}) {
  const resume = useContext(ResumeContext);
  const restored = !p.respond && p.result === undefined && resume.pending.has(p.toolCallId);
  return (
    <div className="basis-full">
      <AllocationCard
        args={p.args as AllocationArgs}
        status={restored ? "executing" : p.status}
        result={p.result}
        respond={restored ? (v) => resume.respond(p.toolCallId, String(v)) : p.respond}
      />
    </div>
  );
}
