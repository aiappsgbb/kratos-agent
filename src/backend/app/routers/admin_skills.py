"""Admin API for managing skills — CRUD operations backed by Blob Storage."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_authenticated_user
from app.models import SkillCreate, SkillFile, SkillFileList, SkillFileUpsert, SkillList, SkillResponse, SkillUpdate
from app.services.skill_registry import SkillMetadata, SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _get_registry(request: Request, use_case: str) -> SkillRegistry:
    """Resolve the SkillRegistry for the given use-case."""
    registries = getattr(request.app.state, "registries", {})
    registry = registries.get(use_case)
    if registry is None:
        # Fall back to the legacy single registry
        registry = getattr(request.app.state, "skill_registry", None)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")
    return registry


def _reset_sessions(request: Request) -> None:
    """No-op — sessions are managed by the Foundry hosted agent."""
    logger.debug("Session reset skipped — Copilot SDK runs in hosted agent")


def _count_skill_files(skill: SkillMetadata) -> int:
    """Count non-SKILL.md files in a skill's local directory."""
    if not skill.local_path:
        return 0
    skill_dir = Path(skill.local_path)
    if not skill_dir.exists():
        return 0
    return sum(1 for f in skill_dir.rglob("*") if f.is_file() and f.name != "SKILL.md")


def _to_response(skill: SkillMetadata) -> SkillResponse:
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        enabled=skill.enabled,
        instructions=skill.instructions,
        toolName=skill.tool_name or skill.name.replace("-", "_"),
        fileCount=_count_skill_files(skill),
        source=skill.source,
    )


@router.get("", response_model=SkillList)
async def list_skills(request: Request, use_case: str = Query("generic")) -> SkillList:
    """List all registered skills for a use-case."""
    registry = _get_registry(request, use_case)
    skills = sorted(registry.skills.values(), key=lambda s: s.name)
    return SkillList(skills=[_to_response(s) for s in skills])


@router.get("/{skill_name}", response_model=SkillResponse)
async def get_skill(skill_name: str, request: Request, use_case: str = Query("generic")) -> SkillResponse:
    """Get a single skill by name."""
    registry = _get_registry(request, use_case)
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return _to_response(skill)


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(body: SkillCreate, request: Request, use_case: str = Query("generic")) -> SkillResponse:
    """Create a new skill definition."""
    registry = _get_registry(request, use_case)

    if registry.get_skill(body.name):
        raise HTTPException(status_code=409, detail=f"Skill '{body.name}' already exists")

    skill = SkillMetadata(
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        instructions=body.instructions,
        tool_name=body.name.replace("-", "_"),
    )
    await registry.add_skill(skill)
    _reset_sessions(request)
    logger.info("Admin created skill: %s", body.name)
    return _to_response(skill)


@router.patch("/{skill_name}", response_model=SkillResponse)
async def update_skill(
    skill_name: str, body: SkillUpdate, request: Request, use_case: str = Query("generic")
) -> SkillResponse:
    """Update an existing skill (partial update)."""
    registry = _get_registry(request, use_case)

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    skill = await registry.update_skill(skill_name, updates)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    _reset_sessions(request)
    logger.info("Admin updated skill: %s fields=%s", skill_name, list(updates.keys()))
    return _to_response(skill)


@router.delete("/{skill_name}", status_code=204)
async def delete_skill(skill_name: str, request: Request, use_case: str = Query("generic")) -> None:
    """Delete a skill definition."""
    registry = _get_registry(request, use_case)

    removed = await registry.remove_skill(skill_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    _reset_sessions(request)
    logger.info("Admin deleted skill: %s", skill_name)


# ─── Skill file management ────────────────────────────────────────────────────


def _validate_file_path(file_path: str) -> None:
    """Reject paths with directory traversal or absolute components."""
    parts = Path(file_path).parts
    if any(p in ("..", "/", "\\") for p in parts) or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")


@router.get("/{skill_name}/files", response_model=SkillFileList)
async def list_skill_files(skill_name: str, request: Request, use_case: str = Query("generic")) -> SkillFileList:
    """List all non-SKILL.md files for a skill, including their content."""
    registry = _get_registry(request, use_case)
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    raw_files = registry.list_skill_files(skill_name)
    result: list[SkillFile] = []
    skill_dir = Path(skill.local_path) if skill.local_path else None
    for entry in raw_files:
        content = ""
        if skill_dir:
            f = skill_dir / entry["path"]
            try:
                content = f.read_text(errors="replace")
            except Exception:
                content = ""
        result.append(SkillFile(path=entry["path"], name=entry["name"], content=content))
    return SkillFileList(files=result)


@router.put("/{skill_name}/files/{file_path:path}", status_code=204)
async def upsert_skill_file(
    skill_name: str,
    file_path: str,
    body: SkillFileUpsert,
    request: Request,
    use_case: str = Query("generic"),
) -> None:
    """Upload or update a file within a skill folder."""
    _validate_file_path(file_path)
    registry = _get_registry(request, use_case)
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    await registry.upsert_skill_file(skill_name, file_path, body.content.encode())
    logger.info("Admin upserted file: %s/%s/%s", use_case, skill_name, file_path)


@router.delete("/{skill_name}/files/{file_path:path}", status_code=204)
async def delete_skill_file(
    skill_name: str,
    file_path: str,
    request: Request,
    use_case: str = Query("generic"),
) -> None:
    """Delete a file from a skill folder."""
    _validate_file_path(file_path)
    registry = _get_registry(request, use_case)
    if not registry.get_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    await registry.remove_skill_file(skill_name, file_path)
    logger.info("Admin deleted file: %s/%s/%s", use_case, skill_name, file_path)
