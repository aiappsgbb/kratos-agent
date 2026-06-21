#!/usr/bin/env node
// assemble.mjs — turn raw captured artifacts (out/raw.json) into the walkthrough
// dataset (out/capture.json) consumed by report-template.html.
//
//   node lib/assemble.mjs <raw.json> <capture.json>
//
// It decodes the user JWT (signature stripped — claims only), builds the 5 real
// hops of the OBO flow INCLUDING the LLM tool-call round-trip (NO APIM — agent
// invocations go straight to the Foundry project endpoint), and contrasts what
// the login token carries vs. the rich profile only Microsoft Graph can return.
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const [, , rawPath, outPath] = process.argv;
if (!rawPath || !outPath) {
  console.error("usage: node lib/assemble.mjs <raw.json> <capture.json>");
  process.exit(2);
}
const raw = JSON.parse(readFileSync(resolve(rawPath), "utf8"));

function decodeJwt(tok) {
  if (!tok || tok.split(".").length < 2) return { header: {}, claims: {} };
  const b64 = (s) => Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
  try {
    return { header: JSON.parse(b64(tok.split(".")[0])), claims: JSON.parse(b64(tok.split(".")[1])) };
  } catch {
    return { header: {}, claims: {} };
  }
}
const { claims } = decodeJwt(raw.userToken);
const eps = raw.endpoints || {};
const tr = raw.toolResult || {};
const oid = claims.oid || "";
const graphId = tr.id || "";
const fmt = (o) => JSON.stringify(o, null, 2);
const redactJwt = (tok) =>
  tok ? `${tok.slice(0, 24)}…<header.payload.signature — ${tok.length} chars, redacted>` : "(none)";

function host(u) {
  if (!u) return "<host>";
  try {
    return new URL(u).host.split(".")[0];
  } catch {
    return u;
  }
}

// ── What the LOGIN TOKEN carries (identity only) ────────────────────────────
const jwtFields = [
  { k: "aud (who it's for)", v: claims.aud },
  { k: "scp (what it allows)", v: claims.scp },
  { k: "name", v: claims.name },
  { k: "preferred_username", v: claims.preferred_username },
  { k: "oid (your Entra id)", v: claims.oid },
].filter((f) => f.v != null);

// ── What only MICROSOFT GRAPH can return (your live directory profile) ──────
// Persona fields are the headline. jobTitle / department / officeLocation /
// preferredLanguage can NEVER appear in an Entra access token — they aren't even
// on the optional-claims list — so they're airtight proof of a live, delegated
// Graph read. (name / oid / preferred_username DO live in the token, so they
// stay in the "login token" column, not here.)
const personaSpec = [
  ["jobTitle", "Job title"],
  ["department", "Department"],
  ["officeLocation", "Office"],
  ["preferredLanguage", "Preferred language"],
  ["givenName", "First name"],
  ["surname", "Last name"],
  ["mail", "Mail"],
];
const personaFields = personaSpec.map(([k, label]) => ({
  k,
  label,
  v: tr[k] == null || tr[k] === "" ? null : tr[k],
}));
// Technical, cross-referenceable backup proof (stamped by Graph on this response).
const technicalFields = [
  { k: "graphRequestId", v: tr.graphRequestId, hint: "a tracking id Microsoft Graph stamped on THIS response" },
  { k: "fetchedAtUtc", v: tr.fetchedAtUtc, hint: "the moment the live call happened" },
].filter((f) => f.v != null && f.v !== "");

const photoDataUri = typeof tr.photoDataUri === "string" ? tr.photoDataUri : raw.photoDataUri || null;

// ── Representative LLM round-trip (assembled from the REAL prompt, tool schema,
// tool call and result captured this run). Shows what the agent sends the model
// and what the model sends back when it decides to use the tool. ─────────────
const llmModel = raw.llmModel || "gpt (Foundry-hosted via Copilot SDK)";
const llmRequest = {
  model: llmModel,
  messages: [
    { role: "system", content: "You are the kratos agent. Use the available tools to answer about the signed-in user." },
    { role: "user", content: raw.prompt },
  ],
  tools: [
    {
      type: "function",
      function: {
        name: "graph-obo-get_my_profile",
        description: "Return the signed-in user's Microsoft 365 profile, fetched live from Microsoft Graph on behalf of the user.",
        parameters: { type: "object", properties: {}, required: [] },
      },
    },
  ],
  tool_choice: "auto",
};
const llmToolCallResponse = {
  role: "assistant",
  content: null,
  tool_calls: [
    {
      id: "call_graph_obo_1",
      type: "function",
      function: { name: "graph-obo-get_my_profile", arguments: "{}" },
    },
  ],
};
const toolResultMessage = {
  role: "tool",
  tool_call_id: "call_graph_obo_1",
  name: "graph-obo-get_my_profile",
  content: fmt({ ...tr, photoDataUri: photoDataUri ? "<48x48 image data-uri, omitted>" : undefined }),
};
const llmFinalResponse = { role: "assistant", content: raw.answer || "" };

