"""Agent endpoint — forwards requests to the Foundry hosted agent and streams SSE."""

import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.models import (
    AgentRequest,
    DoneEvent,
    ErrorEvent,
    FollowUpQuestionsEvent,
    Message,
    MessageRole,
)
from app.services.follow_up_service import generate_follow_ups

logger = logging.getLogger(__name__)

router = APIRouter()

_SAFE_FILENAME_RE = re.compile(r"^[\w\-. ]+$")


def _save_streamed_file(event_data: dict) -> None:
    """Save a file streamed from the hosted agent to /tmp."""
    filename = event_data.get("filename", "")
    content_b64 = event_data.get("content", "")
    if not filename or not content_b64:
        return
    if not _SAFE_FILENAME_RE.match(filename):
        logger.warning("Ignoring streamed file with unsafe name: %s", filename)
        return
    try:
        data = base64.b64decode(content_b64)
        path = f"/tmp/{filename}"  # noqa: S108
        with open(path, "wb") as f:
            f.write(data)
        logger.info("Saved streamed file: %s (%d bytes)", path, len(data))
    except Exception:
        logger.warning("Failed to save streamed file: %s", filename, exc_info=True)


@router.post("/chat")
async def chat(body: AgentRequest, request: Request) -> EventSourceResponse:
    """Forward the request to the Foundry hosted agent and stream results as SSE.

    The response is a stream of JSON events:
    - thought: Agent reasoning / plan
    - tool_call: MCP skill invocation (started/completed/failed)
    - content: Response text chunks
    - done: Completion signal with metrics
    - error: Error details
    """
    cosmos = request.app.state.cosmos_service
    foundry_proxy = request.app.state.foundry_proxy

    async def event_generator():  # noqa: ANN202
        start_time = time.monotonic()
        total_tool_calls = 0

        try:
            # Persist user message
            user_message = Message(
                id=str(uuid.uuid4()),
                conversationId=body.conversationId,
                role=MessageRole.USER,
                content=body.message,
                createdAt=datetime.now(timezone.utc),
            )
            await cosmos.upsert_message(user_message)

            # Resolve use-case system prompt from the registry
            registries = getattr(request.app.state, "registries", {})
            registry = registries.get(body.useCase)
            system_prompt = getattr(registry, "system_prompt", None) if registry else None

            # Look up existing gateway session ID so the hosted agent
            # container (and its in-process CopilotClient state) is reused.
            agent_session_id = await cosmos.get_session_mapping(body.conversationId)
            logger.info("Session lookup for conversation=%s: agent_session_id=%s", body.conversationId, agent_session_id)

            # Stream events from the Foundry hosted agent
            assistant_content_parts: list[str] = []
            collected_thoughts: list[str] = []
            collected_tool_calls: list[dict] = []
            proxy_done: dict = {}
            gateway_session_id: str | None = None

            async for event_dict in foundry_proxy.invoke(
                message=body.message,
                conversation_id=body.conversationId,
                use_case=body.useCase,
                system_prompt=system_prompt,
                agent_session_id=agent_session_id,
            ):
                event_name = event_dict.get("event")
                event_data = event_dict.get("data", {})

                if event_name == "thought":
                    collected_thoughts.append(event_data.get("content", ""))
                    yield {"event": "thought", "data": json.dumps(event_data)}
                elif event_name == "tool_call":
                    if event_data.get("status") == "completed":
                        total_tool_calls += 1
                    collected_tool_calls.append(event_data)
                    yield {"event": "tool_call", "data": json.dumps(event_data)}
                elif event_name == "usage":
                    yield {"event": "usage", "data": json.dumps(event_data)}
                elif event_name == "content":
                    assistant_content_parts.append(event_data.get("content", ""))
                    yield {"event": "content", "data": json.dumps(event_data)}
                elif event_name == "file_content":
                    # Hosted agent streams generated files — save to /tmp for
                    # the download endpoint to serve. Do NOT forward to frontend.
                    _save_streamed_file(event_data)
                elif event_name == "user_input_request":
                    yield {"event": "user_input_request", "data": json.dumps(event_data)}
                elif event_name == "error":
                    yield {"event": "error", "data": json.dumps(event_data)}
                elif event_name == "done":
                    proxy_done = event_data
                elif event_name == "_gateway_session":
                    gateway_session_id = event_data.get("agentSessionId")

            # Persist gateway session ID so subsequent messages reuse the
            # same hosted agent container (preserving CopilotClient state).
            if gateway_session_id:
                logger.info("Gateway session for conversation=%s: %s", body.conversationId, gateway_session_id)
                try:
                    await cosmos.upsert_session_mapping(body.conversationId, gateway_session_id)
                except Exception:
                    logger.warning("Failed to persist gateway session mapping (non-fatal)", exc_info=True)

            # Persist assistant response with execution details
            full_response = "".join(assistant_content_parts)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            run_stats = {
                "totalDurationMs": elapsed_ms,
                "totalToolCalls": total_tool_calls,
                "promptTokens": proxy_done.get("promptTokens", 0),
                "completionTokens": proxy_done.get("completionTokens", 0),
                "reasoningTokens": proxy_done.get("reasoningTokens", 0),
                "totalTokens": proxy_done.get("totalTokens", 0),
                "timeToFirstTokenMs": proxy_done.get("timeToFirstTokenMs", 0),
                "modelLatencyMs": proxy_done.get("modelLatencyMs", 0),
            }
            assistant_message = Message(
                id=str(uuid.uuid4()),
                conversationId=body.conversationId,
                role=MessageRole.ASSISTANT,
                content=full_response,
                metadata={
                    "thoughts": collected_thoughts,
                    "toolCalls": collected_tool_calls,
                    "runStats": run_stats,
                },
                createdAt=datetime.now(timezone.utc),
            )
            await cosmos.upsert_message(assistant_message)

            # Generate follow-up questions (best-effort, non-blocking)
            try:
                registries = getattr(request.app.state, "registries", {})
                registry = registries.get(body.useCase)
                skill_names = [s.name for s in registry.skills if s.enabled] if registry else []
                follow_ups = await generate_follow_ups(body.message, full_response, skill_names)
                if follow_ups:
                    yield {"event": "follow_up_questions", "data": json.dumps(FollowUpQuestionsEvent(questions=follow_ups).model_dump())}
            except Exception:
                logger.debug("Follow-up generation skipped", exc_info=True)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            done = DoneEvent(
                conversationId=body.conversationId,
                totalDurationMs=elapsed_ms,
                totalToolCalls=total_tool_calls,
                promptTokens=run_stats["promptTokens"],
                completionTokens=run_stats["completionTokens"],
                reasoningTokens=run_stats["reasoningTokens"],
                totalTokens=run_stats["totalTokens"],
                timeToFirstTokenMs=run_stats["timeToFirstTokenMs"],
                modelLatencyMs=run_stats["modelLatencyMs"],
            )
            yield {"event": "done", "data": json.dumps(done.model_dump())}

        except Exception:
            logger.exception("Agent proxy failed for conversation=%s", body.conversationId)
            error = ErrorEvent(message="An internal error occurred", code="AGENT_ERROR")
            yield {"event": "error", "data": json.dumps(error.model_dump())}

    return EventSourceResponse(event_generator())


@router.post("/user-input")
async def user_input_response(request: Request) -> JSONResponse:
    """User input responses are not supported via the hosted agent proxy."""
    return JSONResponse(
        status_code=501,
        content={"error": "User input is handled directly by the hosted agent"},
    )
