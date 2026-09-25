"""Tests for the Copilot SDK agent service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models import ContentEvent, ErrorEvent, ThoughtEvent, ToolCallEvent
from app.services.copilot_agent import CopilotAgent, _reasoning_tokens


@pytest.fixture
def settings():
    return Settings(
        foundry_endpoint="https://test.services.ai.azure.com",
        foundry_model_deployment="gpt-52",
    )


@pytest.fixture
def copilot_agent(settings):
    return CopilotAgent(settings)


def test_copilot_agent_init(copilot_agent, settings):
    """Test CopilotAgent initializes with correct settings."""
    assert copilot_agent.settings is settings
    assert copilot_agent._client is None
    assert copilot_agent._sessions == {}


@pytest.mark.asyncio
async def test_copilot_agent_start_stop(settings):
    """Test CopilotClient start and stop lifecycle."""
    # Force cloud mode so the Azure credential is actually created and closed;
    # in local mode start()/stop() intentionally skip the credential entirely.
    cloud_agent = CopilotAgent(settings.model_copy(update={"local_mode": False}))
    mock_client = AsyncMock()
    mock_credential = AsyncMock()
    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=mock_credential),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await cloud_agent.start()

        assert cloud_agent._client is mock_client
        mock_client.start.assert_awaited_once()

        await cloud_agent.stop()
        mock_client.stop.assert_awaited_once()
        mock_credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_copilot_agent_run_streams_content(copilot_agent):
    """Test that run() yields ContentEvent from SDK assistant.message.delta events."""
    mock_session = AsyncMock()
    mock_client = AsyncMock()
    mock_client.create_session = AsyncMock(return_value=mock_session)

    # Simulate SDK events via the on_event callback
    def fake_on(callback):
        # Simulate content delta event
        delta_event = MagicMock()
        delta_event.type.value = "assistant.message_delta"
        delta_event.data.delta_content = "Hello, world!"
        callback(delta_event)

        # Simulate session idle (end of stream)
        idle_event = MagicMock()
        idle_event.type.value = "session.idle"
        callback(idle_event)

    mock_session.on = fake_on
    mock_session.send = AsyncMock()

    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=AsyncMock()),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await copilot_agent.start()

        events = []
        async for event in copilot_agent.run(
            message="Hello",
            conversation_id="test-conv-1",
        ):
            events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], ContentEvent)
    assert events[0].content == "Hello, world!"


@pytest.mark.asyncio
async def test_copilot_agent_run_streams_tool_events(copilot_agent):
    """Test that run() yields ThoughtEvent and ToolCallEvent for tool executions."""
    mock_session = AsyncMock()
    mock_client = AsyncMock()
    mock_client.create_session = AsyncMock(return_value=mock_session)

    def fake_on(callback):
        # Tool start event
        start_event = MagicMock()
        start_event.type.value = "tool.execution_start"
        start_event.data.tool_name = "web_search"
        start_event.data.input = '{"query": "test"}'
        callback(start_event)

        # Tool end event
        end_event = MagicMock()
        end_event.type.value = "tool.execution_complete"
        end_event.data.tool_name = "web_search"
        end_event.data.output = '{"results": []}'
        end_event.data.duration_ms = 150
        end_event.data.success = True
        callback(end_event)

        # Content
        delta_event = MagicMock()
        delta_event.type.value = "assistant.message_delta"
        delta_event.data.delta_content = "Based on the search..."
        callback(delta_event)

        # Done
        idle_event = MagicMock()
        idle_event.type.value = "session.idle"
        callback(idle_event)

    mock_session.on = fake_on
    mock_session.send = AsyncMock()

    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=AsyncMock()),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await copilot_agent.start()

        events = []
        async for event in copilot_agent.run(
            message="Search the web",
            conversation_id="test-conv-2",
        ):
            events.append(event)

    # ThoughtEvent, ToolCallEvent(started), ToolCallEvent(completed), ContentEvent
    assert len(events) == 4
    assert isinstance(events[0], ThoughtEvent)
    assert "Web Search" in events[0].content
    assert isinstance(events[1], ToolCallEvent)
    assert events[1].status == "started"
    assert isinstance(events[2], ToolCallEvent)
    assert events[2].status == "completed"
    assert events[2].durationMs == 150
    assert isinstance(events[3], ContentEvent)


@pytest.mark.asyncio
async def test_copilot_agent_run_handles_error(copilot_agent):
    """Test that run() yields ErrorEvent on SDK error."""
    mock_session = AsyncMock()
    mock_client = AsyncMock()
    mock_client.create_session = AsyncMock(return_value=mock_session)

    def fake_on(callback):
        error_event = MagicMock()
        error_event.type.value = "session.error"
        error_event.data.message = "Model unavailable"
        callback(error_event)

    mock_session.on = fake_on
    mock_session.send = AsyncMock()

    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=AsyncMock()),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await copilot_agent.start()

        events = []
        async for event in copilot_agent.run(
            message="Hello",
            conversation_id="test-conv-3",
        ):
            events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "SDK_ERROR"
    assert "Model unavailable" in events[0].message


@pytest.mark.asyncio
async def test_copilot_agent_session_reuse(copilot_agent):
    """Test that the same conversation reuses the same SDK session."""
    mock_session = AsyncMock()
    mock_client = AsyncMock()
    mock_client.create_session = AsyncMock(return_value=mock_session)

    # The agent registers the event handler ONCE per session, so model a
    # persistent SDK stream: capture the callback on registration and deliver a
    # `session.idle` event on every send() (including the reuse turn).
    captured: dict = {}

    def fake_on(callback):
        captured["callback"] = callback

    async def fake_send(*args, **kwargs):
        idle_event = MagicMock()
        idle_event.type.value = "session.idle"
        captured["callback"](idle_event)

    mock_session.on = fake_on
    mock_session.send = fake_send

    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=AsyncMock()),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await copilot_agent.start()

        # First call creates a session
        async for _ in copilot_agent.run(message="Hello", conversation_id="conv-reuse"):
            pass
        assert mock_client.create_session.await_count == 1

        # Second call reuses the session
        async for _ in copilot_agent.run(message="Follow up", conversation_id="conv-reuse"):
            pass
        assert mock_client.create_session.await_count == 1  # still 1


@pytest.mark.asyncio
async def test_copilot_agent_exception_drops_session(copilot_agent):
    """Test that a failed session is dropped so the next call gets a fresh one."""
    mock_client = AsyncMock()
    mock_client.create_session = AsyncMock(side_effect=Exception("connection failed"))

    with (
        patch("app.services.copilot_agent.CopilotClient", return_value=mock_client),
        patch("app.services.copilot_agent.ManagedIdentityCredential", return_value=AsyncMock()),
        patch("app.services.copilot_agent._HAS_CLI_CREDENTIAL", False),
        patch("app.services.copilot_agent.get_bearer_token_provider", return_value=lambda: "token"),
    ):
        await copilot_agent.start()

        events = []
        async for event in copilot_agent.run(message="Hello", conversation_id="conv-fail"):
            events.append(event)

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert events[0].code == "AGENT_ERROR"
        # Session should be dropped
        assert "conv-fail" not in copilot_agent._sessions


def test_provider_config_uses_responses_wire_api(settings):
    """Reasoning models reject function tools on /chat/completions.

    gpt-6-astra returns 400 "Function tools with reasoning_effort are not
    supported ... use /v1/responses" for ANY tool-bearing request, because the
    deployment applies a non-none reasoning default. Pinning the Responses API
    here is what keeps tool calling and reasoning working together, so guard it.
    """
    agent = CopilotAgent(settings.model_copy(update={"local_mode": False}))
    provider = agent._build_provider_config()

    assert provider is not None
    assert provider["wire_api"] == "responses"
    # Bare resource host: the azure provider appends the API path itself, and
    # omitting azure.api_version selects the versionless /openai/v1/ route.
    assert provider["base_url"] == "https://test.services.ai.azure.com"
    assert "azure" not in provider


def test_provider_config_prefers_gateway_and_strips_trailing_slash(settings):
    """The APIM gateway host wins over the Foundry endpoint when configured."""
    agent = CopilotAgent(
        settings.model_copy(update={"local_mode": False, "llm_gateway_base_url": "https://apim.example.net/"})
    )
    provider = agent._build_provider_config()

    assert provider is not None
    assert provider["base_url"] == "https://apim.example.net"


def test_session_config_carries_reasoning_effort(settings):
    """reasoning_effort is passed through to the SDK session."""
    agent = CopilotAgent(settings.model_copy(update={"reasoning_effort": "medium"}))
    config = agent._build_session_config(enabled_tools=[], skill_dirs=[], system_prompt="be helpful")

    assert config["reasoning_effort"] == "medium"


def test_session_config_omits_empty_reasoning_effort(settings):
    """An empty setting means "inherit the deployment default" — send nothing."""
    agent = CopilotAgent(settings.model_copy(update={"reasoning_effort": ""}))
    config = agent._build_session_config(enabled_tools=[], skill_dirs=[], system_prompt="be helpful")

    assert "reasoning_effort" not in config


class _Usage:
    """Stand-in for an SDK usage payload exposing attributes."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # Responses API nests reasoning under output_tokens_details.
        ({"output_tokens_details": {"reasoning_tokens": 12}}, 12),
        (_Usage(output_tokens_details=_Usage(reasoning_tokens=7)), 7),
        # Chat Completions uses completion_tokens_details.
        (_Usage(completion_tokens_details=_Usage(reasoning_tokens=5)), 5),
        # Flat fallback.
        ({"reasoning_tokens": 3}, 3),
        # Nothing to report.
        ({}, 0),
        ({"output_tokens_details": {"reasoning_tokens": 0}}, 0),
        (_Usage(completion_tokens_details=None, output_tokens_details=None), 0),
    ],
)
def test_reasoning_tokens_handles_both_wire_shapes(payload, expected):
    """Switching to the Responses API moved reasoning tokens to a new field."""
    assert _reasoning_tokens(payload) == expected
