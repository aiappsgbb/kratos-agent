"""Admin API for managing the system prompt — backed by Blob Storage / local disk.

Reads and writes the use-case-specific system prompt via the SkillRegistry,
which persists to Azure Blob Storage (prod) or local use-cases/ directory (dev).
No Cosmos DB involvement.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_authenticated_user
from app.models import SystemPromptResponse, SystemPromptUpdate
from app.services.copilot_agent import DEFAULT_SYSTEM_PROMPT
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _get_registry(request: Request, use_case: str) -> SkillRegistry:
    """Resolve the SkillRegistry for the given use-case."""
    registries = getattr(request.app.state, "registries", {})
    registry = registries.get(use_case)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")
    return registry


@router.get("", response_model=SystemPromptResponse)
async def get_system_prompt(request: Request, use_case: str = Query("generic")) -> SystemPromptResponse:
    """Return the system prompt for a use-case."""
    registry = _get_registry(request, use_case)
    if registry.system_prompt:
        return SystemPromptResponse(content=registry.system_prompt, isDefault=False)
    return SystemPromptResponse(content=DEFAULT_SYSTEM_PROMPT, isDefault=True)


@router.put("", response_model=SystemPromptResponse)
async def update_system_prompt(
    body: SystemPromptUpdate, request: Request, use_case: str = Query("generic")
) -> SystemPromptResponse:
    """Update the system prompt for a use-case. Persists to Blob Storage / local disk."""
    registry = _get_registry(request, use_case)

    registry.system_prompt = body.content

    # Persist to blob storage or local disk
    blob_service = getattr(registry, "_blob_service", None)
    if blob_service and blob_service.is_available:
        blob_path = f"use-cases/{use_case}/SYSTEM_PROMPT.md"
        await blob_service.upload_file(blob_path, body.content.encode())
    else:
        from pathlib import Path

        prompt_path = Path("use-cases") / use_case / "SYSTEM_PROMPT.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(body.content)

    logger.info("System prompt updated for use-case '%s' (%d chars)", use_case, len(body.content))
    return SystemPromptResponse(content=body.content, isDefault=False)


@router.delete("", status_code=204)
async def reset_system_prompt(request: Request, use_case: str = Query("generic")) -> None:
    """Reset the system prompt by re-syncing from blob storage."""
    registry = _get_registry(request, use_case)

    blob_service = getattr(registry, "_blob_service", None)
    if blob_service and blob_service.is_available:
        await blob_service.sync_to_local(use_case)
        local_dir = blob_service.local_dir(use_case)
        prompt_path = local_dir / "SYSTEM_PROMPT.md"
        if prompt_path.exists():
            registry.system_prompt = prompt_path.read_text()

    logger.info("System prompt reset for use-case '%s'", use_case)