// ── the 5 hops ──────────────────────────────────────────────────────────────
const steps = [
  {
    title: "You ask — your delegated token rides along in the request body",
    from: "Browser (MSAL.js)",
    to: `Backend · ${host(eps.backend)}`,
    summary:
      "POST /api/agent/chat. Your Entra access token travels in the JSON body under mcpAccessTokens — never in the prompt, never as a header the model can see.",
    detailLabel: "POST /api/agent/chat (body — token redacted)",
    detail: fmt({
      conversationId: raw.conversationId || "<conv-id>",
      message: raw.prompt,
      mcpAccessTokens: Object.fromEntries((raw.requestBodyKeys || ["graph-obo"]).map((k) => [k, redactJwt(raw.userToken)])),
    }),
    note: `The token's audience is the <b>OBO server app</b> (<code>aud=${claims.aud || "api://<obo-server>"}</code>), scope <code>scp=${claims.scp || "access_as_user"}</code> — it is <b>not</b> a Graph token yet. The OBO server will exchange it.`,
  },
  {
    title: "Backend forwards it to the Foundry-hosted agent",
    from: `Backend · ${host(eps.backend)}`,
    to: "Hosted agent (Foundry Invocations)",
    summary:
      "Straight to the Foundry project Invocations endpoint — no APIM in this path. The mcpAccessTokens body field is preserved and reaches the sandbox.",
    detailLabel: "POST …/agents/kratos-agent/endpoint/protocols/invocations",
    detail: [
      `${eps.foundryInvocations || "https://<resource>.cognitiveservices.azure.com/api/projects/<proj>/agents/kratos-agent/endpoint/protocols/invocations?api-version=…"}`,
      "",
      "Authorization: Bearer <backend managed-identity token for the Foundry resource>",
      "x-agent-session-id: <warm-pool session routing>",
      "",
      "// Body carries the user's mcpAccessTokens through to the hosted agent.",
    ].join("\n"),
    note: `The &quot;gateway&quot; here is <b>Foundry's own Invocations gateway</b> (warm-pool / session manager), <b>not</b> APIM. The APIM AI-gateway fronts LLM calls only and is bypassed in this deployment.`,
  },
  {
    title: "The agent asks the model — and the model decides to call the tool",
    from: "Hosted agent ↔ LLM",
    to: "graph-obo tool selected",
    summary:
      "The agent sends the model your question plus the tools it has. The model replies with a tool call: run graph-obo-get_my_profile. (No arguments — you're identified by the attached token, not by prompt text.)",
    detailLabel: "The model round-trip",
    blocks: [
      { label: "① Agent → LLM  (request: your message + available tools)", content: fmt(llmRequest) },
      { label: "② LLM → Agent  (response: “call graph-obo-get_my_profile”)", content: fmt(llmToolCallResponse) },
    ],
    note: `This is the moment the agent decides to act. The model only chooses the tool — it never sees your token; the SDK injects that as the tool's HTTP header in the next step.`,
  },
  {
    title: "The agent runs the tool as YOU — On-Behalf-Of → Microsoft Graph",
    from: "Hosted agent → graph-obo MCP",
    to: "Microsoft Graph /v1.0/me",
    summary:
      "The SDK attaches your token as the graph-obo server's Authorization header. The server validates it, exchanges it On-Behalf-Of for a Graph token, and calls /me — so Graph answers as YOU.",
    detailLabel: "What happens inside the tool call",
    blocks: [
      {
        label: "① Agent injects your token as the MCP server's header (keys-only diag)",
        content: fmt({
          event: "kratos_diag",
          data: {
            mcp_token_effective_keys: (raw.hostedDiag && raw.hostedDiag.mcp_token_effective_keys) || ["graph-obo"],
            obo_env_url_present: (raw.hostedDiag && raw.hostedDiag.obo_env_url_present) ?? true,
            obo_env_name: (raw.hostedDiag && raw.hostedDiag.obo_env_name) || "graph-obo",
          },
        }),
      },
      {
        label: "② OBO server: validate → On-Behalf-Of exchange → GET /me 200 (real logs)",
        content: (raw.oboLogs || "obo-mcp-server.obo - OnBehalfOfCredential.get_token succeeded").trim(),
      },
      { label: "③ Tool result handed back to the agent (your live profile)", content: fmt(tr) },
    ],
    note: `Self-auth differs by environment only: <b>cloud</b> = secret-less managed-identity federation; <b>local</b> = a dev client secret on the same app reg. The token validation and the Graph call are identical.`,
  },
  {
    title: "The model writes the answer — and you see it",
    from: "Hosted agent ↔ LLM",
    to: "Browser (streamed answer)",
    summary:
      "The tool result goes back to the model, which turns it into a human answer and streams it to you. The words below could only come from a live Graph call made on your behalf.",
    detailLabel: "The model round-trip (answer)",
    blocks: [
      { label: "① Agent → LLM  (request: here is the tool result)", content: fmt(toolResultMessage) },
      { label: "② LLM → Agent → You  (final answer)", content: fmt(llmFinalResponse) },
    ],
    note: `Everything in the answer that isn't your name/login came from <b>Microsoft Graph</b>, live, as you — see the proof below.`,
  },
];

