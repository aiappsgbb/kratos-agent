"""AG-UI endpoint: relays a CopilotKit / AG-UI run to the hosted agent.

The browser talks to the Next.js CopilotKit runtime, whose ``HttpAgent`` posts a
``RunAgentInput`` here. This route forwards it to the Foundry hosted agent (which
runs the Copilot SDK behind the AG-UI adapter) and streams the AG-UI events back.

Along the way it keeps the Kratos-side duties of the legacy ``/api/agent/chat``
route: gateway-session affinity, Cosmos persistence, generated-file capture,
follow-up suggestions and OTel spans for the traces tab. The run is detached from
the HTTP request so it completes and persists even if the client disconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ag_ui.core import RunAgentInput
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import context as otel_context
from opentelemetry import trace
from pydantic import ValidationError

from app.models import Message, MessageRole
from app.routers.agent import _save_streamed_file
from app.services.follow_up_service import generate_follow_ups

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("kratos.agui.proxy")

router = APIRouter()

RUN_STATS_EVENT = "kratos.run_stats"
FILE_CONTENT_EVENT = "kratos.file_content"
FOLLOW_UPS_EVENT = "kratos.follow_ups"
_FOLLOW_UP_TIMEOUT_S = 6.0

_background_runs: set[asyncio.Task] = set()


def _text_of(content: Any) -> str:
    """Plain text of an AG-UI message content (string or multimodal parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(getattr(p, "text", "") for p in content if getattr(p, "type", None) == "text")
    return ""


@dataclass
class _ToolCall:
    id: str
    name: str
    args: str = ""
    result: str | None = None
    span: Any = None


@dataclass
class _RunRecord:
    """What the relay learns from the AG-UI stream, for persistence and traces."""

    text: list[str] = field(default_factory=list)
    tools: dict[str, _ToolCall] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    gateway_session: str | None = None


def _safe_tokens(props: dict[str, Any]) -> dict[str, str]:
    raw = props.get("mcpAccessTokens")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str) and v}


@router.post("")
async def run_agui(request: Request) -> Any:
    try:
        run_input = RunAgentInput.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        return JSONResponse(status_code=422, content={"error": "invalid RunAgentInput", "detail": str(exc)[:500]})

    props = run_input.forwarded_props if isinstance(run_input.forwarded_props, dict) else {}
    use_case = str(props.get("useCase") or "generic")
    mcp_tokens = _safe_tokens(props)
    conversation_id = run_input.thread_id
    eval_run_id = request.headers.get("x-kratos-eval-run-id") or ""

    span = trace.get_current_span()
    span.set_attribute("kratos.use_case", use_case)
    span.set_attribute("kratos.conversation_id", conversation_id)
    if eval_run_id:
        span.set_attribute("kratos.eval_run_id", eval_run_id)

    # Relay the run without the OBO bearers: they travel out-of-band in the
    # hosted-agent body field, never inside the AG-UI payload or the prompt.
    relayed = run_input.model_dump(mode="json", by_alias=True, exclude_none=True)
    relayed["forwardedProps"] = {k: v for k, v in props.items() if k != "mcpAccessTokens"}

    app = request.app
    otel_ctx = otel_context.get_current()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def relay() -> None:
        token = otel_context.attach(otel_ctx)
        try:
            await _relay_run(app, run_input, relayed, use_case, mcp_tokens, eval_run_id, queue)
        except Exception:
            logger.exception("AG-UI relay failed for thread=%s", conversation_id)
            await queue.put({"type": "RUN_ERROR", "message": "An internal error occurred", "code": "AGENT_ERROR"})
        finally:
            await queue.put(sentinel)
            otel_context.detach(token)

    task = asyncio.create_task(relay())
    _background_runs.add(task)
    task.add_done_callback(_background_runs.discard)

    async def stream():  # noqa: ANN202
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield f"data: {json.dumps(item, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def _relay_run(
    app: Any,
    run_input: RunAgentInput,
    relayed: dict[str, Any],
    use_case: str,
    mcp_tokens: dict[str, str],
    eval_run_id: str,
    queue: asyncio.Queue,
) -> None:
    cosmos = app.state.cosmos_service
    proxy = app.state.foundry_proxy
    conversation_id = run_input.thread_id
    frontend_tools = {t.name for t in run_input.tools}
    common_attrs = {"kratos.use_case": use_case, "kratos.conversation_id": conversation_id}
    if eval_run_id:
        common_attrs["kratos.eval_run_id"] = eval_run_id

    last = run_input.messages[-1] if run_input.messages else None
    if last is not None and last.role == "user":
        await _persist(cosmos, conversation_id, MessageRole.USER, _text_of(last.content), message_id=last.id)
    elif last is not None and last.role == "tool":
        # The browser's answer to a frontend tool (e.g. an ask_user approval).
        await _persist(
            cosmos,
            conversation_id,
            MessageRole.TOOL,
            str(last.content or ""),
            message_id=last.id,
            metadata={"agui": {"toolCallId": last.tool_call_id}},
        )

    record = _RunRecord()
    held_finish: dict | None = None
    agent_session_id = await cosmos.get_session_mapping(conversation_id)

    async for event in proxy.invoke_agui(
        relayed,
        use_case=use_case,
        agent_session_id=agent_session_id,
        eval_run_id=eval_run_id or None,
        mcp_access_tokens=mcp_tokens,
    ):
        kind = event.get("type")
        if kind == "_gateway_session":
            record.gateway_session = event.get("agentSessionId")
            continue
        if kind == "CUSTOM" and event.get("name") == FILE_CONTENT_EVENT:
            _save_streamed_file(event.get("value") or {})
            continue
        if kind == "CUSTOM" and event.get("name") == RUN_STATS_EVENT:
            record.stats = event.get("value") or {}
        _observe(record, event, common_attrs)
        if kind == "RUN_FINISHED":
            # Follow-ups must precede RUN_FINISHED: AG-UI clients reject events after it.
            held_finish = event
            continue
        await queue.put(event)

    for call in record.tools.values():
        if call.span is not None:
            with contextlib.suppress(Exception):
                call.span.end()

    if record.gateway_session:
        try:
            await cosmos.upsert_session_mapping(conversation_id, record.gateway_session)
        except Exception:
            logger.warning("Failed to persist gateway session mapping (non-fatal)", exc_info=True)

    full_text = "".join(record.text)
    tool_calls = list(record.tools.values())
    if full_text or tool_calls:
        await _persist(
            cosmos,
            conversation_id,
            MessageRole.ASSISTANT,
            full_text,
            metadata={
                "toolCalls": [
                    {
                        "skillName": c.name,
                        "status": "completed" if c.result is not None else "pending",
                        "input": c.args,
                        "output": (c.result or "")[:2000],
                    }
                    for c in tool_calls
                ],
                "runStats": record.stats,
                "agui": {
                    "toolCalls": [{"id": c.id, "name": c.name, "args": c.args, "result": c.result} for c in tool_calls]
                },
            },
        )

    if held_finish is None:
        return
    paused = any(c.name in frontend_tools and c.result is None for c in tool_calls)
    if full_text and not paused and not record.error:
        follow_ups = await _follow_ups(app, run_input, use_case, full_text)
        if follow_ups:
            await queue.put({"type": "CUSTOM", "name": FOLLOW_UPS_EVENT, "value": {"questions": follow_ups}})
    await queue.put(held_finish)


