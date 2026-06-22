"""Tests for per-conversation OBO MCP token injection in CopilotAgent.

Covers set_conversation_mcp_tokens + _apply_mcp_tokens — the hook that injects
the signed-in user's bearer into the remote OBO MCP server's transport headers
so the tool runs On-Behalf-Of the user. The token must never mutate the shared
registry config and must only land on the matching server.
"""

import pytest

from app.config import Settings
from app.services.copilot_agent import CopilotAgent


@pytest.fixture
def settings():
    return Settings(
        foundry_endpoint="https://test.services.ai.azure.com",
        foundry_model_deployment="gpt-52",
    )


@pytest.fixture
def agent(settings):
    return CopilotAgent(settings)


def test_inject_header_on_registry_server(agent):
    """A token whose key matches a configured server sets its Authorization header."""
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-abc"})
    registry = {"graph-obo": {"type": "http", "url": "https://obo.example/mcp", "tools": ["*"]}}

    result = agent._apply_mcp_tokens("conv1", registry)

    assert result["graph-obo"]["headers"]["Authorization"] == "Bearer tok-abc"
    # original registry dict is untouched (deep copy)
    assert "headers" not in registry["graph-obo"]


def test_autocreate_obo_server_from_env(agent, monkeypatch):
    """With no registry entry, the known OBO server is created from env config."""
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.setenv("OBO_MCP_SERVER_MCP_URL", "https://obo.example/mcp")
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-xyz"})

    result = agent._apply_mcp_tokens("conv1", {})

    entry = result["graph-obo"]
    assert entry["type"] == "http"
    assert entry["url"] == "https://obo.example/mcp"
    assert entry["headers"]["Authorization"] == "Bearer tok-xyz"


def test_autocreate_skipped_without_url(agent, monkeypatch):
    """No URL configured => the OBO server is not fabricated."""
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.delenv("OBO_MCP_SERVER_MCP_URL", raising=False)
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-xyz"})

    result = agent._apply_mcp_tokens("conv1", {})

    assert "graph-obo" not in result


def test_unknown_server_token_ignored(agent, monkeypatch):
    """A token for a server that is neither configured nor the OBO server is ignored."""
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.setenv("OBO_MCP_SERVER_MCP_URL", "https://obo.example/mcp")
    agent.set_conversation_mcp_tokens("conv1", {"mystery": "tok"})

    result = agent._apply_mcp_tokens("conv1", {})

    assert "mystery" not in result


def test_preconfigured_non_obo_server_token_ignored(agent, monkeypatch):
    """Confused-deputy guard: a token keyed to a *pre-configured* non-OBO server
    is ignored — the user's bearer is never attached to any server other than the
    configured OBO server, even when that server exists in the registry."""
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.setenv("OBO_MCP_SERVER_MCP_URL", "https://obo.example/mcp")
    agent.set_conversation_mcp_tokens("conv1", {"servicenow": "tok-leak"})
    registry = {"servicenow": {"type": "http", "url": "https://servicenow.example/mcp", "tools": ["*"]}}

    result = agent._apply_mcp_tokens("conv1", registry)

    assert "headers" not in result["servicenow"]


def test_obo_url_mismatch_token_not_injected(agent, monkeypatch):
    """A registry server named like the OBO server but pointing at a URL other than
    the trusted OBO URL must not receive the bearer (guards a tampered registry)."""
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.setenv("OBO_MCP_SERVER_MCP_URL", "https://obo.example/mcp")
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-abc"})
    registry = {"graph-obo": {"type": "http", "url": "https://evil.example/mcp", "tools": ["*"]}}

    result = agent._apply_mcp_tokens("conv1", registry)

    assert "headers" not in result["graph-obo"]


def test_no_tokens_is_noop(agent):
    """No registered tokens => servers returned unchanged, no Authorization added."""
    registry = {"graph-obo": {"type": "http", "url": "https://obo.example/mcp"}}

    result = agent._apply_mcp_tokens("conv-none", registry)

    assert "headers" not in result["graph-obo"]


def test_empty_dict_clears_tokens(agent):
    """Passing an empty dict removes previously registered tokens."""
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-abc"})
    agent.set_conversation_mcp_tokens("conv1", {})
    registry = {"graph-obo": {"type": "http", "url": "https://obo.example/mcp"}}

    result = agent._apply_mcp_tokens("conv1", registry)

    assert "headers" not in result["graph-obo"]


def test_empty_token_value_not_injected(agent):
    """A falsy token value must not produce a 'Bearer ' header."""
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": ""})
    registry = {"graph-obo": {"type": "http", "url": "https://obo.example/mcp"}}

    result = agent._apply_mcp_tokens("conv1", registry)

    assert "headers" not in result["graph-obo"]


def test_tokens_isolated_per_conversation(agent):
    """Tokens registered for one conversation never leak into another."""
    agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-1"})
    registry = {"graph-obo": {"type": "http", "url": "https://obo.example/mcp"}}

    other = agent._apply_mcp_tokens("conv2", registry)

    assert "headers" not in other["graph-obo"]


