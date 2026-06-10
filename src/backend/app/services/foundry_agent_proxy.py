"""Foundry Hosted Agent proxy — invokes the hosted agent via the Invocations REST API.

Instead of running the Copilot SDK in-process, the backend forwards requests
to the Foundry-managed hosted agent container which runs the SDK.  The proxy
streams SSE events back in the same format the frontend expects.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator

import aiohttp
from azure.identity.aio import DefaultAzureCredential

from app.config import Settings

logger = logging.getLogger(__name__)

_AI_SCOPE = "https://ai.azure.com/.default"

# HTTP statuses returned by the hosted-agent gateway while the (scale-to-zero)
# container is cold-starting or briefly overloaded. These are transient — the
# container is warming up — so the invocation is retried.
_COLD_START_STATUSES = frozenset({408, 425, 429, 503, 504})
_MAX_INVOKE_ATTEMPTS = 3


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
        # Warm pool of pre-provisioned, UNCLAIMED gateway sessions.
        #
        # Foundry hosted agents scale per-session: each distinct
        # agent_session_id gets its own VM-isolated sandbox (its own /tmp
        # filesystem) that cold-starts (~16s) and stays warm ~15 min. The only
        # way to be fast is to reuse a warm sandbox — but reusing ONE sandbox
        # across conversations leaks files between them (they share /tmp).
        #
        # So instead we keep a small pool of sessions that are warm but NOT yet
        # assigned to any conversation. A new conversation claims one (pops it
        # from the pool) and owns it exclusively: already warm (~1.5s) AND fully
        # isolated (no other conversation ever uses that session id / sandbox).
        # An empty pool degrades gracefully to a cold but still-isolated start.
        self._warm_pool: list[str] = []
        self._pool_target: int = max(0, int(getattr(settings, "warm_pool_size", 2)))
        self._pool_lock = asyncio.Lock()
        self._replenishing = False
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

    @property
    def warm_pool_size(self) -> int:
        """Current number of unclaimed pre-warmed sessions available."""
        return len(self._warm_pool)

    async def _warmup_ping(self, session_id: str | None) -> tuple[bool, str | None, int, float]:
        """POST a lightweight ``{"warmup": true}`` ping to the hosted agent.

        When ``session_id`` is None the gateway provisions a BRAND-NEW
        VM-isolated sandbox and returns its fresh ``x-agent-session-id`` (used to
        grow the warm pool). When a ``session_id`` is supplied the ping targets
        that existing sandbox and resets its idle timer (used to keep pooled
        sessions alive). The hosted agent recognises the warmup payload and
        returns immediately (no model call, no persistence) once its services
        are initialised.

        Returns ``(ok, returned_session_id, status, elapsed_seconds)``. Never
        raises — transient errors are reported via the return value.
        """
        if self._http_session is None:
            return (False, None, 0, 0.0)

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        try:
            token = await self._get_token()
        except Exception:  # noqa: BLE001 — never let token errors kill the pool loop
            logger.warning("Warm-pool: token acquisition failed", exc_info=True)
            return (False, None, 0, loop.time() - t0)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Foundry-Features": "HostedAgents=V1Preview",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        endpoint = self._endpoint
        if session_id:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}agent_session_id={session_id}"

        try:
            async with self._http_session.post(
                endpoint,
                headers=headers,
                json={"warmup": True},
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                body = await resp.read()
                elapsed = loop.time() - t0
                ok = resp.status == 200
                returned = resp.headers.get("x-agent-session-id")
                if not ok:
                    logger.warning("Warm-pool ping returned HTTP %d in %.1fs", resp.status, elapsed)
                else:
                    # The hosted agent reports its own _startup() cost so we can
                    # distinguish platform microVM boot from our init work.
                    with contextlib.suppress(Exception):
                        payload = json.loads(body)
                        startup_ms = payload.get("startup_ms")
                        if startup_ms is not None:
                            logger.info(
                                "Warm-pool: hosted-agent core ready in %sms (phases=%s, loaded=%s)",
                                startup_ms,
                                payload.get("phases"),
                                payload.get("loaded_use_cases"),
                            )
                return (ok, returned, resp.status, elapsed)
        except (aiohttp.ClientError, TimeoutError):
            elapsed = loop.time() - t0
            logger.warning("Warm-pool ping failed after %.1fs", elapsed, exc_info=True)
            return (False, None, 0, elapsed)

    async def _replenish_pool(self) -> None:
        """Provision new pre-warmed sessions until the pool reaches its target.

        Each provisioning call cold-starts a fresh sandbox (~16s) but this runs
        in the background, off the user's request path.
        """
        while True:
            async with self._pool_lock:
                deficit = self._pool_target - len(self._warm_pool)
            if deficit <= 0:
                return
            ok, sid, status, elapsed = await self._warmup_ping(None)
            if ok and sid:
                async with self._pool_lock:
                    if sid not in self._warm_pool and len(self._warm_pool) < self._pool_target:
                        self._warm_pool.append(sid)
                        size = len(self._warm_pool)
                    else:
                        size = len(self._warm_pool)
                logger.info(
                    "Warm-pool: provisioned isolated session %s (%.1fs), pool=%d/%d",
                    sid,
                    elapsed,
                    size,
                    self._pool_target,
                )
            else:
                logger.warning("Warm-pool: provisioning failed (status=%d, %.1fs)", status, elapsed)
                return  # avoid hot-looping on persistent failure

    def _schedule_replenish(self) -> None:
        """Kick a single background pool replenish (deduped)."""
        if self._replenishing:
            return
        self._replenishing = True

        async def _run() -> None:
            try:
                await self._replenish_pool()
            finally:
                self._replenishing = False

        with contextlib.suppress(RuntimeError):
            asyncio.get_event_loop().create_task(_run())

    async def claim_warm_session(self) -> str | None:
        """Pop a pre-warmed session for exclusive use by one conversation.

        Returns a warm session id the caller owns exclusively (fast + isolated),
        or None when the pool is empty (caller cold-starts a fresh isolated
        session). Always kicks a background replenish so the pool refills for the
        next new conversation.
        """
        async with self._pool_lock:
            sid = self._warm_pool.pop(0) if self._warm_pool else None
            remaining = len(self._warm_pool)
        if sid:
            logger.info("Warm-pool: claimed isolated session %s, pool=%d/%d", sid, remaining, self._pool_target)
        else:
            logger.info("Warm-pool: empty — new conversation will cold-start (still isolated)")
        self._schedule_replenish()
        return sid

    async def maintain_warm_pool(self) -> tuple[int, int]:
        """Keep pooled sessions alive and replenish to target. Returns (size, target).

        Called periodically by the keep-warm loop. Pings each unclaimed pool
        member with its own id to reset the platform's 15-min idle timer, drops
        any that have died, then tops the pool back up.
        """
        async with self._pool_lock:
            members = list(self._warm_pool)
        for sid in members:
            ok, _, _, _ = await self._warmup_ping(sid)
            if not ok:
                async with self._pool_lock:
                    if sid in self._warm_pool:
                        self._warm_pool.remove(sid)
                logger.warning("Warm-pool: dropped dead session %s", sid)
        await self._replenish_pool()
        async with self._pool_lock:
            return (len(self._warm_pool), self._pool_target)

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
        # gateway session (container) across messages in a conversation. For the
        # FIRST turn of a new conversation (no per-conversation session yet),
        # claim a DEDICATED pre-warmed session from the pool: the request lands
        # on an already-provisioned sandbox (~1.5s) that this conversation owns
        # exclusively (no shared /tmp with other conversations). If the pool is
        # empty, fall back to None so the gateway assigns a fresh isolated
        # session (cold ~16s, but still never shared).
        effective_session_id = agent_session_id
        if effective_session_id is None:
            effective_session_id = await self.claim_warm_session()
        endpoint = self._endpoint
        if effective_session_id:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}agent_session_id={effective_session_id}"

        try:
            for attempt in range(1, _MAX_INVOKE_ATTEMPTS + 1):
                async with self._http_session.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("Hosted agent returned %d: %s", resp.status, body[:500])
                        # Cold-start / transient overload — the container is
                        # warming up, so retry with a short backoff before
                        # surfacing an error to the user.
                        if resp.status in _COLD_START_STATUSES and attempt < _MAX_INVOKE_ATTEMPTS:
                            backoff = 3 * attempt
                            logger.warning(
                                "Hosted agent cold-start (HTTP %d); retrying in %ds (attempt %d/%d)",
                                resp.status,
                                backoff,
                                attempt,
                                _MAX_INVOKE_ATTEMPTS,
                            )
                            await asyncio.sleep(backoff)
                            continue
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
                    return

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
