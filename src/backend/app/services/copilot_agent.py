"""Copilot SDK agent service.

Replaces agent_loop.py. Uses CopilotClient to manage sessions per conversation,
and translates SDK events to the existing SSE event schema.
Uses DefaultAzureCredential for keyless auth to Microsoft Foundry.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncGenerator
from importlib.metadata import version
from typing import TYPE_CHECKING

from azure.identity.aio import ManagedIdentityCredential, get_bearer_token_provider
from copilot import CopilotClient, PermissionRequestResult

try:
    from azure.identity.aio import AzureCLICredential, ChainedTokenCredential

    _HAS_CLI_CREDENTIAL = True
except ImportError:
    _HAS_CLI_CREDENTIAL = False
import contextlib

from opentelemetry import context as otel_context
from opentelemetry import trace

from app.config import Settings
from app.models import ContentEvent, ErrorEvent, ThoughtEvent, ToolCallEvent, UsageEvent, UserInputRequestEvent
from app.observability import operation_duration_histogram, token_usage_histogram
from app.services.skill_tools import ALL_TOOLS

if TYPE_CHECKING:
    from app.services.cosmos_service import CosmosService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Regex patterns for extracting actual skill name from the generic "skill" tool
_SKILL_OUTPUT_RE = re.compile(r'Skill ["\']([^"\']+ )["\']')
_SKILL_INPUT_NAME_RE = re.compile(r'["\']?name["\']?\s*[:=]\s*["\']([^"\'\.]+)["\']')


def _resolve_skill_display_name(event_data, fallback: str = "skill") -> str:
    """Extract the real skill name (e.g. 'email-draft') from a generic 'skill' tool event."""
    # 1. Try explicit attributes the SDK might set
    for attr in ("skill_name", "skill_id"):
        val = getattr(event_data, attr, None)
        if val and isinstance(val, str):
            return val

    # 2. Try parsing from input (dict, JSON, or repr)
    raw_input = getattr(event_data, "input", None)
    if raw_input is not None:
        # If it's already a dict, look for 'name' key
        if isinstance(raw_input, dict):
            for key in ("name", "skill_name", "skill"):
                if key in raw_input and raw_input[key]:
                    return str(raw_input[key])
        input_str = str(raw_input)
        # Try JSON
        try:
            parsed = json.loads(input_str)
            if isinstance(parsed, dict):
                for key in ("name", "skill_name", "skill"):
                    if key in parsed and parsed[key]:
                        return str(parsed[key])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        # Try key=value patterns in repr strings
        m = _SKILL_INPUT_NAME_RE.search(input_str)
        if m:
            return m.group(1).strip()

    # 3. Try parsing from output (e.g. 'Skill "email-draft" loaded successfully')
    raw_output = getattr(event_data, "output", None) or getattr(event_data, "result", None)
    if raw_output:
        m = _SKILL_OUTPUT_RE.search(str(raw_output))
        if m:
            return m.group(1).strip()

    return fallback


def pretty_tool_name(name: str) -> str:
    """Convert tool_name to 'Tool Name' for display."""
    return " ".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def _extract_tool_value(obj) -> str:
    """Extract a human-readable string from an SDK tool input/output object.

    The SDK returns Result/dict/str objects whose __repr__ is ugly
    (e.g. Result(content='{"text": …}', contents=None, …)).
    This helper pulls out the actual content and formats it.
    """
    if obj is None:
        return ""

    # If the object has a .content attribute (SDK Result), use that
    content = getattr(obj, "content", None)
    if content is not None:
        text = str(content)
    elif isinstance(obj, dict):
        try:
            text = json.dumps(obj, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(obj)
    else:
        text = str(obj)

    # Try to pretty-print if it looks like JSON
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
            # For objects with a single "text" key, just return the text
            if isinstance(parsed, dict) and len(parsed) == 1 and "text" in parsed:
                return parsed["text"]
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return text


SYSTEM_PROMPT = """You are Kratos, an enterprise AI assistant.