def _observe(record: _RunRecord, event: dict[str, Any], common_attrs: dict[str, str]) -> None:
    kind = event.get("type")
    if kind == "TEXT_MESSAGE_CONTENT" and not event.get("subagentRunId"):
        record.text.append(event.get("delta") or "")
    elif kind == "TOOL_CALL_START":
        call_id = event["toolCallId"]
        name = event.get("toolCallName") or "tool"
        record.tools[call_id] = _ToolCall(
            id=call_id,
            name=name,
            span=_tracer.start_span(
                f"tool.{name}",
                kind=trace.SpanKind.INTERNAL,
                attributes={
                    **common_attrs,
                    "gen_ai.tool.name": name,
                    "gen_ai.tool.call.id": call_id,
                    "kratos.skill.name": name,
                    "gen_ai.tool.kind": "skill",
                },
            ),
        )
    elif kind == "TOOL_CALL_ARGS":
        call = record.tools.get(event.get("toolCallId", ""))
        if call is not None:
            call.args += event.get("delta") or ""
    elif kind == "TOOL_CALL_RESULT":
        call = record.tools.get(event.get("toolCallId", ""))
        if call is not None:
            call.result = str(event.get("content") or "")
            if call.span is not None:
                call.span.end()
                call.span = None
    elif kind == "CUSTOM" and event.get("name") == RUN_STATS_EVENT:
        stats = event.get("value") or {}
        llm_span = _tracer.start_span(
            "chat.completions",
            kind=trace.SpanKind.CLIENT,
            attributes={
                **common_attrs,
                "gen_ai.operation.name": "chat",
                "gen_ai.usage.input_tokens": int(stats.get("promptTokens") or 0),
                "gen_ai.usage.output_tokens": int(stats.get("completionTokens") or 0),
            },
        )
        llm_span.end()
    elif kind == "RUN_ERROR":
        record.error = str(event.get("message") or "error")
        for call in record.tools.values():
            if call.span is not None:
                call.span.set_status(trace.Status(trace.StatusCode.ERROR))


async def _follow_ups(app: Any, run_input: RunAgentInput, use_case: str, response: str) -> list[str]:
    users = [m for m in run_input.messages if m.role == "user"]
    question = _text_of(users[-1].content) if users else ""
    registry = getattr(app.state, "registries", {}).get(use_case)
    skills = getattr(registry, "skills", None) or []
    skills = skills.values() if isinstance(skills, dict) else skills
    skill_names = [s.name for s in skills if getattr(s, "enabled", False)]
    try:
        return await asyncio.wait_for(generate_follow_ups(question, response, skill_names), _FOLLOW_UP_TIMEOUT_S)
    except Exception:
        logger.debug("Follow-up generation skipped", exc_info=True)
        return []


async def _persist(
    cosmos: Any,
    conversation_id: str,
    role: MessageRole,
    content: str,
    *,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        await cosmos.upsert_message(
            Message(
                id=message_id or str(uuid.uuid4()),
                conversationId=conversation_id,
                role=role,
                content=content,
                metadata=metadata or {},
                createdAt=datetime.now(UTC),
            )
        )
    except Exception:
        logger.warning("Failed to persist %s message (non-fatal)", role.value, exc_info=True)
