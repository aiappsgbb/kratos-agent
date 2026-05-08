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
_registries: dict[str, SkillRegistry] = {}
_settings: Settings | None = None

app = InvocationAgentServerHost()


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def _apm_startup_sync(apm_service: ApmService, use_cases_root: str) -> tuple[int, int]:
    """Run ``apm install`` for each local use-case that needs syncing."""
    from pathlib import Path

    root = Path(use_cases_root)
    if not root.is_dir():
        return (0, 0)

    synced = 0
    total = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        total += 1
        try:
            if not await apm_service.needs_sync(entry.name):
                continue
            await apm_service.sync(entry.name)
            synced += 1
        except ApmError as exc:
            logger.warning("APM sync failed for '%s': %s", entry.name, exc)
    return (synced, total)


async def _startup() -> None:
    """Initialise all services — mirrors the FastAPI lifespan startup."""
    global _copilot_agent, _cosmos_service, _settings

    _settings = get_settings()

    # Setup OpenTelemetry
    setup_telemetry(_settings)

    # Cosmos DB
    _cosmos_service = CosmosService(_settings)
    await _cosmos_service.initialize()

    # Blob Storage for skills
    blob_service = BlobSkillService(_settings)
    await blob_service.initialize()

    # APM service
    apm_service = ApmService(_settings, blob_service)

    if _settings.apm_enabled and _settings.apm_startup_sync:
        synced, total = await _apm_startup_sync(apm_service, _settings.apm_use_cases_root)
        logger.info("APM startup sync: %d/%d use-cases synced", synced, total)

    # Load all use-case registries
    if blob_service.is_available:
        try:
            seeded = await blob_service.seed_from_local()
            if seeded:
                logger.info("Seeded %d use-case(s) into blob", len(seeded))
            for uc_name in await blob_service.list_use_cases():
                registry = SkillRegistry()
                await registry.load(uc_name, blob_service, apm_service=apm_service)
                _registries[uc_name] = registry
        except Exception:
            logger.exception("Failed to load use-cases from blob storage — falling back to local disk")

    if not _registries:
        # Blob unavailable or failed — load from baked-in local use-cases directory
        logger.info("Loading use-cases from local disk: %s", _settings.apm_use_cases_root)
        from pathlib import Path

        uc_root = Path(_settings.apm_use_cases_root)
        if uc_root.is_dir():
            for entry in sorted(uc_root.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    registry = SkillRegistry()
                    await registry.load(entry.name, apm_service=apm_service, local_root=str(uc_root))
                    _registries[entry.name] = registry
        else:
            logger.warning("Local use-cases directory not found: %s", uc_root)

    logger.info("Loaded %d use-cases: %s", len(_registries), list(_registries.keys()))

    # Copilot SDK agent
    _copilot_agent = CopilotAgent(_settings)
    _copilot_agent.set_registries(_registries)
    _copilot_agent.set_cosmos_service(_cosmos_service)
    await _copilot_agent.start()

    logger.info(
        "Kratos Hosted Agent started — environment=%s foundry_endpoint=%s model=%s",
        _settings.environment,
        _settings.foundry_endpoint[:80] if _settings.foundry_endpoint else "(empty)",
        _settings.foundry_model_deployment or "(empty)",
    )


async def _shutdown() -> None:
    """Cleanup on shutdown."""
    if _copilot_agent:
        await _copilot_agent.stop()
    if _cosmos_service:
        await _cosmos_service.close()
    logger.info("Kratos Hosted Agent stopped")


# ─── Invocation Handler ─────────────────────────────────────────────────────

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

    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("body is not a JSON object")

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