# ---------------------------------------------------------------------------
# Identity fingerprint helpers
# ---------------------------------------------------------------------------


def test_mcp_has_auth_detects_authorization(agent):
    assert agent._mcp_has_auth({"s": {"headers": {"Authorization": "Bearer x"}}}) is True
    assert agent._mcp_has_auth({"s": {"headers": {}}}) is False
    assert agent._mcp_has_auth({"s": {}}) is False
    assert agent._mcp_has_auth({}) is False
    assert agent._mcp_has_auth(None) is False


def test_mcp_fingerprint_changes_with_token(agent):
    a = agent._mcp_fingerprint({"s": {"headers": {"Authorization": "Bearer one"}}})
    b = agent._mcp_fingerprint({"s": {"headers": {"Authorization": "Bearer two"}}})
    assert a and b and a != b
    # No identity header => empty fingerprint
    assert agent._mcp_fingerprint({"s": {"url": "x"}}) == ""
    # Same input is stable and never leaks the raw token
    fp = agent._mcp_fingerprint({"s": {"headers": {"Authorization": "Bearer secret-123"}}})
    assert fp == agent._mcp_fingerprint({"s": {"headers": {"Authorization": "Bearer secret-123"}}})
    assert "secret-123" not in fp


# ---------------------------------------------------------------------------
# Session lifecycle: OBO sessions must force-create (never resume / never persist)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True


class _FakeClient:
    def __init__(self):
        self.created = []
        self.resumed = []
        self._n = 0

    async def create_session(self, **config):
        self._n += 1
        s = _FakeSession(f"sdk-{self._n}")
        self.created.append(config)
        return s

    async def resume_session(self, sdk_session_id, **config):
        self.resumed.append(sdk_session_id)
        return _FakeSession(sdk_session_id)


class _FakeCosmos:
    def __init__(self, mapping=None):
        self._mapping = mapping
        self.upserts = []

    async def get_session_mapping(self, conversation_id):
        return self._mapping

    async def upsert_session_mapping(self, conversation_id, session_id):
        self.upserts.append((conversation_id, session_id))


@pytest.fixture
def wired_agent(agent, monkeypatch):
    monkeypatch.setenv("OBO_MCP_SERVER_NAME", "graph-obo")
    monkeypatch.setenv("OBO_MCP_SERVER_MCP_URL", "https://obo.example/mcp")
    agent._client = _FakeClient()
    return agent


async def test_identity_session_forces_create_never_resumes(wired_agent):
    """An OBO token must produce a fresh create_session and ignore any Cosmos mapping."""
    cosmos = _FakeCosmos(mapping="stale-sdk-id")
    wired_agent._cosmos_service = cosmos
    wired_agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-abc"})

    session = await wired_agent._get_or_create_session("conv1")

    assert wired_agent._client.resumed == []  # never resumed
    assert len(wired_agent._client.created) == 1
    assert session.session_id == "sdk-1"
    # Identity sessions are never persisted to Cosmos
    assert cosmos.upserts == []


async def test_identity_token_change_recreates_session(wired_agent):
    """A changed user token evicts and disconnects the old session, then creates a new one."""
    wired_agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-1"})
    first = await wired_agent._get_or_create_session("conv1")

    wired_agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-2"})
    second = await wired_agent._get_or_create_session("conv1")

    assert first.disconnected is True
    assert first.session_id != second.session_id
    assert len(wired_agent._client.created) == 2


async def test_identity_same_token_reuses_cached_session(wired_agent):
    """An unchanged token reuses the in-memory session (single create)."""
    wired_agent.set_conversation_mcp_tokens("conv1", {"graph-obo": "tok-1"})
    first = await wired_agent._get_or_create_session("conv1")
    second = await wired_agent._get_or_create_session("conv1")

    assert first is second
    assert len(wired_agent._client.created) == 1


async def test_non_identity_resumes_from_cosmos(wired_agent):
    """Without an OBO token, a Cosmos-persisted session id is resumed (history continuity)."""
    cosmos = _FakeCosmos(mapping="persisted-sdk-id")
    wired_agent._cosmos_service = cosmos

    session = await wired_agent._get_or_create_session("conv-plain")

    assert wired_agent._client.resumed == ["persisted-sdk-id"]
    assert session.session_id == "persisted-sdk-id"
    assert wired_agent._client.created == []


async def test_non_identity_creates_and_persists(wired_agent):
    """Without an OBO token and no mapping, a new session is created and persisted."""
    cosmos = _FakeCosmos(mapping=None)
    wired_agent._cosmos_service = cosmos

    session = await wired_agent._get_or_create_session("conv-plain")

    assert wired_agent._client.resumed == []
    assert len(wired_agent._client.created) == 1
    assert cosmos.upserts == [("conv-plain", session.session_id)]
