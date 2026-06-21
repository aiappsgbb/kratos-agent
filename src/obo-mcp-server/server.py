"""OBO MCP server — exposes a Microsoft Graph ``/me`` tool over MCP (HTTP).

The kratos agent connects to this server as a *remote* MCP server and injects
the signed-in user's Entra access token into the ``Authorization`` request
header (see kratos hosted-agent ``main.py``). This server validates that token,
performs a secret-less On-Behalf-Of exchange, and returns the user's Graph
profile — so the tool runs **as the signed-in user**, not as the agent.

Transport: streamable HTTP at ``/mcp`` (FastMCP default). The Copilot SDK
connects with ``{"type": "http", "url": "https://<fqdn>/mcp"}``.
"""

from __future__ import annotations

import json
import logging
import os

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request

from obo import TokenValidationError, assert_auth_config_safe, validate_user_token
from obo import get_my_profile as fetch_my_profile

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("obo-mcp-server")

PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP(name="graph-obo", host="0.0.0.0", port=PORT)


def _bearer_from_context(ctx: Context) -> str:
    """Extract the Bearer token from the inbound HTTP request headers.

    The token is NEVER passed as a tool argument (which would make it visible to
    the model); it travels only in the transport ``Authorization`` header.
    """
    request: Request | None = getattr(ctx.request_context, "request", None)
    if request is None:
        raise TokenValidationError("no HTTP request context (is this running over HTTP transport?)")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise TokenValidationError("missing or malformed Authorization header")
    return auth[7:].strip()


@mcp.tool()
def get_my_profile(ctx: Context) -> dict:
    """Return the signed-in user's Microsoft 365 profile (name, email, job title).

    Use this whenever the user asks about themselves — "who am I", "what's my
    email", "what's my job title", "show my profile". The profile is fetched
    live from Microsoft Graph on behalf of the signed-in user.
    """
    try:
        token = _bearer_from_context(ctx)
        validate_user_token(token)  # rejects wrong audience / scope / tenant / expiry
        profile = fetch_my_profile(token)
        logger.info("get_my_profile: returned profile for upn=%s", profile.get("userPrincipalName"))
        # Full (non-sensitive) projection at INFO so demos/observability can show
        # exactly what Graph returned — including the live profile photo + the
        # graph-only proof fields (graphRequestId, account/password dates) that
        # are absent from the access token. The report harness reads this line.
        logger.info("get_my_profile result: %s", json.dumps(profile, default=str))
        # The 48x48 photo is a base64 data URI — useful for the report (captured
        # from the log above) but noise for the model, which might echo the blob.
        # Hand the model everything EXCEPT the raw image bytes.
        model_view = {k: v for k, v in profile.items() if k != "photoDataUri"}
        if "photoDataUri" in profile:
            model_view["hasProfilePhoto"] = True
        return model_view
    except TokenValidationError as exc:
        # Do not leak the token; surface a clean, actionable error.
        logger.warning("get_my_profile: token rejected: %s", exc)
        return {"error": "unauthorized", "detail": str(exc)}
    except Exception:  # noqa: BLE001 — surface OBO/Graph failures without leaking internals
        # Log full detail server-side; return an opaque message so library
        # internals (correlation ids, tenant info, token fragments) never reach
        # the model or end user.
        logger.exception("get_my_profile: OBO/Graph call failed")
        return {"error": "obo_failed", "detail": "Graph on-behalf-of request failed"}


if __name__ == "__main__":
    assert_auth_config_safe()  # refuse to start with AUTH_DISABLED outside dev
    logger.info("Starting OBO MCP server on :%d (streamable-http at /mcp)", PORT)
    mcp.run(transport="streamable-http")
