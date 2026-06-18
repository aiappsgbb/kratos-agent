"""Kratos Agent — Hosted Agent entry point using the Invocations protocol.

Runs the same CopilotClient + SkillRegistry + CosmosService engine as the
Container App backend, but hosted on Microsoft Foundry via the
``azure-ai-agentserver-invocations`` protocol adapter on port 8088.

Key differences from the FastAPI backend:
- HTTP layer: InvocationAgentServerHost (port 8088) instead of FastAPI+uvicorn (8000)
- Compute: Foundry-managed auto-provision/deprovision instead of always-on Container App
- Identity: Dedicated Entra agent identity (injected by the platform)
- Protocol: Invocations (arbitrary JSON in, SSE out) — preserves our event schema
"""

import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
import uuid

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

# Foundry reserves all FOUNDRY_* env vars; remap our non-reserved names.
# The platform auto-injects FOUNDRY_PROJECT_ENDPOINT but our Settings class reads FOUNDRY_ENDPOINT.
if "MODEL_DEPLOYMENT_NAME" in os.environ and "FOUNDRY_MODEL_DEPLOYMENT" not in os.environ:
    os.environ["FOUNDRY_MODEL_DEPLOYMENT"] = os.environ["MODEL_DEPLOYMENT_NAME"]
if "FOUNDRY_ENDPOINT" not in os.environ:
    # Platform injects FOUNDRY_PROJECT_ENDPOINT (e.g. https://host/api/projects/proj).
    # The CopilotClient provider needs just the base URL (https://host) without the
    # project path, since it appends /openai/deployments/<model> itself.
    project_ep = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if project_ep:
        # Strip /api/projects/... suffix to get the AI Services base URL
        idx = project_ep.find("/api/projects")
        os.environ["FOUNDRY_ENDPOINT"] = project_ep[:idx] if idx > 0 else project_ep
    # Also try AI_SERVICES_ENDPOINT set in agent.yaml
    elif "AI_SERVICES_ENDPOINT" in os.environ:
        os.environ["FOUNDRY_ENDPOINT"] = os.environ["AI_SERVICES_ENDPOINT"]

# Add the backend app to the Python path so we can reuse all existing modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import Settings, get_settings
from app.hosted_agent_invoke import parse_invoke_payload
from app.models import (
    ContentEvent,
    DoneEvent,
    ErrorEvent,
    ThoughtEvent,
    ToolCallEvent,
    UsageEvent,
    UserInputRequestEvent,
)
from app.observability import setup_telemetry
from app.services.apm_service import ApmError, ApmService
from app.services.blob_skill_service import BlobSkillService
from app.services.copilot_agent import CopilotAgent
from app.services.cosmos_service import CosmosService
from app.services.skill_registry import SkillRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ─── Global state (initialised in startup) ──────────────────────────────────

_copilot_agent: CopilotAgent | None = None
_cosmos_service: CosmosService | None = None
_blob_service: BlobSkillService | None = None
_apm_service: ApmService | None = None
_registries: dict[str, SkillRegistry] = {}
_settings: Settings | None = None

# Lazy per-use-case loading. A pre-warmed sandbox is unclaimed, so at warm time
# we don't yet know which use-case it will serve — loading all 9 use-cases up
# front (each does a serial blob sync + skill parse + ``apm install``) is the
# dominant cold-start cost. Instead we warm only the shared core (Cosmos, blob,
# Copilot agent) and load a single use-case's skills the first time it is
# actually requested, caching it in ``_registries`` thereafter.
_registry_lock = asyncio.Lock()

# Cold-start timing — populated by _startup() and surfaced in the warmup
# response so the backend can log the hosted-agent's own startup cost (vs the
# platform microVM boot) without needing App Insights access.
_startup_total_ms: float = 0.0
_startup_phases: dict[str, float] = {}

