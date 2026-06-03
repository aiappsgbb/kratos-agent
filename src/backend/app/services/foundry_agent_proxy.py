"""Foundry Hosted Agent proxy — invokes the hosted agent via the Invocations REST API.

Instead of running the Copilot SDK in-process, the backend forwards requests
to the Foundry-managed hosted agent container which runs the SDK.  The proxy
streams SSE events back in the same format the frontend expects.
"""

import json
import logging
from collections.abc import AsyncGenerator

import aiohttp
from azure.identity.aio import DefaultAzureCredential

from app.config import Settings

logger = logging.getLogger(__name__)

_AI_SCOPE = "https://ai.azure.com/.default"


class FoundryAgentProxy:
    """Invokes the Foundry hosted agent via the Invocations REST API."""

    def __init__(self, settings: Settings) -> None:
        # Build the invocations endpoint URL
        if settings.foundry_agent_invocations_endpoint:
            self._endpoint = settings.foundry_agent_invocations_endpoint
        else:
            project_ep = settings.foundry_project_endpoint or ""
            agent_name = settings.foundry_agent_name
            api_version = settings.foundry_api_version
            self._endpoint = (
                f"{project_ep.rstrip('/')}/agents/{agent_name}/endpoint/protocols/invocations?api-version={api_version}"
            )

        # In local mode the hosted agent is an unauthenticated localhost stub;
        # skip the Azure credential entirely (container has no `az` CLI / MSI).
        self._local_mode = settings.is_local_mode
        self._credential = None if self._local_mode else DefaultAzureCredential()
        self._http_session: aiohttp.ClientSession | None = None
        logger.info(
            "FoundryAgentProxy endpoint: %s (local_mode=%s)",
            self._endpoint,
            self._local_mode,
        )

    async def start(self) -> None:
        self._http_session = aiohttp.ClientSession()

    async def stop(self) -> None:
        if self._http_session:
            await self._http_session.close()
        if self._credential is not None:
            await self._credential.close()

    async def _get_token(self) -> str | None:
        if self._credential is None:
            return None
        token = await self._credential.get_token(_AI_SCOPE)
        return token.token

    async def invoke(
        self,
        message: str,
        conversation_id: str,
        use_case: str = "generic",
        system_prompt: str | None = None,
        agent_session_id: str | None = None,
        eval_run_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Invoke the hosted agent and yield event dicts.

        Each yielded dict has the form::

            {"event": "content", "data": {"content": "..."}}
            {"event": "thought", "data": {"content": "..."}}
            {"event": "tool_call", "data": {...}}
            {"event": "usage", "data": {...}}
            {"event": "done", "data": {...}}
            {"event": "error", "data": {...}}
        """
        # Prepend use-case metadata and system prompt so the hosted agent
        # can route to the correct skills even if the Invocations gateway
        # strips custom JSON fields like "useCase" from the payload.
        preamble_parts: list[str] = []
        if use_case and use_case != "generic":
            preamble_parts.append(f"<use_case>{use_case}</use_case>")
        if system_prompt:
            preamble_parts.append(f"<system_instructions>\n{system_prompt}\n</system_instructions>")
        input_text = "\n\n".join(preamble_parts) + f"\n\n{message}" if preamble_parts else message

        token = await self._get_token()
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Foundry-Features": "HostedAgents=V1Preview",
            "x-kratos-use-case": str(use_case) if use_case else "",
            "x-kratos-conversation-id": str(conversation_id) if conversation_id else "",
        }
        if eval_run_id:
            headers["x-kratos-eval-run-id"] = str(eval_run_id)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {
            "input": input_text,
            "conversationId": conversation_id,
            "useCase": use_case,
        }

        # Append agent_session_id as query parameter to reuse the same
        # gateway session (container) across messages in a conversation.
        endpoint = self._endpoint
        if agent_session_id:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}agent_session_id={agent_session_id}"

        try:
            async with self._http_session.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Hosted agent returned %d: %s", resp.status, body[:500])
                    yield {
                        "event": "error",
                        "data": {"message": f"Hosted agent error: HTTP {resp.status}", "code": "PROXY_ERROR"},
                    }
                    return

                # Capture the gateway session ID from response headers
                gateway_session = resp.headers.get("x-agent-session-id")

                # Parse SSE stream
                buffer = ""
                async for chunk in resp.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="replace")

                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        parsed = self._parse_sse_block(event_block)
                        if parsed is not None:
                            if parsed.get("_protocol_done"):
                                # Yield the gateway session ID before ending
                                # so the router can persist it for future calls.
                                if gateway_session:
                                    yield {"event": "_gateway_session", "data": {"agentSessionId": gateway_session}}
                                return
                            yield parsed

                # Fallback: if stream ends without a protocol done event,
                # still yield the gateway session.
                if gateway_session:
                    yield {"event": "_gateway_session", "data": {"agentSessionId": gateway_session}}

        except aiohttp.ClientError:
            logger.exception("Failed to invoke hosted agent")
            yield {
                "event": "error",
                "data": {"message": "Connection to hosted agent failed", "code": "PROXY_ERROR"},
            }

    @staticmethod
    def _parse_sse_block(block: str) -> dict | None:
        """Parse a single SSE event block into an event dict.

        Handles Invocations protocol events:
        - assistant.message / assistant.message_delta → content
        - assistant.reasoning / assistant.reasoning_delta → thought
        - tool.execution_start / tool.execution_complete → tool_call
        - SESSION_IDLE → done
        - SESSION_ERROR → error
        """
        event_type = None
        data_parts: list[str] = []

        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data_parts.append(line[6:])
            elif line.startswith("data:"):
                data_parts.append(line[5:])

        if not data_parts:
            return None

        data_str = "\n".join(data_parts)

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in SSE data: %s", data_str[:200])
            return None

        # Map Invocations protocol event types to our frontend format
        inv_type = data.get("type", "") if isinstance(data, dict) else ""
        content = data.get("data", {}).get("content", "") if isinstance(data, dict) else ""

        # Protocol-level done / idle
        if event_type == "done" or inv_type == "SESSION_IDLE":
            return {"_protocol_done": True}

        if inv_type == "SESSION_ERROR":
            return {"event": "error", "data": {"message": content or "Agent session error", "code": "AGENT_ERROR"}}

        # Content events
        if inv_type in ("assistant.message", "assistant.message_delta") and content:
            return {"event": "content", "data": {"content": content}}

        # Reasoning / thought events
        if inv_type in ("assistant.reasoning", "assistant.reasoning_delta") and content:
            return {"event": "thought", "data": {"content": content}}

        # Tool events
        if inv_type == "tool.execution_start":
            return {"event": "tool_call", "data": data.get("data", {})}

        if inv_type == "tool.execution_complete":
            return {"event": "tool_result", "data": data.get("data", {})}

        # Legacy format: application-level events with {"event": ..., "data": ...}
        if isinstance(data, dict) and "event" in data:
            return data

        return None
