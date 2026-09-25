#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(here, "data");

type Citation = { source_id: string; title: string; section: string; url: string; };
type KnowledgeDoc = { id: string; source_id: string; title: string; category: "runbook" | "safety" | "maintenance" | "process" | "tooling"; plant_id: string; machine_id?: string; tags: string[]; summary: string; content: string; citations: Citation[]; last_updated: string; confidence: number; };

const load = <T>(file: string): T => JSON.parse(readFileSync(path.join(dataDir, file), "utf-8")) as T;
const docs: KnowledgeDoc[] = load("docs.json");
const withSimulationNote = <T>(obj: T) => ({ ...(obj as object), simulation_only: true });
const text = (obj: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(withSimulationNote(obj), null, 2) }] });
const notFound = (kind: string, id: string) => ({ content: [{ type: "text" as const, text: JSON.stringify({ error: "not_found", kind, id, simulation_only: true }, null, 2) }], isError: true });
const server = new McpServer({ name: "foundry-iq-mcp-server", version: "0.1.0" });

server.registerTool(
  "foundry_iq_search_knowledge",
  {
    title: "Search industrial knowledge",
    description: "Search synthetic industrial knowledge for runbooks, safety, tooling, and process guidance. Returns citations and source IDs.",
    inputSchema: {
      query: z.string().describe("Search string over title, summary, tags, and content."),
      plant_id: z.string().optional().describe("Restrict to a specific plant."),
      machine_id: z.string().optional().describe("Restrict to a specific machine id."),
      category: z.enum(["runbook", "safety", "maintenance", "process", "tooling"]).optional(),
      limit: z.number().int().positive().optional().describe("Maximum documents to return."),
    },
  },
  async ({ query, plant_id, machine_id, category, limit }) => {
    const terms = query.toLowerCase().split(/[^a-z0-9-]+/).filter((term) => term.length > 2);
    let pool = docs
      .map((doc) => {
        const haystack = [doc.title, doc.summary, doc.content, ...doc.tags].join(" ").toLowerCase();
        return { doc, score: terms.filter((term) => haystack.includes(term)).length };
      })
      .filter(({ score }) => score > 0)
      .sort((left, right) => right.score - left.score || left.doc.id.localeCompare(right.doc.id))
      .map(({ doc }) => doc);
    if (plant_id) pool = pool.filter((doc) => doc.plant_id === plant_id);
    if (machine_id) pool = pool.filter((doc) => doc.machine_id === machine_id);
    if (category) pool = pool.filter((doc) => doc.category === category);
    if (limit) pool = pool.slice(0, limit);
    return text({ documents: pool, total: pool.length });
  },
);

server.registerTool(
  "foundry_iq_get_document",
  {
    title: "Get a synthetic knowledge document",
    description: "Retrieve a knowledge document by document_id or source_id. Includes citations and a simulation-only note.",
    inputSchema: {
      document_id: z.string().optional().describe("Document id."),
      source_id: z.string().optional().describe("Source id."),
    },
  },
  async ({ document_id, source_id }) => {
    const doc = docs.find((entry) => (document_id && entry.id === document_id) || (source_id && entry.source_id === source_id));
    if (!doc) return notFound("document", document_id ?? source_id ?? "unknown");
    return text(doc);
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