app = InvocationAgentServerHost()


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def _startup() -> None:
    """Initialise the shared core — mirrors the FastAPI lifespan startup.

    Only use-case-agnostic services are initialised here (telemetry, Cosmos,
    blob, the Copilot SDK agent). Individual use-case skill registries are
    loaded lazily by :func:`_ensure_registry` on first use, so a pre-warmed
    sandbox becomes ready without paying to load all 9 use-cases up front.
    """
    global _copilot_agent, _cosmos_service, _blob_service, _apm_service, _settings
    global _startup_total_ms, _startup_phases

    import time as _time

    t_start = _time.monotonic()
    phases: dict[str, float] = {}

    def _mark(name: str, t0: float) -> None:
        phases[name] = round((_time.monotonic() - t0) * 1000, 1)

    _settings = get_settings()

    # Setup OpenTelemetry
    t0 = _time.monotonic()
    setup_telemetry(_settings)
    _mark("telemetry", t0)

    # Cosmos, blob storage, and the Copilot SDK agent are mutually independent,
    # so initialise them concurrently. Cosmos init and the Copilot agent's token
    # pre-warm each cost ~1.7s serially; running them in parallel roughly halves
    # the shared-core warm time.
    t0 = _time.monotonic()
    _cosmos_service = CosmosService(_settings)
    blob_service = BlobSkillService(_settings)
    _copilot_agent = CopilotAgent(_settings)
    # The agent shares the (initially empty) _registries dict; lazy loads add
    # keys to it in place so the agent sees them without a reset.
    _copilot_agent.set_registries(_registries)
    await asyncio.gather(
        _cosmos_service.initialize(),
        blob_service.initialize(),
        _copilot_agent.start(),
    )
    _blob_service = blob_service
    _copilot_agent.set_cosmos_service(_cosmos_service)
    # APM service (kept for lazy per-use-case syncs)
    _apm_service = ApmService(_settings, blob_service)
    _mark("core_parallel", t0)

    # Seed local use-cases into blob if the container is empty. This only
    # uploads use-cases that are missing (a fast list + skip when already
    # seeded by a prior deploy / the backend), and is required so that the
    # lazy per-use-case loads below can pull skills from blob.
    if blob_service.is_available:
        t0 = _time.monotonic()
        try:
            seeded = await blob_service.seed_from_local()
            if seeded:
                logger.info("Seeded %d use-case(s) into blob", len(seeded))
        except Exception:
            logger.exception("Failed to seed use-cases into blob storage")
        _mark("seed", t0)

    _startup_phases = phases
    _startup_total_ms = round((_time.monotonic() - t_start) * 1000, 1)

    logger.info(
        "Kratos Hosted Agent core started in %.0fms (phases=%s) — environment=%s model=%s",
        _startup_total_ms,
        phases,
        _settings.environment,
        _settings.foundry_model_deployment or "(empty)",
    )


