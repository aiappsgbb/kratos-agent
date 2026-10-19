"""Tests for the AG-UI path: the Kratos adapter subclass, the proxy and the relay route."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ag_ui.core import RunAgentInput
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agui import RUN_STATS_EVENT, KratosAGUIAgent
from app.config import Settings
from app.routers import agui as agui_router
from app.services.copilot_agent import CopilotAgent
from app.services.foundry_agent_proxy import FoundryAgentProxy

ASK_USER_TOOL = {
    "name": "ask_user",
    "description": "Ask the user",
    "parameters": {"type": "object", "properties": {"question": {"type": "string"}}},
}


class _Event:
    def __init__(self, kind: str, data: dict, event_id: str | None = None):
        self._raw = {"type": kind, "data": data, "id": event_id or f"{kind}:{json.dumps(data, sort_keys=True)}"}

    def to_dict(self) -> dict:
        return self._raw


class _FakeSession:
    """Plays a scripted list of native events for each prompt or resolved call."""

    def __init__(self, on_event, scripts):
        self.session_id = "sdk-1"
        self._on_event = on_event
        self._scripts = scripts
        self.sent: list[str] = []
        self.resolved: list = []
        self.rpc = SimpleNamespace(tools=SimpleNamespace(handle_pending_tool_call=self._resolve))

    def _play(self):
        for kind, data in self._scripts.pop(0):
            self._on_event(_Event(kind, data))

    async def send(self, prompt, **_kwargs):
        self.sent.append(prompt)
        self._play()

    async def _resolve(self, request):
        self.resolved.append(request)
        self._play()
        return SimpleNamespace(success=True)

    async def abort(self):
        return None

    async def disconnect(self):
        return None


def _text_turn(message_id: str, text: str) -> list:
    return [
        ("assistant.message_start", {"messageId": message_id}),
        ("assistant.message_delta", {"messageId": message_id, "deltaContent": text}),
        ("assistant.usage", {"inputTokens": 100, "outputTokens": 7}),
        ("assistant.message", {"messageId": message_id, "content": text}),
        ("session.idle", {}),
    ]


def _kratos(client, *, has_identity=False, mapping=None):
    kratos = MagicMock(spec=CopilotAgent)
    kratos.client = client
    kratos.cosmos_service = AsyncMock()
    kratos.cosmos_service.get_session_mapping.return_value = mapping
    kratos.identity_fingerprint.return_value = "fp-1"
    kratos.resolve_session_config.side_effect = lambda _cid: (
        {"model": "m", "streaming": True, "tools": [], "on_user_input_request": object()},
        has_identity,
        "fp-1",
    )
    return kratos


def _client(scripts):
    client = MagicMock()
    holder: dict = {}

    async def create_session(**config):
        holder["config"] = config
        holder["session"] = _FakeSession(config["on_event"], scripts)
        return holder["session"]

    async def resume_session(session_id, **config):
        holder["resumed"] = session_id
        return await create_session(**config)

    client.create_session = AsyncMock(side_effect=create_session)
    client.resume_session = AsyncMock(side_effect=resume_session)
    return client, holder


def _input(thread_id="t1", run_id="r1", messages=None, tools=None) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": thread_id,
            "runId": run_id,
            "state": {},
            "messages": messages or [{"id": "u1", "role": "user", "content": "hello"}],
            "tools": tools or [],
            "context": [],
            "forwardedProps": {},
        }
    )


async def _collect(agent, run_input):
    return [e async for e in agent.run(run_input)]


async def test_session_uses_kratos_config_and_frontend_tools():
    client, holder = _client([_text_turn("m1", "Hi")])
    agent = KratosAGUIAgent(_kratos(client))

    events = await _collect(agent, _input(tools=[ASK_USER_TOOL]))

    config = holder["config"]
    assert "on_user_input_request" not in config  # the browser answers ask_user
    [tool] = config["tools"]
    assert tool.name == "ask_user"
    assert tool.handler is None  # handler-less: the runtime suspends the call
    assert tool.overrides_built_in_tool is True
    assert tool.defer == "never"  # the model must always see the exact schema
    assert [e.type.value for e in events][0] == "RUN_STARTED"
    assert events[-1].type.value == "RUN_FINISHED"


async def test_run_stats_custom_event_precedes_run_finished():
    client, _ = _client([_text_turn("m1", "Hi")])
    agent = KratosAGUIAgent(_kratos(client))

    events = await _collect(agent, _input())

    stats = events[-2]
    assert stats.type.value == "CUSTOM" and stats.name == RUN_STATS_EVENT
    assert stats.value["promptTokens"] == 100
    assert stats.value["completionTokens"] == 7
    assert stats.value["totalTokens"] == 107


async def test_resumes_persisted_session_and_persists_new_ones():
    client, holder = _client([_text_turn("m1", "Hi")])
    kratos = _kratos(client, mapping="sdk-old")
    await _collect(KratosAGUIAgent(kratos), _input())
    assert holder["resumed"] == "sdk-old"
    kratos.cosmos_service.upsert_session_mapping.assert_not_awaited()

    client, holder = _client([_text_turn("m1", "Hi")])
    kratos = _kratos(client, mapping=None)
    await _collect(KratosAGUIAgent(kratos), _input())
    kratos.cosmos_service.upsert_session_mapping.assert_awaited_once_with("t1", "sdk-1")


async def test_identity_sessions_are_never_resumed_or_persisted():
    client, holder = _client([_text_turn("m1", "Hi")])
    kratos = _kratos(client, has_identity=True, mapping="sdk-old")
    await _collect(KratosAGUIAgent(kratos), _input())
    assert "resumed" not in holder
    kratos.cosmos_service.get_session_mapping.assert_not_awaited()
    kratos.cosmos_service.upsert_session_mapping.assert_not_awaited()


async def test_ask_user_pauses_then_continuation_resolves_the_same_call():
    pause = [
        (
            "external_tool.requested",
            {"requestId": "req-1", "toolCallId": "call-1", "toolName": "ask_user", "arguments": {"question": "OK?"}},
        )
    ]
    resume = [
        ("tool.execution_complete", {"toolCallId": "call-1", "result": {"content": "Yes"}}),
        *_text_turn("m2", "Done."),
    ]
    client, holder = _client([pause, resume])
    agent = KratosAGUIAgent(_kratos(client))

    first = await _collect(agent, _input(tools=[ASK_USER_TOOL]))
    kinds = [e.type.value for e in first]
    assert "TOOL_CALL_START" in kinds and "RUN_ERROR" not in kinds
    assert kinds[-1] == "RUN_FINISHED"

    continuation = _input(
        run_id="r2",
        tools=[ASK_USER_TOOL],
        messages=[
            {"id": "u1", "role": "user", "content": "hello"},
            {
                "id": "a1",
                "role": "assistant",
                "toolCalls": [
                    {"id": "call-1", "type": "function", "function": {"name": "ask_user", "arguments": "{}"}}
                ],
            },
            {"id": "t1", "role": "tool", "toolCallId": "call-1", "content": "Yes"},
        ],
    )
    second = await _collect(agent, continuation)

    session = holder["session"]
    assert session.sent == ["hello"]  # the answer was not re-sent as a prompt
    [request] = session.resolved
    assert request.request_id == "req-1" and request.result == "Yes"
    assert "TOOL_CALL_RESULT" in [e.type.value for e in second]


async def test_restart_with_tool_history_still_accepts_a_new_prompt():
    client, holder = _client([_text_turn("m3", "Again")])
    agent = KratosAGUIAgent(_kratos(client))
    history = [
        {"id": "u1", "role": "user", "content": "first"},
        {
            "id": "a1",
            "role": "assistant",
            "toolCalls": [{"id": "c1", "type": "function", "function": {"name": "skill", "arguments": "{}"}}],
        },
        {"id": "r1", "role": "tool", "toolCallId": "c1", "content": "ok"},
        {"id": "u2", "role": "user", "content": "second"},
    ]

    events = await _collect(agent, _input(messages=history))

    assert "RUN_ERROR" not in [e.type.value for e in events]
    assert holder["session"].sent == ["second"]


async def test_continuation_after_lost_session_errors_clearly():
    client, _ = _client([])
    agent = KratosAGUIAgent(_kratos(client))
    messages = [
        {"id": "u1", "role": "user", "content": "hello"},
        {"id": "t1", "role": "tool", "toolCallId": "gone", "content": "Yes"},
    ]

    events = await _collect(agent, _input(messages=messages))

    assert events[-1].type.value == "RUN_ERROR"
    assert "lost" in events[-1].message


async def test_identity_change_rebuilds_an_idle_thread():
    client, _ = _client([_text_turn("m1", "Hi"), _text_turn("m2", "Hi again")])
    kratos = _kratos(client)
    agent = KratosAGUIAgent(kratos)
    await _collect(agent, _input())
    assert client.create_session.await_count == 1

    kratos.identity_fingerprint.return_value = "fp-2"
    client2, _ = _client([_text_turn("m2", "Hi again")])
    kratos.client = client2
    await _collect(
        agent,
        _input(
            run_id="r2",
            messages=[{"id": "u1", "role": "user", "content": "hello"}, {"id": "u2", "role": "user", "content": "x"}],
        ),
    )
    assert client2.create_session.await_count == 1


# ─── Proxy parsing ───


def test_parse_agui_block():
    parse = FoundryAgentProxy._parse_agui_block
    assert parse('data: {"type":"RUN_STARTED","threadId":"t","runId":"r"}') == {
        "type": "RUN_STARTED",
        "threadId": "t",
        "runId": "r",
    }
    assert parse('event: done\ndata: {"invocation_id":"x"}') is None
    assert parse("data: not-json") is None
    assert parse('data: {"no_type":1}') is None


# ─── Relay route ───


def _relay_app(events, cosmos):
    app = FastAPI()
    app.include_router(agui_router.router, prefix="/api/agui")
    proxy = MagicMock()
    captured: dict = {}

    async def invoke_agui(relayed, **kwargs):
        captured["relayed"] = relayed
        captured["kwargs"] = kwargs
        for e in events:
            yield e

    proxy.invoke_agui = invoke_agui
    app.state.foundry_proxy = proxy
    app.state.cosmos_service = cosmos
    app.state.registries = {}
    return app, captured


def _sse(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_relay_persists_strips_tokens_and_orders_follow_ups():
    cosmos = AsyncMock()
    cosmos.get_session_mapping.return_value = "gw-old"
    events = [
        {"type": "RUN_STARTED", "threadId": "t1", "runId": "r1"},
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "servicenow-get_ticket"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"id":"INC-1"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {"type": "TOOL_CALL_RESULT", "messageId": "m", "toolCallId": "c1", "content": "ticket"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "Done."},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "CUSTOM", "name": "kratos.file_content", "value": {"filename": "a.txt", "content": "eA=="}},
        {"type": "CUSTOM", "name": RUN_STATS_EVENT, "value": {"promptTokens": 1, "completionTokens": 2}},
        {"type": "RUN_FINISHED", "threadId": "t1", "runId": "r1"},
        {"type": "_gateway_session", "agentSessionId": "gw-new"},
    ]
    app, captured = _relay_app(events, cosmos)
    body = {
        "threadId": "t1",
        "runId": "r1",
        "state": {},
        "messages": [{"id": "u1", "role": "user", "content": "Check INC-1"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"useCase": "it-service-desk", "mcpAccessTokens": {"graph-obo": "secret"}},
    }
    with (
        patch.object(agui_router, "generate_follow_ups", AsyncMock(return_value=["Next?"])),
        patch.object(agui_router, "_save_streamed_file") as save_file,
    ):
        out = _sse(TestClient(app).post("/api/agui", json=body).text)

    kinds = [e["type"] for e in out]
    assert kinds[-1] == "RUN_FINISHED"
    assert out[-2] == {"type": "CUSTOM", "name": "kratos.follow_ups", "value": {"questions": ["Next?"]}}
    assert not any(e.get("name") == "kratos.file_content" for e in out)
    assert "_gateway_session" not in kinds
    save_file.assert_called_once()

    assert captured["relayed"]["forwardedProps"] == {"useCase": "it-service-desk"}
    assert captured["kwargs"]["mcp_access_tokens"] == {"graph-obo": "secret"}
    assert captured["kwargs"]["agent_session_id"] == "gw-old"
    cosmos.upsert_session_mapping.assert_awaited_once_with("t1", "gw-new")

    persisted = [c.args[0] for c in cosmos.upsert_message.await_args_list]
    assert [m.role.value for m in persisted] == ["user", "assistant"]
    assert persisted[0].id == "u1" and persisted[0].content == "Check INC-1"
    assistant = persisted[1]
    assert assistant.content == "Done."
    assert assistant.metadata["agui"]["toolCalls"] == [
        {"id": "c1", "name": "servicenow-get_ticket", "args": '{"id":"INC-1"}', "result": "ticket"}
    ]


def test_relay_skips_follow_ups_while_paused_on_a_frontend_tool():
    cosmos = AsyncMock()
    cosmos.get_session_mapping.return_value = None
    events = [
        {"type": "RUN_STARTED", "threadId": "t1", "runId": "r1"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "Draft ready."},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "ask_user"},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {"type": "RUN_FINISHED", "threadId": "t1", "runId": "r1"},
    ]
    app, _ = _relay_app(events, cosmos)
    body = {
        "threadId": "t1",
        "runId": "r1",
        "state": {},
        "messages": [{"id": "u1", "role": "user", "content": "Do it"}],
        "tools": [ASK_USER_TOOL],
        "context": [],
        "forwardedProps": {},
    }
    follow_ups = AsyncMock(return_value=["x"])
    with patch.object(agui_router, "generate_follow_ups", follow_ups):
        out = _sse(TestClient(app).post("/api/agui", json=body).text)

    follow_ups.assert_not_awaited()
    assert out[-1]["type"] == "RUN_FINISHED"


def test_relay_persists_a_frontend_tool_answer():
    cosmos = AsyncMock()
    cosmos.get_session_mapping.return_value = None
    app, _ = _relay_app([{"type": "RUN_FINISHED", "threadId": "t1", "runId": "r2"}], cosmos)
    body = {
        "threadId": "t1",
        "runId": "r2",
        "state": {},
        "messages": [
            {"id": "u1", "role": "user", "content": "Do it"},
            {"id": "ans", "role": "tool", "toolCallId": "c1", "content": "Approve"},
        ],
        "tools": [ASK_USER_TOOL],
        "context": [],
        "forwardedProps": {},
    }
    TestClient(app).post("/api/agui", json=body)
    [tool_msg] = [c.args[0] for c in cosmos.upsert_message.await_args_list]
    assert tool_msg.role.value == "tool"
    assert tool_msg.metadata == {"agui": {"toolCallId": "c1"}}


def test_relay_rejects_invalid_input():
    app, _ = _relay_app([], AsyncMock())
    assert TestClient(app).post("/api/agui", json={"nope": 1}).status_code == 422


# ─── BYOK override ───


def test_byok_override_applies_only_in_local_mode(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:5567/v1")
    local = CopilotAgent(Settings(local_mode=True))
    assert local._build_provider_config()["base_url"] == "http://127.0.0.1:5567/v1"
    cloud = CopilotAgent(Settings(local_mode=False, foundry_endpoint="https://x.example", foundry_model_deployment="m"))
    assert cloud._build_provider_config()["type"] == "azure"


# ─── Agent Manager edits reach new conversations ───


async def test_blob_content_fingerprint_changes_with_blob_etags():
    from app.services.blob_skill_service import BlobSkillService

    def listing(etag):
        async def list_blobs(name_starts_with):
            assert name_starts_with == "use-cases/wealth-management/"
            for name in (
                "use-cases/wealth-management/SYSTEM_PROMPT.md",
                "use-cases/wealth-management/skills/crm/SKILL.md",
            ):
                yield SimpleNamespace(name=name, etag=etag if name.endswith("SYSTEM_PROMPT.md") else "same")

        return list_blobs

    service = BlobSkillService(Settings(local_mode=True))
    service._container_client = SimpleNamespace(list_blobs=listing("v1"))
    before = await service.content_fingerprint("wealth-management")
    assert before == await service.content_fingerprint("wealth-management")
    service._container_client = SimpleNamespace(list_blobs=listing("v2"))
    assert await service.content_fingerprint("wealth-management") != before

    service._container_client = None
    assert await service.content_fingerprint("wealth-management") == ""
