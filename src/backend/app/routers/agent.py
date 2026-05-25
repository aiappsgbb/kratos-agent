"""Agent endpoint — forwards requests to the Foundry hosted agent and streams SSE."""

import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
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
_tracer = trace.get_tracer("kratos.agent.proxy")

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

    # Stamp kratos attributes on the current (HTTP) span so every request is
    # filterable by use-case, conversation, and optional eval run.
    eval_run_id = request.headers.get("x-kratos-eval-run-id") or ""
    request.state.eval_run_id = eval_run_id
    _span = trace.get_current_span()
    if body.useCase:
        _span.set_attribute("kratos.use_case", str(body.useCase))
    if body.conversationId:
        _span.set_attribute("kratos.conversation_id", str(body.conversationId))
    if eval_run_id:
        _span.set_attribute("kratos.eval_run_id", eval_run_id)

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

            # Replay tool/usage events as OTel child spans so the traces tab
            # can render meaningful waterfalls. The hosted Foundry agent emits
            # its own gen_ai spans to its private AppInsights — these manual
            # spans surface the same signal in the kratos-side trace tree.
            common_attrs = {
                "kratos.use_case": str(body.useCase) if body.useCase else "",
                "kratos.conversation_id": str(body.conversationId),
            }
            if eval_run_id:
                common_attrs["kratos.eval_run_id"] = eval_run_id
            open_tool_spans: dict[str, Any] = {}
            # When the SSE event doesn't carry a unique call_id, use a per-skill
            # FIFO queue so started→completed pairs match by arrival order.
            started_queue: dict[str, list[str]] = {}
            synthetic_seq = 0

            async for event_dict in foundry_proxy.invoke(
                message=body.message,
                conversation_id=body.conversationId,
                use_case=body.useCase,
                system_prompt=system_prompt,
                agent_session_id=agent_session_id,
                eval_run_id=eval_run_id or None,
            ):
                event_name = event_dict.get("event")
                event_data = event_dict.get("data", {})

                if event_name == "thought":
                    collected_thoughts.append(event_data.get("content", ""))
                    yield {"event": "thought", "data": json.dumps(event_data)}
                elif event_name == "tool_call":
                    status = event_data.get("status")
                    tool_name = (
                        event_data.get("skillName")
                        or event_data.get("skill_name")
                        or event_data.get("name")
                        or event_data.get("tool_name")
                        or event_data.get("tool")
                        or "tool"
                    )
                    real_call_id = (
                        event_data.get("id")
                        or event_data.get("call_id")
                        or event_data.get("tool_call_id")
                    )
                    if status in (None, "started", "running"):
                        if real_call_id:
                            call_id = str(real_call_id)
                        else:
                            synthetic_seq += 1
                            call_id = f"{tool_name}:{synthetic_seq}"
                            started_queue.setdefault(tool_name, []).append(call_id)
                        sp = _tracer.start_span(
                            f"tool.{tool_name}",
                            kind=trace.SpanKind.INTERNAL,
                            attributes={
                                **common_attrs,
                                "gen_ai.tool.name": str(tool_name),
                                "kratos.skill.name": str(tool_name),
                                "gen_ai.tool.kind": "skill",
                            },
                        )
                        open_tool_spans[call_id] = sp
                    elif status in ("completed", "failed", "error"):
                        if real_call_id:
                            call_id = str(real_call_id)
                        else:
                            queue = started_queue.get(tool_name) or []
                            call_id = queue.pop(0) if queue else f"{tool_name}:orphan"
                        sp = open_tool_spans.pop(call_id, None)
                        if sp is None:
                            # tool_call arrived only on completion — synthesise a span
                            sp = _tracer.start_span(
                                f"tool.{tool_name}",
                                kind=trace.SpanKind.INTERNAL,
                                attributes={
                                    **common_attrs,
                                    "gen_ai.tool.name": str(tool_name),
                                    "kratos.skill.name": str(tool_name),
                                    "gen_ai.tool.kind": "skill",
                                },
                            )
                        if status in ("failed", "error"):
                            sp.set_attribute("error.type", str(event_data.get("error", "tool_failed")))
                            sp.set_status(trace.Status(trace.StatusCode.ERROR))
                        sp.end()
                        total_tool_calls += 1
                    collected_tool_calls.append(event_data)
                    yield {"event": "tool_call", "data": json.dumps(event_data)}
                elif event_name == "usage":
                    # Replay usage as an LLM span so traces tab shows model + tokens
                    llm_sp = _tracer.start_span(
                        "chat.completions",
                        kind=trace.SpanKind.CLIENT,
                        attributes={
                            **common_attrs,
                            "gen_ai.operation.name": "chat",
                            "gen_ai.response.model": str(
                                event_data.get("model")
                                or event_data.get("modelName")
                                or proxy_done.get("model", "")
                            ),
                            "gen_ai.usage.input_tokens": int(event_data.get("promptTokens") or 0),
                            "gen_ai.usage.output_tokens": int(event_data.get("completionTokens") or 0),
                        },
                    )
                    llm_sp.end()
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

            # Close any tool spans that never received a completion
            for call_id, sp in list(open_tool_spans.items()):
                try:
                    sp.end()
                except Exception:
                    pass
            open_tool_spans.clear()

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