async def _ensure_registry(use_case: str) -> None:
    """Lazily load a single use-case's skill registry on first use.

    Loading is guarded by a lock and cached in ``_registries`` so concurrent or
    repeat requests for the same use-case load it only once. Falls back to the
    baked-in local ``use-cases/`` directory when blob is unavailable.
    """
    if use_case in _registries:
        return

    import time as _time

    async with _registry_lock:
        if use_case in _registries:
            return
        t0 = _time.monotonic()

        # Sync just this use-case's APM dependencies (no-op when none declared).
        if _apm_service is not None and _settings is not None and _settings.apm_enabled and _settings.apm_startup_sync:
            try:
                if await _apm_service.needs_sync(use_case):
                    await _apm_service.sync(use_case)
            except ApmError as exc:
                logger.warning("APM sync failed for '%s': %s", use_case, exc)
            except Exception:
                logger.warning("Unexpected APM sync error for '%s' (non-fatal)", use_case, exc_info=True)

        local_root = _settings.apm_use_cases_root if _settings else "use-cases"

        # Prefer blob (so use-cases uploaded post-deploy are picked up), but ALWAYS
        # fall back to the baked-in local use-cases/ directory if blob is
        # unavailable OR the blob load fails / yields nothing. The hosted-agent's
        # Foundry-managed compute may not be able to reach the storage account
        # (private-endpoint only), so the local fallback is what keeps the
        # correct skills + system prompt loaded — mirroring the original eager
        # startup behaviour. Without this fallback the agent silently reverts to
        # the generic system prompt for every use-case.
        registry: SkillRegistry | None = None
        if _blob_service is not None and _blob_service.is_available:
            try:
                candidate = SkillRegistry()
                await candidate.load(use_case, _blob_service, apm_service=_apm_service)
                if candidate.system_prompt or candidate.skills:
                    registry = candidate
                else:
                    logger.warning("Blob load for '%s' returned no skills/prompt — falling back to local disk", use_case)
            except Exception:
                logger.warning("Blob load failed for '%s' — falling back to local disk", use_case, exc_info=True)

        if registry is None:
            try:
                candidate = SkillRegistry()
                await candidate.load(use_case, apm_service=_apm_service, local_root=local_root)
                registry = candidate
            except Exception:
                logger.exception("Failed to lazy-load use-case '%s' from local disk", use_case)
                return

        _registries[use_case] = registry
        logger.info(
            "Lazy-loaded use-case '%s' (%d skills, prompt=%s) in %.0fms",
            use_case,
            len(getattr(registry, "skills", {}) or {}),
            bool(getattr(registry, "system_prompt", "")),
            (_time.monotonic() - t0) * 1000,
        )


async def _shutdown() -> None:
    """Cleanup on shutdown."""
    if _copilot_agent:
        await _copilot_agent.stop()
    if _cosmos_service:
        await _cosmos_service.close()
    logger.info("Kratos Hosted Agent stopped")


# ─── Invocation Handler ─────────────────────────────────────────────────────

_TMP_FILE_PATTERN = re.compile(r"/tmp/([\w.\- /]+\.[a-zA-Z0-9]{1,10})")


def _collect_generated_files(response_text: str) -> list[tuple[str, bytes]]:
    """Scan the agent response for /tmp/ file paths and collect their contents.

    Returns a list of (relative_path, file_bytes) tuples for files that exist locally.
    relative_path may include subdirectories (e.g. 'pete_report/file.pdf').
    These will be streamed to the backend proxy via SSE events.
    """
    matches = _TMP_FILE_PATTERN.findall(response_text)
    if not matches:
        return []

    files: list[tuple[str, bytes]] = []
    for rel_path in set(matches):
        local_path = f"/tmp/{rel_path}"
        if not os.path.isfile(local_path):
            logger.warning("Referenced file not found locally: %s", local_path)
            continue
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            files.append((rel_path, data))
            logger.info("Collected generated file: %s (%d bytes)", local_path, len(data))
        except Exception:
            logger.warning("Failed to read generated file %s", local_path, exc_info=True)
    return files


