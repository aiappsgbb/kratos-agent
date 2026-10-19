"""Kratos personas served over AG-UI.

The vendored adapter owns the AG-UI side: one native session per thread,
frontend tools suspended as pending RPCs, and SDK events mapped to AG-UI events.
This subclass supplies the Kratos side: the use-case registry's tools, skills,
MCP servers (with OBO bearers), system prompt and model provider, plus session
resume and per-run statistics.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ag_ui.core import BaseEvent, CustomEvent, RunAgentInput, RunFinishedEvent
from copilot.tools import Tool

from .agent import CopilotAgent as _AdapterAgent
from .agent import _Thread

if TYPE_CHECKING:
    from app.services.copilot_agent import CopilotAgent as KratosCopilotAgent

logger = logging.getLogger(__name__)

#: CUSTOM event carrying token/latency figures for the finished run.
RUN_STATS_EVENT = "kratos.run_stats"

#: Frontend tools that replace a runtime built-in of the same name. ``ask_user`` is
#: the persona skills' approval gate; in the AG-UI path the browser renders it.
BUILT_IN_OVERRIDES = frozenset({"ask_user"})


def _num(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if value:
            return int(value)
    return 0


@dataclass
class RunStats:
    """Token and latency counters for one AG-UI run, fed from native events."""

    started: float = field(default_factory=time.monotonic)
    first_token: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    tool_calls: int = 0

    def observe(self, raw: dict[str, Any]) -> None:
        kind = raw.get("type")
        data = raw.get("data") or {}
        if kind == "assistant.message_delta" and self.first_token is None:
            self.first_token = time.monotonic()
        elif kind == "assistant.usage":
            self.prompt_tokens += _num(data, "inputTokens", "input_tokens", "promptTokens")
            self.completion_tokens += _num(data, "outputTokens", "output_tokens", "completionTokens")
            self.reasoning_tokens += _num(data, "reasoningTokens", "reasoning_tokens")
        elif kind == "tool.execution_start":
            self.tool_calls += 1

    def snapshot(self) -> dict[str, int]:
        now = time.monotonic()
        return {
            "totalDurationMs": int((now - self.started) * 1000),
            "timeToFirstTokenMs": int((self.first_token - self.started) * 1000) if self.first_token else 0,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "totalTokens": self.prompt_tokens + self.completion_tokens,
            "totalToolCalls": self.tool_calls,
        }


class KratosAGUIAgent(_AdapterAgent):
    """One AG-UI agent for every persona; the use-case is chosen per thread."""

    def __init__(self, kratos: KratosCopilotAgent, *, run_timeout: float = 1800.0) -> None:
        super().__init__(client=None, name="kratos", run_timeout=run_timeout)
        self.kratos = kratos
        self._stats: dict[str, RunStats] = {}
        self._fingerprints: dict[str, str] = {}

    async def _create_session(self, thread: _Thread, input_data: RunAgentInput) -> Any:
        conversation_id = input_data.thread_id
        config, has_identity, _ = self.kratos.resolve_session_config(conversation_id)
        config = dict(config)
        # The browser answers ask_user (a frontend tool); the backend never blocks on it.
        config.pop("on_user_input_request", None)
        frontend_tools = [
            Tool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                skip_permission=True,
                overrides_built_in_tool=tool.name in BUILT_IN_OVERRIDES,
                # Browser tools carry exact argument schemas (charts, tables);
                # a deferred tool shows the model only its name, and it guesses.
                defer="never",
            )
            for tool in input_data.tools
        ]
        config["tools"] = [*config.get("tools", []), *frontend_tools]

        def on_event(event: Any) -> None:
            raw = event.to_dict()
            stats = self._stats.get(conversation_id)
            if stats is not None:
                stats.observe(raw)
            thread.queue.put_nowait(raw)

        config["on_event"] = on_event

        client = self.kratos.client
        if client is None:
            raise RuntimeError("Copilot client is not started")
        cosmos = self.kratos.cosmos_service

        # Identity-bearing (OBO) sessions are never resumed: the CLI freezes MCP
        # auth headers at create time (same rule as the legacy path).
        sdk_session_id = None
        if not has_identity and cosmos is not None:
            sdk_session_id = await cosmos.get_session_mapping(conversation_id)
        if sdk_session_id:
            try:
                session = await client.resume_session(sdk_session_id, **config)
                logger.info("AG-UI resumed SDK session=%s thread=%s", sdk_session_id, conversation_id)
                return session
            except Exception:
                logger.warning("AG-UI resume failed for thread=%s; creating new", conversation_id, exc_info=True)

        session = await client.create_session(**config)
        if not has_identity and cosmos is not None and getattr(session, "session_id", None):
            await cosmos.upsert_session_mapping(conversation_id, session.session_id)
        logger.info(
            "AG-UI created SDK session=%s thread=%s frontend_tools=%s",
            getattr(session, "session_id", "?"),
            conversation_id,
            [t.name for t in frontend_tools],
        )
        return session

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[BaseEvent]:
        thread_id = input_data.thread_id
        thread = self._threads.get(thread_id)
        fingerprint = self.kratos.identity_fingerprint(thread_id)
        if (
            thread is not None
            and not thread.busy
            and not thread.pending
            and self._fingerprints.get(thread_id) != fingerprint
        ):
            # The user's OBO bearer changed (refresh, sign-in, sign-out). MCP auth
            # headers are frozen at create time, so rebuild the session.
            logger.info("AG-UI identity changed for thread=%s; rebuilding session", thread_id)
            await self._dispose(thread_id)
            thread = None
        # A continuation run resolves calls on the session as built; keep the
        # fingerprint it was created with until those calls are settled.
        if thread is None or not thread.pending:
            self._fingerprints[thread_id] = fingerprint

        self._stats[thread_id] = stats = RunStats()
        try:
            async for event in super().run(input_data):
                if isinstance(event, RunFinishedEvent):
                    yield CustomEvent(name=RUN_STATS_EVENT, value=stats.snapshot())
                yield event
        finally:
            self._stats.pop(thread_id, None)