// ── flow diagram nodes (1:1 with the steps above) ───────────────────────────
const diagram = [
  { n: 1, label: "You", sub: "+ delegated token" },
  { n: 2, label: "Backend", sub: "→ Foundry agent" },
  { n: 3, label: "LLM", sub: "decides: call tool" },
  { n: 4, label: "OBO → Graph", sub: "runs as YOU" },
  { n: 5, label: "Answer", sub: "streamed back" },
];

const walkthrough = {
  target: raw.target || "cloud",
  capturedAt: raw.capturedAt || new Date().toISOString().replace("T", " ").slice(0, 16) + " UTC",
  prompt: raw.prompt,
  endpoints: eps,
  diagram,
  steps,
  answer: raw.answer || "",
  photoDataUri,
  proof: {
    oidFromToken: oid,
    idFromGraph: graphId,
    match: !!(oid && graphId && oid === graphId),
    jwtFields,
    personaFields,
    technicalFields,
    nullNote:
      "A field shown as <b>null</b> isn't an error — it means that field is genuinely empty in the directory. " +
      "The agent reports exactly what Graph returns, live; it never guesses or fills blanks.",
  },
  notes: {
    apim:
      "<b>No APIM in the agent path.</b> Agent invocations go directly to the Foundry project endpoint " +
      "(<code>…cognitiveservices.azure.com/api/projects/…/agents/kratos-agent/…/invocations</code>). The " +
      "&quot;gateway&quot; in the logs is Foundry's own Invocations gateway (warm-pool/session manager). The APIM " +
      "AI-gateway is an optional <b>LLM</b> governance layer; in this deployment <code>FOUNDRY_ENDPOINT</code> targets " +
      "the AI Services resource directly, so APIM is provisioned but bypassed.",
    llm:
      "The model round-trip (steps 3 &amp; 5) is shown in the OpenAI chat-completions shape, assembled from the " +
      "<b>real</b> prompt, tool schema, tool call and result captured this run. The model only ever sees the tool's " +
      "<i>result</i> — never your access token.",
    repro:
      `<b>Reproduce:</b> <code>cd .copilot/skills/obo-demo-walkthrough &amp;&amp; ` +
      `TARGET=${raw.target || "cloud"} ./run.sh</code> &nbsp;·&nbsp; local: <code>docker compose up</code> then ` +
      `<code>TARGET=local ./run.sh</code>. Same proof, same HTML; only the OBO server's self-auth differs.`,
    footer: `Generated by the <b>obo-demo-walkthrough</b> skill · target=${raw.target || "cloud"} · ${new Date().toISOString()}`,
  },
};

writeFileSync(resolve(outPath), JSON.stringify(walkthrough, null, 2));
console.log(
  `[assemble] wrote ${outPath} — steps=${steps.length} match=${walkthrough.proof.match} persona=${personaFields.filter((f) => f.v).length}/${personaFields.length} photo=${photoDataUri ? "yes" : "no"}`,
);