async def _stream_response(invocation_id: str, conversation_id: str, message: str, use_case: str):
    """Run the Copilot SDK agent and stream our SSE event schema."""
    start_time = time.monotonic()
    total_tool_calls = 0

    # Associate conversation with use-case
    _copilot_agent.set_conversation_use_case(conversation_id, use_case)

    try:
        # Persist user message to Cosmos (non-fatal — agent works without persistence)
        from datetime import datetime, timezone

        from app.models import Message, MessageRole

        user_message = Message(
            id=str(uuid.uuid4()),
            conversationId=conversation_id,
            role=MessageRole.USER,
            content=message,
            createdAt=datetime.now(timezone.utc),
        )
        try:
            await _cosmos_service.upsert_message(user_message)
        except Exception:
            logger.warning("Failed to persist user message to Cosmos (non-fatal)", exc_info=True)

        # Stream events from CopilotAgent
        assistant_content_parts: list[str] = []
        collected_thoughts: list[str] = []
        collected_tool_calls: list[dict] = []

        async for event in _copilot_agent.run(
            message=message,
            conversation_id=conversation_id,
        ):
            if isinstance(event, ThoughtEvent):
                collected_thoughts.append(event.content)
                yield f"data: {json.dumps({'event': 'thought', 'data': event.model_dump()})}\n\n".encode()
            elif isinstance(event, ToolCallEvent):
                if event.status == "completed":
                    total_tool_calls += 1
                collected_tool_calls.append(event.model_dump())
                yield f"data: {json.dumps({'event': 'tool_call', 'data': event.model_dump()})}\n\n".encode()
            elif isinstance(event, UsageEvent):
                yield f"data: {json.dumps({'event': 'usage', 'data': event.model_dump()})}\n\n".encode()
            elif isinstance(event, ContentEvent):
                assistant_content_parts.append(event.content)
                yield f"data: {json.dumps({'event': 'content', 'data': event.model_dump()})}\n\n".encode()
            elif isinstance(event, UserInputRequestEvent):
                yield f"data: {json.dumps({'event': 'user_input_request', 'data': event.model_dump()})}\n\n".encode()
            elif isinstance(event, ErrorEvent):
                yield f"data: {json.dumps({'event': 'error', 'data': event.model_dump()})}\n\n".encode()

        # Persist assistant response
        full_response = "".join(assistant_content_parts)

        # Stream generated files to the backend proxy so it can serve them
        # from its own /tmp. This avoids needing blob access from the hosted
        # agent container (which is outside the VNet).
        generated_files = _collect_generated_files(full_response)
        for filename, data in generated_files:
            file_event = {
                "event": "file_content",
                "data": {"filename": filename, "content": base64.b64encode(data).decode("ascii")},
            }
            yield f"data: {json.dumps(file_event)}\n\n".encode()

        stats = _copilot_agent.get_run_stats(conversation_id)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        run_stats = {
            "totalDurationMs": elapsed_ms,
            "totalToolCalls": total_tool_calls,
            "promptTokens": stats["prompt_tokens"],
            "completionTokens": stats["completion_tokens"],
            "reasoningTokens": stats.get("reasoning_tokens", 0),
            "totalTokens": stats["total_tokens"],
            "timeToFirstTokenMs": stats["time_to_first_token_ms"],
            "modelLatencyMs": stats["model_latency_ms"],
        }
        assistant_message = Message(
            id=str(uuid.uuid4()),
            conversationId=conversation_id,
            role=MessageRole.ASSISTANT,
            content=full_response,
            metadata={
                "thoughts": collected_thoughts,
                "toolCalls": collected_tool_calls,
                "runStats": run_stats,
            },
            createdAt=datetime.now(timezone.utc),
        )
        try:
            await _cosmos_service.upsert_message(assistant_message)
        except Exception:
            logger.warning("Failed to persist assistant message to Cosmos (non-fatal)", exc_info=True)

        # Done event
        done = DoneEvent(
            conversationId=conversation_id,
            totalDurationMs=elapsed_ms,
            totalToolCalls=total_tool_calls,
            promptTokens=run_stats["promptTokens"],
            completionTokens=run_stats["completionTokens"],
            reasoningTokens=run_stats["reasoningTokens"],
            totalTokens=run_stats["totalTokens"],
            timeToFirstTokenMs=run_stats["timeToFirstTokenMs"],
            modelLatencyMs=run_stats["modelLatencyMs"],
        )
        done_payload = done.model_dump()
        yield f"data: {json.dumps({'event': 'done', 'data': done_payload})}\n\n".encode()

    except Exception:
        logger.exception("Agent failed for conversation=%s", conversation_id)
        error = ErrorEvent(message="An internal error occurred", code="AGENT_ERROR")
        yield f"data: {json.dumps({'event': 'error', 'data': error.model_dump()})}\n\n".encode()

    # Final done signal for the invocations protocol
    yield f"event: done\ndata: {json.dumps({'invocation_id': invocation_id, 'conversation_id': conversation_id})}\n\n".encode()


