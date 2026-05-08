"""Admin API for managing MCP server configs — stored as .mcp.json per use-case in blob."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_authenticated_user
from app.models import MCPConfigResponse, MCPConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


@router.get("", response_model=MCPConfigResponse)
async def get_mcp_config(use_case: str, request: Request) -> MCPConfigResponse:
    """Return the current MCP servers config for a use-case."""
    registries: dict = request.app.state.registries
    registry = registries.get(use_case)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")
    return MCPConfigResponse(
        servers=registry.mcp_servers,
        sources=getattr(registry, "mcp_sources", {}),
    )


@router.put("", response_model=MCPConfigResponse)
async def update_mcp_config(use_case: str, body: MCPConfigUpdate, request: Request) -> MCPConfigResponse:
    """Update (replace) the MCP servers config for a use-case. Clears active sessions."""
    registries: dict = request.app.state.registries
    registry = registries.get(use_case)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")

    await registry.update_mcp_servers(body.servers)

    logger.info("MCP config updated for use-case '%s': %d servers", use_case, len(body.servers))
    return MCPConfigResponse(
        servers=body.servers,
        sources=getattr(registry, "mcp_sources", {}),
    )