You MUST use your available skills (tools) whenever they are relevant to the user's request.
Do NOT answer from memory or improvise when a skill can provide accurate, grounded results.
Skills are always preferred over generating answers without tool support.
Search before guessing. Compute, don't estimate. Draft with the skill.
When in doubt, use a skill — it is always better to call a tool than to guess.
Cite tool outputs in your final response.
When producing files, write them to /tmp and reference the path so the user can download them.
If a required Python library is not installed, install it first with pip before running your code.
"""

DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT

# Default use-case when none is specified
DEFAULT_USE_CASE = "generic"


class CopilotAgent:
    """Manages one CopilotClient shared across the app lifetime.

    Each conversation gets its own SDK session, preserving multi-turn history
    automatically without manually loading from Cosmos DB on every turn.
    Uses DefaultAzureCredential for keyless auth to Microsoft Foundry.
    Supports multiple use-cases, each with their own skills and system prompt.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: CopilotClient | None = None
        self._registries: dict[str, object] = {}  # use_case -> SkillRegistry
        self._cosmos_service: CosmosService | None = None
        self._sessions: dict[str, object] = {}
        self._conversation_use_cases: dict[str, str] = {}  # conv_id -> use_case
        self._system_prompt: str = DEFAULT_SYSTEM_PROMPT
        # Futures for resolving user input requests from the SDK
        self._user_input_futures: dict[str, asyncio.Future] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._tool_counters: dict[str, int] = {}
        self._registered_handlers: set[str] = set()
        self._credential: ManagedIdentityCredential | None = None
        self._token_provider = None
        self._usage: dict[str, dict] = {}
        self._first_token_time: dict[str, float] = {}
        self._model_response_start: dict[str, float] = {}
        self._response_parts: dict[str, list[str]] = {}

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value
        # Clear sessions so new chats pick up the updated prompt.
        # Sessions are not explicitly disconnected here (async not possible in a property setter);
        # use update_system_prompt() in async contexts for a full disconnect + Cosmos cleanup.
        self._sessions.clear()
        # Must also clear registered handlers — without this, new sessions created after the
        # reset would skip session.on(on_event) registration (the handler guard checks this set),
        # causing the event queue to never receive events and every request to time out.
        self._registered_handlers.clear()
        self._queues.clear()
        logger.info("System prompt updated — all sessions reset")

    def set_registries(self, registries: dict[str, object]) -> None:
        """Inject the use-case skill registries."""
        self._registries = registries
        self._queues: dict[str, asyncio.Queue] = {}
        self._tool_counters: dict[str, int] = {}
        self._registered_handlers: set[str] = set()
        self._credential: ManagedIdentityCredential | None = None
        self._token_provider = None
        self._usage: dict[str, dict] = {}
        self._first_token_time: dict[str, float] = {}
        self._model_response_start: dict[str, float] = {}

    def set_skill_registry(self, registry: object) -> None:
        """Inject a single skill registry (backward compat — uses 'generic')."""
        self._registries = {DEFAULT_USE_CASE: registry}
        self._queues: dict[str, asyncio.Queue] = {}
        self._tool_counters: dict[str, int] = {}
        self._registered_handlers: set[str] = set()
        self._credential: ManagedIdentityCredential | None = None
        self._token_provider = None
        self._usage: dict[str, dict] = {}
        self._first_token_time: dict[str, float] = {}
        self._model_response_start: dict[str, float] = {}

    def set_conversation_use_case(self, conversation_id: str, use_case: str) -> None:
        """Associate a conversation with a use-case."""
        self._conversation_use_cases[conversation_id] = use_case

    def _get_registry(self, conversation_id: str) -> object | None:
        """Get the SkillRegistry for a conversation's use-case."""
        use_case = self._conversation_use_cases.get(conversation_id, DEFAULT_USE_CASE)
        return self._registries.get(use_case)

    def get_enabled_skill_names(self, conversation_id: str) -> list[str] | None:
        """Return the enabled skill/tool names for a conversation's use-case, or None."""
        registry = self._get_registry(conversation_id)
        if registry is not None and hasattr(registry, "get_enabled_tool_names"):
            return registry.get_enabled_tool_names()
        return None

    def _resolve_skill_source(self, conversation_id: str, tool_name: str) -> str:
        """Best-effort lookup of ``Skill.source`` for a given tool/skill name.

        Returns an empty string when the registry is unavailable or no matching
        skill is found (e.g. builtin tools that predate the registry).
        """
        registry = self._get_registry(conversation_id)
        if registry is None:
            return ""
        skills = getattr(registry, "skills", None) or {}
        for skill in skills.values():
            if getattr(skill, "tool_name", None) == tool_name or getattr(skill, "name", None) == tool_name:
                return getattr(skill, "source", "") or ""
        return ""

    def _get_system_prompt(self, conversation_id: str) -> str:
        """Get the system prompt for a conversation's use-case."""
        registry = self._get_registry(conversation_id)
        if registry is not None and hasattr(registry, "system_prompt") and registry.system_prompt:
            # Parse out just the body (skip YAML frontmatter)
            prompt = registry.system_prompt
            m = re.match(r"^---\s*\n.*?\n---\s*\n?", prompt, re.DOTALL)
            if m:
                prompt = prompt[m.end() :].strip()
            return prompt
        return self._system_prompt

    def set_cosmos_service(self, cosmos_service: "CosmosService") -> None:
        """Inject the Cosmos service for session persistence."""
        self._cosmos_service = cosmos_service

    async def update_system_prompt(self, value: str) -> None:
        """Update the system prompt, disconnect all active sessions, and purge Cosmos mappings.

        Prefer this over the property setter in async contexts (e.g. admin API handlers) so
        that existing SDK sessions are properly disconnected and stale Cosmos session mappings
        are removed, preventing resume attempts for sessions that used the old prompt.
        """
        for session in self._sessions.values():
            with contextlib.suppress(Exception):
                await session.disconnect()
        self._system_prompt = value
        self._sessions.clear()
        self._registered_handlers.clear()
        self._queues.clear()
        if self._cosmos_service:
            await self._cosmos_service.delete_all_session_mappings()
        logger.info("System prompt updated (async) — all sessions disconnected and Cosmos mappings purged")

    async def reset_sessions_for_use_case(self, use_case: str) -> None:
        """Disconnect and drop all sessions belonging to a specific use-case.

        Called after MCP config changes so the next request rebuilds with the new config.
        """
        conv_ids = [cid for cid, uc in self._conversation_use_cases.items() if uc == use_case]
        for cid in conv_ids:
            session = self._sessions.pop(cid, None)
            if session:
                with contextlib.suppress(Exception):
                    await session.disconnect()
            self._registered_handlers.discard(cid)
            self._queues.pop(cid, None)
            if self._cosmos_service:
                await self._cosmos_service.delete_session_mapping(cid)
        logger.info("Reset %d sessions for use-case '%s'", len(conv_ids), use_case)

    async def start(self) -> None:
        """Initialize the Copilot CLI client. Called once on app startup.

        In cloud mode, uses ManagedIdentityCredential (prod) with AzureCLICredential
        fallback (dev) instead of DefaultAzureCredential, which probes many credential
        sources sequentially and adds significant latency on each token acquisition.

        In local mode (``settings.is_local_mode``), skips Azure credential setup and
        relies on the Copilot SDK's default GitHub-hosted model. A ``GITHUB_TOKEN``
        environment variable is exported from ``settings.copilot_github_token`` when
        set (and not already present in the environment) so the SDK can authenticate.
        """
        local_mode = self.settings.is_local_mode

        if local_mode:
            if self.settings.copilot_github_token and not os.environ.get("GITHUB_TOKEN"):
                os.environ["GITHUB_TOKEN"] = self.settings.copilot_github_token
        else:
            if _HAS_CLI_CREDENTIAL:
                self._credential = ChainedTokenCredential(
                    ManagedIdentityCredential(),
                    AzureCLICredential(),
                )
            else:
                self._credential = ManagedIdentityCredential()
            scope = "https://cognitiveservices.azure.com/.default"
            self._token_provider = get_bearer_token_provider(self._credential, scope)

            # Pre-warm: acquire the first token now so user requests don't pay the cost
            try:
                t0 = time.monotonic()
                await self._credential.get_token(scope)
                logger.info("Token pre-warmed successfully in %.1fms", (time.monotonic() - t0) * 1000)
            except Exception:
                logger.warning("Token pre-warm failed — first request will be slower", exc_info=True)

        self._client = CopilotClient()
        await self._client.start()

        # Emit a create_agent span so Foundry Traces tab can discover this agent.
        # Foundry looks for plural gen_ai.agents.id / gen_ai.agents.name;
        # OTel spec uses singular gen_ai.agent.id — emit both.
        span_attrs: dict = {
            "gen_ai.operation.name": "create_agent",
            "gen_ai.request.model": self.settings.foundry_model_deployment,
            "gen_ai.agent.id": "kratos-agent",
            "gen_ai.agent.name": "kratos-agent",
            "gen_ai.agents.id": "kratos-agent",
            "gen_ai.agents.name": "kratos-agent",
            "gen_ai.agent.version": "0.1.0",
        }
        if local_mode:
            span_attrs["gen_ai.system"] = "github"
            span_attrs["gen_ai.provider.name"] = "github"
            span_attrs["server.address"] = "api.githubcopilot.com"
        else:
            span_attrs["gen_ai.system"] = "openai"
            span_attrs["gen_ai.provider.name"] = "azure.ai.openai"
            span_attrs["server.address"] = self.settings.foundry_endpoint
        with tracer.start_as_current_span(
            "create_agent kratos-agent",
            kind=trace.SpanKind.CLIENT,
            attributes=span_attrs,
        ):
            pass

        if local_mode:
            logger.info(
                "CopilotClient started (local mode — GitHub token auth, sdk_version=%s)",
                version("github-copilot-sdk"),
            )
        else:
            logger.info(
                "CopilotClient started (Managed Identity auth, sdk_version=%s)",
                version("github-copilot-sdk"),
            )

    async def stop(self) -> None:
        """Shutdown all sessions and the CLI client. Called on app shutdown."""
        for session in self._sessions.values():
            with contextlib.suppress(Exception):
                await session.disconnect()
        self._sessions.clear()
        self._registered_handlers.clear()
        self._queues.clear()
        self._tool_counters.clear()
        self._user_input_futures.clear()
        if self._client:
            await self._client.stop()
        if self._credential:
            await self._credential.close()
        logger.info("CopilotClient stopped")

    async def update_config(
        self,
        foundry_endpoint: str,
        foundry_model_deployment: str,
    ) -> None:
        """Update config and drop all sessions so they recreate with new settings."""
        if foundry_endpoint:
            self.settings.foundry_endpoint = foundry_endpoint
        if foundry_model_deployment:
            self.settings.foundry_model_deployment = foundry_model_deployment

        # Drop all existing sessions so they get recreated with the new config
        for session in self._sessions.values():
            with contextlib.suppress(Exception):
                await session.disconnect()
        self._sessions.clear()
        self._registered_handlers.clear()
        self._queues.clear()
        self._tool_counters.clear()
        self._user_input_futures.clear()
        # Purge stale Cosmos session mappings so the next request doesn't attempt (and fail)
        # to resume disconnected sessions, which would log spurious warnings.
        if self._cosmos_service:
            await self._cosmos_service.delete_all_session_mappings()
        logger.info("Config updated — all sessions reset")

    def _build_provider_config(self) -> dict | None:
        """Return the Azure provider dict for cloud mode, or ``None`` in local mode.

        In local mode the Copilot SDK falls back to its default GitHub-hosted model
        and authenticates via the ``GITHUB_TOKEN`` / ``COPILOT_GITHUB_TOKEN`` env var.

        Returns:
            A provider configuration dict suitable for ``CopilotClient`` sessions
            when running against Azure OpenAI, or ``None`` when running in local
            (GitHub-hosted) mode.
        """
        if self.settings.is_local_mode:
            return None
        return {
            "type": "azure",
            "base_url": f"{self.settings.foundry_endpoint.rstrip('/')}/openai/deployments/{self.settings.foundry_model_deployment}",  # noqa: E501
            "token_provider": self._token_provider,
            "wire_api": "completions",
            "azure": {
                "api_version": "2024-10-21",
            },
        }

    def _build_session_config(
        self, enabled_tools: list, skill_dirs: list, system_prompt: str, mcp_servers: dict | None = None
    ) -> dict:
        """Build the shared session config dict used for both create and resume."""
        config = {
            "model": self.settings.foundry_model_deployment,
            "streaming": True,
            "tools": enabled_tools,
            "skill_directories": skill_dirs,
            "system_message": {
                "mode": "replace",
                "content": system_prompt,
            },
            "on_permission_request": lambda req, ctx: PermissionRequestResult(kind="approved"),
            "on_user_input_request": self._handle_user_input_request,
        }
        provider = self._build_provider_config()
        if provider is not None:
            config["provider"] = provider
        if mcp_servers:
            config["mcp_servers"] = mcp_servers
        return config

    async def _handle_user_input_request(self, request: dict, context: dict) -> dict:
        """Called by the SDK when the agent uses ask_user. Pushes an event to the SSE
        queue and awaits the user's response via an asyncio.Future."""
        conversation_id = context.get("session_id", "")
        # Find the matching conversation ID from our session map
        for cid, session in self._sessions.items():
            if hasattr(session, "session_id") and session.session_id == conversation_id:
                conversation_id = cid
                break

        request_id = str(uuid.uuid4())
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._user_input_futures[request_id] = future

        # Push the request event to the SSE queue
        q = self._queues.get(conversation_id)
        if q:
            q.put_nowait(
                UserInputRequestEvent(
                    requestId=request_id,
                    question=request.get("question", ""),
                    choices=request.get("choices", []),
                    allowFreeform=request.get("allowFreeform", True),
                )
            )

        # Wait for the user to respond (timeout 5 minutes)
        try:
            answer = await asyncio.wait_for(future, timeout=300.0)
        except TimeoutError:
            self._user_input_futures.pop(request_id, None)
            return {"answer": "No response provided", "wasFreeform": True}
        finally:
            self._user_input_futures.pop(request_id, None)

        return {"answer": answer, "wasFreeform": True}

    def resolve_user_input(self, request_id: str, answer: str) -> bool:
        """Resolve a pending user input request. Returns True if found."""
        future = self._user_input_futures.get(request_id)
        if future and not future.done():
            future.set_result(answer)
            return True
        return False

    def get_sdk_session_id(self, conversation_id: str) -> str | None:
        """Return the SDK session ID for a conversation, if one is cached."""
        session = self._sessions.get(conversation_id)
        return getattr(session, "session_id", None) if session else None

    async def _get_or_create_session(self, conversation_id: str, sdk_session_id: str | None = None) -> object:
        """Return an existing session or create/resume one for this conversation."""
        if conversation_id in self._sessions:
            logger.info("Reusing SDK session for conversation=%s", conversation_id)
            return self._sessions[conversation_id]

        # Resolve enabled tools and skill directories from the use-case registry
        registry = self._get_registry(conversation_id)
        enabled_tools = ALL_TOOLS
        skill_dirs = []
        mcp_servers: dict = {}
        if registry is not None:
            enabled_names = registry.get_enabled_tool_names()
            enabled_tools = [t for t in ALL_TOOLS if t.name in enabled_names]
            skill_dirs = registry.get_skill_directories()
            mcp_servers = getattr(registry, "mcp_servers", {})

        logger.info(
            "Session config for conversation=%s: mcp_servers=%s skill_dirs=%d tools=%d",
            conversation_id,
            list(mcp_servers.keys()) if mcp_servers else "none",
            len(skill_dirs),
            len(enabled_tools),
        )

        system_prompt = self._get_system_prompt(conversation_id)
        config = self._build_session_config(enabled_tools, skill_dirs, system_prompt, mcp_servers)

        # Try to resume an existing SDK session — prefer explicitly passed ID,
        # then fall back to Cosmos DB lookup.
        if sdk_session_id is None and self._cosmos_service:
            sdk_session_id = await self._cosmos_service.get_session_mapping(conversation_id)

        t0 = time.monotonic()
        session = None

        if sdk_session_id:
            try:
                session = await self._client.resume_session(sdk_session_id, config)
                elapsed_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "Resumed SDK session=%s for conversation=%s elapsed=%.0fms",
                    sdk_session_id,
                    conversation_id,
                    elapsed_ms,
                )
            except Exception:
                logger.warning(
                    "Failed to resume SDK session=%s for conversation=%s — creating new",
                    sdk_session_id,
                    conversation_id,
                    exc_info=True,
                )
                session = None

        if session is None:
            t0 = time.monotonic()
            session = await self._client.create_session(config)
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Persist the new SDK session ID to Cosmos DB
            if self._cosmos_service and hasattr(session, "session_id"):
                await self._cosmos_service.upsert_session_mapping(conversation_id, session.session_id)

            logger.info(
                "Created SDK session=%s for conversation=%s model=%s custom_tools=%s elapsed=%.0fms",
                getattr(session, "session_id", "?"),
                conversation_id,
                self.settings.foundry_model_deployment,
                ",".join(tool.name for tool in enabled_tools),
                elapsed_ms,
            )
        self._sessions[conversation_id] = session
        return session

    async def run(
        self,
        message: str,
        conversation_id: str,
        attachments: list[dict] | None = None,
        sdk_session_id: str | None = None,
    ) -> AsyncGenerator[ThoughtEvent | ToolCallEvent | ContentEvent | ErrorEvent | UserInputRequestEvent, None]:
        """Send a message and stream SDK events as typed SSE events."""

        _content_recording = (
            os.environ.get("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "").lower() == "true"
            or os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "").lower() == "true"
        )

        _local_mode = self.settings.is_local_mode
        _invoke_span_attrs: dict = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.system": "github" if _local_mode else "openai",
            "gen_ai.provider.name": "github" if _local_mode else "azure.ai.openai",
            "gen_ai.request.model": self.settings.foundry_model_deployment,
            "gen_ai.agent.id": "kratos-agent",
            "gen_ai.agent.name": "kratos-agent",
            "gen_ai.agents.id": "kratos-agent",
            "gen_ai.agents.name": "kratos-agent",
            "gen_ai.agent.version": "0.1.0",
            "gen_ai.conversation.id": conversation_id,
            "server.address": "api.githubcopilot.com" if _local_mode else self.settings.foundry_endpoint,
        }
        with tracer.start_as_current_span(
            "invoke_agent kratos-agent",
            attributes=_invoke_span_attrs,
        ) as span:
            queue: asyncio.Queue = asyncio.Queue()
            self._queues[conversation_id] = queue
            self._tool_counters[conversation_id] = 0
            self._usage[conversation_id] = {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0}
            self._first_token_time.pop(conversation_id, None)
            self._model_response_start.pop(conversation_id, None)
            self._response_parts[conversation_id] = []  # reset for this turn

            try:
                session = await self._get_or_create_session(conversation_id, sdk_session_id=sdk_session_id)
                logger.info("Sending prompt for conversation=%s message=%r", conversation_id, message)
                self._send_time = time.monotonic()

                # Capture the current span context so the sync on_event callback
                # can create child spans nested under this copilot_agent.run span.
                # Use set_span_in_context to explicitly attach the span to a context object.
                # (otel_context.get_current() is unreliable across async boundaries.)
                if not hasattr(self, "_span_contexts"):
                    self._span_contexts: dict[str, otel_context.Context] = {}
                self._span_contexts[conversation_id] = trace.set_span_in_context(span)

                # Register the event handler ONCE per session, not per run() call.
                # The handler routes events to whatever queue is active for that conversation.
                if conversation_id not in self._registered_handlers:
                    cid = conversation_id  # capture for closure

                    _pending_tools: list[str] = []  # track started tools in order for matching
                    _tool_spans: dict[str, trace.Span] = {}  # active tool span per tool name
                    _tool_span_stack: list[tuple[str, trace.Span]] = []  # ordered stack for matching

                    def on_event(event) -> None:
                        """Translate SDK events into our SSE event types."""
                        q = self._queues.get(cid)
                        if q is None:
                            return  # no active run for this conversation
                        try:
                            etype = event.type.value if hasattr(event.type, "value") else str(event.type)

                            # Log time-to-first-event from send
                            if hasattr(self, "_send_time"):
                                ttfe = (time.monotonic() - self._send_time) * 1000
                                logger.info("Event received type=%s ttfe=%.0fms conversation=%s", etype, ttfe, cid)

                            if etype in ("assistant.message_delta", "assistant.streaming_delta"):
                                # Track time-to-first-token
                                if cid not in self._first_token_time and hasattr(self, "_send_time"):
                                    self._first_token_time[cid] = (time.monotonic() - self._send_time) * 1000
                                # Try multiple fields — SDK versions use different attribute names
                                delta = (
                                    getattr(event.data, "delta_content", None)
                                    or getattr(event.data, "content", None)
                                    or getattr(event.data, "text", None)
                                    or getattr(event.data, "delta", None)
                                    or ""
                                )
                                if delta:
                                    self._response_parts.setdefault(cid, []).append(delta)
                                    q.put_nowait(ContentEvent(content=delta))

                            elif etype == "assistant.turn_start":
                                # Model started processing — mark for latency calc
                                self._model_response_start[cid] = time.monotonic()

                            elif etype == "assistant.message":
                                # End-of-turn complete message — capture content as fallback
                                # if streaming deltas didn't carry text
                                msg_content = getattr(event.data, "content", None) or ""
                                if msg_content and not self._response_parts.get(cid):
                                    self._response_parts.setdefault(cid, []).append(msg_content)

                            elif etype in ("assistant.usage", "session.usage_info"):
                                # Capture token usage from the model
                                data = event.data
                                prompt_t = int(
                                    getattr(data, "prompt_tokens", 0) or getattr(data, "input_tokens", 0) or 0
                                )
                                completion_t = int(
                                    getattr(data, "completion_tokens", 0) or getattr(data, "output_tokens", 0) or 0
                                )
                                total_t = int(getattr(data, "total_tokens", 0) or 0) or (prompt_t + completion_t)

                                # Extract reasoning tokens from completion_tokens_details
                                reasoning_t = 0
                                details = getattr(data, "completion_tokens_details", None)
                                if details:
                                    reasoning_t = int(getattr(details, "reasoning_tokens", 0) or 0)
                                if not reasoning_t:
                                    reasoning_t = int(getattr(data, "reasoning_tokens", 0) or 0)

                                usage = self._usage.get(cid, {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0})
                                usage["prompt"] += prompt_t
                                usage["completion"] += completion_t
                                usage["reasoning"] += reasoning_t
                                usage["total"] += total_t
                                self._usage[cid] = usage
                                logger.info(
                                    "Usage conversation=%s prompt_tokens=%d completion_tokens=%d reasoning_tokens=%d total=%d",  # noqa: E501
                                    cid,
                                    prompt_t,
                                    completion_t,
                                    reasoning_t,
                                    total_t,
                                )
                                if total_t > 0:
                                    q.put_nowait(
                                        UsageEvent(
                                            promptTokens=usage["prompt"],
                                            completionTokens=usage["completion"],
                                            reasoningTokens=usage["reasoning"],
                                            totalTokens=usage["total"],
                                        )
                                    )

                            elif etype == "tool.execution_start":
                                tool_name = (
                                    getattr(event.data, "tool_name", None)
                                    or getattr(event.data, "name", None)
                                    or "unknown"
                                )
                                # Resolve actual skill name for the generic "skill" meta-tool
                                if tool_name == "skill":
                                    tool_name = _resolve_skill_display_name(event.data, fallback="skill")
                                    logger.info(
                                        "Resolved skill display name: %s (attrs=%s)",
                                        tool_name,
                                        {
                                            a: repr(getattr(event.data, a, None))
                                            for a in dir(event.data)
                                            if not a.startswith("_")
                                        },
                                    )
                                self._tool_counters[cid] = self._tool_counters.get(cid, 0) + 1
                                _pending_tools.append(tool_name)
                                logger.info(
                                    "Tool start conversation=%s tool=%s pending=%s", cid, tool_name, _pending_tools
                                )

                                # Create a child span nested under the invoke_agent span
                                raw_input_str = str(getattr(event.data, "input", "") or "")
                                tool_call_id = (
                                    getattr(event.data, "call_id", None)
                                    or getattr(event.data, "id", None)
                                    or str(uuid.uuid4())[:12]
                                )
                                parent_ctx = self._span_contexts.get(cid)
                                tool_span = tracer.start_span(
                                    f"execute_tool {tool_name}",
                                    context=parent_ctx,
                                    attributes={
                                        "gen_ai.system": "openai",
                                        "gen_ai.operation.name": "execute_tool",
                                        "gen_ai.tool.name": tool_name,
                                        "gen_ai.tool.call.id": str(tool_call_id),
                                        "gen_ai.tool.type": "function",
                                        "gen_ai.tool.call.arguments": raw_input_str[:2000],
                                    },
                                )
                                _tool_spans[tool_name] = tool_span
                                _tool_span_stack.append((tool_name, tool_span))
                                # Emit descriptive thought (not just "Calling tool: X")
                                display = pretty_tool_name(tool_name)
                                raw_input = getattr(event.data, "input", None)
                                detail = ""
                                if raw_input:
                                    input_str = str(raw_input)
                                    # Try to extract a query or key param for context
                                    for key in ("query", "code", "prompt", "message", "text"):
                                        import re as _re

                                        m = _re.search(rf'["\']?{key}["\']?\s*[:=]\s*["\']([^"\']+)["\']', input_str)
                                        if m:
                                            snippet = m.group(1)[:80]
                                            detail = f": {snippet}{'…' if len(m.group(1)) > 80 else ''}"
                                            break
                                q.put_nowait(
                                    ThoughtEvent(
                                        content=f"{display}{detail}",
                                        iteration=0,
                                    )
                                )
                                q.put_nowait(
                                    ToolCallEvent(
                                        skillName=tool_name,
                                        status="started",
                                        input=_extract_tool_value(getattr(event.data, "input", "")),
                                        source=self._resolve_skill_source(cid, tool_name),
                                    )
                                )

                            elif etype == "tool.execution_complete":
                                # SDK often doesn't include tool_name on complete events,
                                # so match back to the oldest pending started tool.
                                raw_name = getattr(event.data, "tool_name", None) or getattr(event.data, "name", None)
                                if raw_name:
                                    tool_name = raw_name
                                    # Resolve generic "skill" to actual name
                                    if tool_name == "skill":
                                        tool_name = _resolve_skill_display_name(event.data, fallback="skill")
                                    # Remove from pending if present
                                    if tool_name in _pending_tools:
                                        _pending_tools.remove(tool_name)
                                    elif "skill" in _pending_tools:
                                        # Fallback: remove unresolved "skill" entry
                                        _pending_tools.remove("skill")
                                elif _pending_tools:
                                    tool_name = _pending_tools.pop(0)
                                else:
                                    tool_name = "unknown"
                                duration_ms = int(
                                    getattr(event.data, "duration_ms", 0) or getattr(event.data, "duration", 0) or 0
                                )
                                success = getattr(event.data, "success", None)
                                error = getattr(event.data, "error", None)
                                logger.info(
                                    "Tool complete conversation=%s tool=%s success=%r duration_ms=%s error=%r",
                                    cid,
                                    tool_name,
                                    success,
                                    duration_ms,
                                    error,
                                )

                                # End the corresponding tool span
                                tool_span = _tool_spans.pop(tool_name, None)
                                if tool_span is None and _tool_span_stack:
                                    # Fallback: end the oldest pending tool span
                                    _, tool_span = _tool_span_stack.pop(0)
                                if tool_span is not None:
                                    # Remove from stack by identity
                                    _tool_span_stack[:] = [(n, s) for n, s in _tool_span_stack if s is not tool_span]
                                    output_str = str(
                                        getattr(event.data, "output", "") or getattr(event.data, "result", "")
                                    )[:2000]
                                    tool_span.set_attribute("gen_ai.tool.call.result", output_str)
                                    if error:
                                        tool_span.set_attribute(
                                            "error.type",
                                            type(error).__name__ if not isinstance(error, str) else "tool_error",
                                        )
                                        tool_span.set_status(trace.StatusCode.ERROR, str(error))
                                    elif success is False:
                                        tool_span.set_attribute("error.type", "tool_execution_failed")
                                        tool_span.set_status(trace.StatusCode.ERROR, "Tool execution failed")
                                    else:
                                        tool_span.set_status(trace.StatusCode.OK)
                                    tool_span.end()
                                q.put_nowait(
                                    ToolCallEvent(
                                        skillName=tool_name,
                                        status="completed" if success is not False else "failed",
                                        output=_extract_tool_value(
                                            getattr(event.data, "output", "") or getattr(event.data, "result", "")
                                        )[:2000],
                                        durationMs=duration_ms,
                                        source=self._resolve_skill_source(cid, tool_name),
                                    )
                                )

                            elif etype == "session.idle":
                                # End any orphaned tool spans
                                for _, orphan_span in _tool_span_stack:
                                    orphan_span.set_status(trace.StatusCode.OK)
                                    orphan_span.end()
                                _tool_span_stack.clear()
                                _tool_spans.clear()

                                tc = self._tool_counters.get(cid, 0)
                                usage = self._usage.get(cid, {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0})
                                ttft = int(self._first_token_time.get(cid, 0))
                                model_start = self._model_response_start.get(cid)
                                model_latency = int((time.monotonic() - model_start) * 1000) if model_start else 0
                                logger.info(
                                    "Session idle conversation=%s tool_events=%s tokens=%s ttft=%dms model_latency=%dms",  # noqa: E501
                                    cid,
                                    tc,
                                    usage,
                                    ttft,
                                    model_latency,
                                )
                                q.put_nowait(None)  # sentinel — stream is done

                            elif etype == "session.error":
                                # End any orphaned tool spans
                                for _, orphan_span in _tool_span_stack:
                                    orphan_span.set_status(trace.StatusCode.ERROR, "Session error")
                                    orphan_span.end()
                                _tool_span_stack.clear()
                                _tool_spans.clear()

                                logger.error(
                                    "Session error conversation=%s message=%s",
                                    cid,
                                    str(getattr(event.data, "message", "Unknown error")),
                                )
                                q.put_nowait(
                                    ErrorEvent(
                                        message=str(getattr(event.data, "message", "Unknown error")),
                                        code="SDK_ERROR",
                                    )
                                )
                                q.put_nowait(None)

                            else:
                                # Log unhandled events so we can discover new event types
                                logger.info(
                                    "Unhandled SDK event type=%s conversation=%s data_attrs=%s",
                                    etype,
                                    cid,
                                    {
                                        a: repr(getattr(event.data, a, None))[:100]
                                        for a in dir(event.data)
                                        if not a.startswith("_")
                                    }
                                    if event.data
                                    else "no_data",
                                )
                        except Exception:
                            logger.exception("Error in session event handler conversation=%s", cid)

                    session.on(on_event)
                    self._registered_handlers.add(conversation_id)

                send_opts: dict = {"prompt": message}
                if attachments:
                    send_opts["attachments"] = attachments
                await session.send(send_opts)

                # Drain the queue until sentinel
                while True:
                    item = await asyncio.wait_for(queue.get(), timeout=120.0)
                    if item is None:
                        break
                    yield item

                tool_events = self._tool_counters.get(conversation_id, 0)
                # Enrich the span with usage and tool call counts
                usage = self._usage.get(conversation_id, {})
                span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt", 0))
                span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion", 0))
                span.set_attribute("gen_ai.agent.tool_calls", tool_events)

                # Reasoning tokens (non-standard but useful for o-series / GPT-5)
                reasoning_t = usage.get("reasoning", 0)
                if reasoning_t:
                    span.set_attribute("gen_ai.usage.reasoning_tokens", reasoning_t)

                # Time-to-first-token as span attribute
                ttft = self._first_token_time.get(conversation_id)
                if ttft:
                    span.set_attribute("gen_ai.client.time_to_first_token_ms", int(ttft))

                # Input/output/system content (opt-in, respects content recording env var)
                if _content_recording:
                    system_prompt = self._get_system_prompt(conversation_id)
                    span.set_attribute(
                        "gen_ai.system_instructions",
                        json.dumps([{"type": "text", "content": system_prompt[:4000]}]),
                    )
                    span.set_attribute(
                        "gen_ai.input.messages",
                        json.dumps([{"role": "user", "parts": [{"type": "text", "content": message[:4000]}]}]),
                    )
                    full_response = "".join(self._response_parts.get(conversation_id, []))
                    span.set_attribute(
                        "gen_ai.output.messages",
                        json.dumps(
                            [
                                {
                                    "role": "assistant",
                                    "parts": [{"type": "text", "content": full_response[:4000]}],
                                    "finish_reason": "stop",
                                }
                            ]
                        ),
                    )
                if tool_events == 0:
                    logger.warning(
                        "No tool events observed for conversation=%s prompt=%r",
                        conversation_id,
                        message,
                    )

                # Record GenAI metrics (token usage + operation duration)
                _metric_attrs = {
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.provider.name": "github" if _local_mode else "azure.ai.openai",
                    "gen_ai.request.model": self.settings.foundry_model_deployment,
                    "server.address": "api.githubcopilot.com" if _local_mode else self.settings.foundry_endpoint,
                }
                if usage.get("prompt", 0):
                    token_usage_histogram.record(usage["prompt"], {**_metric_attrs, "gen_ai.token.type": "input"})
                if usage.get("completion", 0):
                    token_usage_histogram.record(usage["completion"], {**_metric_attrs, "gen_ai.token.type": "output"})
                elapsed_s = time.monotonic() - self._send_time
                operation_duration_histogram.record(elapsed_s, _metric_attrs)

            except TimeoutError:
                span.set_attribute("error.type", "timeout")
                span.set_status(trace.StatusCode.ERROR, "Agent timed out")
                logger.warning("Agent timed out for conversation=%s", conversation_id)
                yield ErrorEvent(message="Agent timed out waiting for response", code="TIMEOUT")
            except Exception as e:
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(trace.StatusCode.ERROR, str(e))
                logger.exception("CopilotAgent failed for conversation=%s", conversation_id)
                yield ErrorEvent(message=str(e), code="AGENT_ERROR")
                # Drop the broken session so next turn gets a fresh one
                self._sessions.pop(conversation_id, None)
                self._registered_handlers.discard(conversation_id)
                if self._cosmos_service:
                    await self._cosmos_service.delete_session_mapping(conversation_id)
            finally:
                self._queues.pop(conversation_id, None)

    def get_run_stats(self, conversation_id: str) -> dict:
        """Return accumulated stats for the last run of a conversation."""
        usage = self._usage.get(conversation_id, {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0})
        ttft = int(self._first_token_time.get(conversation_id, 0))
        model_start = self._model_response_start.get(conversation_id)
        model_latency = int((time.monotonic() - model_start) * 1000) if model_start else 0
        return {
            "prompt_tokens": usage["prompt"],
            "completion_tokens": usage["completion"],
            "reasoning_tokens": usage.get("reasoning", 0),
            "total_tokens": usage["total"],
            "time_to_first_token_ms": ttft,
            "model_latency_ms": model_latency,
        }