@app.invoke_handler
async def handle_invoke(request: Request) -> Response:
    """Handle invocation requests — accepts the same payload as the FastAPI /api/agent/chat endpoint."""
    # Ensure services are initialised (first request triggers startup)
    if _copilot_agent is None:
        await _startup()

    # Read the request body exactly once and normalise it. The hosted agent is
    # invoked through several paths that frame the body differently:
    #   * ``azd ai agent invoke "msg"`` posts the message as text/plain (NOT JSON)
    #   * the Kratos backend proxy posts a JSON object
    #   * the platform keep-alive posts ``{"warmup": true}`` or an empty body
    # parse_invoke_payload coerces all of these into a dict (empty body → warmup),
    # so a plain-text CLI invoke no longer 400s on json.loads.
    data = parse_invoke_payload(await request.body())

    # Keep-warm fast-path: the backend pings the hosted agent periodically with
    # ``{"warmup": true}`` to stop the Foundry platform from scaling the container
    # to zero (which causes multi-second cold starts and gateway 408 timeouts on
    # the next real request). Running _startup() above already re-provisions and
    # initialises every service, so we return immediately without invoking the
    # model or persisting anything — this resets the platform idle timer cheaply.
    if data.get("warmup") is True:
        return JSONResponse(
            status_code=200,
            content={
                "status": "warm",
                "ready": _copilot_agent is not None,
                "startup_ms": _startup_total_ms,
                "phases": _startup_phases,
                "loaded_use_cases": list(_registries.keys()),
            },
        )

    try:
        message = data.get("message") or data.get("input")
        if not isinstance(message, str) or not message.strip():
            raise ValueError('missing or empty "message" (or "input") field')

        conversation_id = data.get("conversationId", str(uuid.uuid4()))
        use_case = data.get("useCase", "generic")

        # The proxy may embed metadata tags in the input when the Invocations
        # gateway strips custom JSON fields.  Parse them and remove from the
        # message so the CopilotAgent receives a clean user message.
        if isinstance(message, str):
            # Parse <use_case> tag (fallback when gateway strips useCase field)
            uc_match = re.search(r"<use_case>\s*(\S+?)\s*</use_case>", message)
            if uc_match:
                if use_case == "generic":
                    use_case = uc_match.group(1)
                    logger.info("Parsed useCase='%s' from input tag (gateway fallback)", use_case)
                message = message[:uc_match.start()] + message[uc_match.end():]

            # Strip <system_instructions> — the hosted agent sets the system
            # prompt via the registry, so the prepended copy is redundant.
            message = re.sub(
                r"<system_instructions>\s*.*?\s*</system_instructions>",
                "",
                message,
                flags=re.DOTALL,
            )

            # Clean up leading/trailing whitespace from tag removal
            message = message.strip()

        logger.info(
            "handle_invoke: useCase=%s conversation=%s registries=%s message_len=%d",
            use_case, conversation_id, list(_registries.keys()), len(message),
        )

    except (json.JSONDecodeError, ValueError) as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": str(e),
            },
        )

    # Lazy-load this conversation's use-case (cached after first use). A
    # pre-warmed sandbox warms only the shared core, so the first real request
    # for a given use-case pays a small one-time load instead of every sandbox
    # loading all 9 use-cases up front.
    await _ensure_registry(use_case)

    return StreamingResponse(
        _stream_response(request.state.invocation_id, conversation_id, message, use_case),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    import atexit
    import signal

    def _sync_shutdown(*_args):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_shutdown())
        loop.close()

    atexit.register(_sync_shutdown)
    signal.signal(signal.SIGTERM, lambda *a: (_sync_shutdown(), sys.exit(0)))

    app.run()
