import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { KRATOS_AGENT_ID } from "@/lib/agui";

// The browser's only path to the agent. CopilotKit's runtime speaks to the
// browser; its single HttpAgent relays each AG-UI run to the backend, which
// forwards it to the Foundry hosted agent. It deliberately sits outside /api so
// a Front Door that routes <basePath>/api/* to the backend never captures it.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 8 * 1024 * 1024;

function backendOrigin(): string {
  // Server-side only; never taken from the request.
  return (process.env.AGENT_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");
let handler: ReturnType<typeof createCopilotRuntimeHandler> | undefined;

function getHandler() {
  handler ??= createCopilotRuntimeHandler({
    runtime: new CopilotRuntime({
      agents: {
        [KRATOS_AGENT_ID]: new HttpAgent({
          url: `${backendOrigin()}/api/agui`,
          headers: { "Content-Type": "application/json" },
        }),
      },
      forwardHeaders: { allow: ["content-type", "x-kratos-eval-run-id"] },
    }),
    basePath: `${basePath}/copilotkit/${KRATOS_AGENT_ID}`,
    mode: "single-route",
  });
  return handler;
}

export async function POST(request: Request, context: { params: Promise<{ agent: string }> }) {
  const { agent } = await context.params;
  if (agent !== KRATOS_AGENT_ID) {
    return Response.json({ error: "Unknown agent" }, { status: 404 });
  }
  const length = Number(request.headers.get("content-length") || "0");
  if (length > MAX_BODY_BYTES) {
    return Response.json({ error: "Request too large" }, { status: 413 });
  }
  const body = await request.arrayBuffer();
  if (body.byteLength > MAX_BODY_BYTES) {
    return Response.json({ error: "Request too large" }, { status: 413 });
  }
  const response = await getHandler()(
    new Request(request.url, { method: "POST", headers: request.headers, body, signal: request.signal }),
  );
  if (response.headers.get("content-type")?.includes("text/event-stream")) {
    response.headers.set("content-type", "text/event-stream; charset=utf-8");
    response.headers.set("cache-control", "no-cache, no-transform");
    response.headers.set("x-accel-buffering", "no");
  }
  return response;
}
