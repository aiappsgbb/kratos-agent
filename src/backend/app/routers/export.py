"""Export API — download a use-case as a Foundry Hosted Agent ZIP.

Mirrors the ``GET /api/generate/export/{job_id}`` endpoint from
``threadlight-vnext`` but operates on already-existing use-case folders
instead of LLM-generated drafts.

Returns ``application/zip`` with a ``Content-Disposition`` attachment
header. The exporter materialises a project tree in a temporary directory
(removed automatically when the response is closed), then streams the
in-memory ZIP — no on-disk artefacts persist after the request completes.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import require_authenticated_user
from app.services.project_exporter import ProjectExporter
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


_USE_CASE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


_auth_dep = Depends(require_authenticated_user)


@router.get("/{use_case}/export", response_class=StreamingResponse)
async def export_use_case(
    use_case: str,
    request: Request,
    _principal: dict = _auth_dep,
) -> StreamingResponse:
    """Stream the use-case as a ``Foundry Hosted Agent`` ZIP archive.

    The returned file contains everything required to run the persona as
    a standalone hosted agent in someone else's Azure subscription via
    ``azd up``: copilot-instructions.md, skills/, mcp-config.json,
    bundled MCP mock packages, a single-tenant main.py, Dockerfile,
    pyproject.toml, agent.yaml, azure.yaml, and minimal infra/ Bicep.
    """
    if not _USE_CASE_NAME_RE.match(use_case):
        raise HTTPException(status_code=400, detail="Invalid use-case name")

    registries: dict[str, SkillRegistry] = request.app.state.registries
    if use_case not in registries:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")

    blob_service = getattr(request.app.state, "blob_skill_service", None)
    # Locate the on-disk use-case directory. Prefer the blob service's
    # local mirror; fall back to the conventional ``use-cases/<name>`` path
    # so tests don't need to wire up Blob.
    if blob_service is not None and getattr(blob_service, "local_base_dir", None):
        use_cases_root = Path(blob_service.local_base_dir)
    else:
        use_cases_root = Path("use-cases")

    exporter = ProjectExporter(use_cases_root=use_cases_root)

    try:
        with tempfile.TemporaryDirectory(prefix=f"kratos-export-{use_case}-") as td:
            project_dir = Path(td) / f"{use_case}-agent"
            project_dir.mkdir()
            exporter.assemble(use_case, project_dir)
            zip_bytes = ProjectExporter.build_zip(project_dir)
    except FileNotFoundError as exc:
        # Should be rare: registry knows about the use-case but its directory
        # is missing on disk. Treat as a server-side state inconsistency.
        logger.exception("Use-case '%s' directory missing on disk", use_case)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface as 500 with safe message
        logger.exception("Failed to export use-case '%s'", use_case)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    filename = f"{use_case}-foundry-agent.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(zip_bytes)),
        "Cache-Control": "no-store",
    }
    return StreamingResponse(io.BytesIO(zip_bytes), media_type="application/zip", headers=headers)
