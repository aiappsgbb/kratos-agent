"""Persona import API — create a Kratos use-case from a threadlight manifest.

``POST /api/use-cases/import`` accepts a threadlight-design-compatible persona
manifest (the primary, deterministic path — no LLM) and maps it onto the three
core persona files Kratos already understands:

* ``SYSTEM_PROMPT.md`` — frontmatter (name/description/sampleQuestions/curated)
  plus the manifest ``instructions`` as the body.
* ``.mcp.json``        — Copilot MCP config built from ``mcpServers``.
* ``apm.yml``          — APM manifest carrying ``skills`` (→ ``dependencies.apm``)
  and ``mcpServers`` (→ ``dependencies.mcp``), with ``traits``/``workflow_model``
  recorded under ``metadata.kratos``.

The persona is persisted (blob + local mirror) and registered live in
``app.state.registries`` so it is immediately selectable in the UI.

A secondary natural-language ``prompt`` path is supported: the prompt is
expanded into a manifest via the Foundry model and then runs through the exact
same deterministic mapping. See design spec §5.
"""

from __future__ import annotations

import json
import logging
import re

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_authenticated_user
from app.models import (
    ImportMcpServer,
    PersonaImportRequest,
    PersonaImportResponse,
    PersonaManifest,
)
from app.services.blob_skill_service import BlobSkillService
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter()

_USE_CASE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_auth_dep = Depends(require_authenticated_user)


# ─── Slug helpers ────────────────────────────────────────────────────────────


def _slugify(value: str) -> str:
    """Normalise an arbitrary string into a valid use-case slug.

    Produces a value matching ``^[a-z0-9][a-z0-9-]{0,63}$`` or ``"persona"``
    when nothing usable remains.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:64].strip("-")
    if not slug or not slug[0].isalnum():
        slug = f"persona-{slug}".strip("-")[:64] if slug else "persona"
    return slug or "persona"


async def _resolve_slug(
    base: str,
    *,
    registries: dict[str, SkillRegistry],
    blob_service: BlobSkillService,
    overwrite: bool,
    dedupe: bool,
) -> str:
    """Resolve the final slug, honouring overwrite / dedupe semantics.

    * ``overwrite`` → return ``base`` unchanged (existing persona replaced).
    * ``dedupe``    → return the first free ``base``, ``base-2``, ``base-3`` …
    * otherwise     → return ``base``; the caller raises 409 if it exists.
    """
    if overwrite:
        return base

    async def _taken(name: str) -> bool:
        return name in registries or await blob_service.use_case_exists(name)

    if not dedupe:
        return base

    if not await _taken(base):
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"[:64].strip("-")
        if not await _taken(candidate):
            return candidate
    raise HTTPException(status_code=409, detail="Unable to allocate a unique persona slug")


# ─── Manifest → persona files mapping ────────────────────────────────────────


def _build_system_prompt(manifest: PersonaManifest, slug: str) -> str:
    """Render SYSTEM_PROMPT.md (frontmatter + instructions body)."""
    display = manifest.displayName or manifest.name or slug.replace("-", " ").title()
    frontmatter: dict = {
        "name": display,
        "description": manifest.description,
        "sampleQuestions": list(manifest.sampleQuestions),
        "curated": True,
    }
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body = manifest.instructions.strip() or f"You are {display}, an enterprise AI assistant."
    return f"---\n{fm_yaml}\n---\n\n{body}\n"


def _build_mcp_json(servers: list[ImportMcpServer]) -> str:
    """Render .mcp.json (Copilot MCP config) from the manifest MCP servers.

    ``.mcp.json`` is loaded verbatim into the Copilot SDK session config, so every
    entry must be runnable. A remote (http/sse) server needs a ``url``; a registry
    reference without one cannot be expressed here deterministically (it would need
    ``apm install`` to resolve a command/url). Such entries are therefore skipped —
    they remain recorded in ``apm.yml`` ``dependencies.mcp`` for later resolution —
    so the imported persona never carries a non-startable MCP server.
    """
    config: dict[str, dict] = {}
    for server in servers:
        if not server.url:
            logger.info(
                "Skipping MCP server '%s' in .mcp.json: no url (registry=%s, transport=%s); "
                "kept in apm.yml dependencies.mcp for later resolution",
                server.name,
                server.registry,
                server.transport,
            )
            continue
        config[server.name] = {"type": server.transport, "url": server.url}
    return json.dumps(config, indent=2) + "\n"


def _build_apm_yml(manifest: PersonaManifest, slug: str) -> str:
    """Render apm.yml carrying skill + MCP dependencies and Kratos metadata."""
    apm_packages = [s.package for s in manifest.skills if s.package]
    mcp_deps = [
        {
            "name": s.name,
            "registry": s.registry,
            "transport": s.transport,
            **({"url": s.url} if s.url else {}),
        }
        for s in manifest.mcpServers
    ]

    dependencies: dict = {}
    if apm_packages:
        dependencies["apm"] = apm_packages
    if mcp_deps:
        dependencies["mcp"] = mcp_deps

    data: dict = {
        "name": f"kratos-{slug}",
        "version": "1.0.0",
        "description": manifest.description or f"Kratos persona — {slug}",
        "author": "kratos-import",
        "license": "MIT",
        "target": "copilot",
        "dependencies": dependencies,
        "metadata": {
            "kratos": {
                "traits": list(manifest.traits),
                "workflow_model": manifest.workflow_model,
                "skills": [s.name for s in manifest.skills],
            }
        },
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


# ─── Natural-language (secondary) path ───────────────────────────────────────

_NL_SYSTEM_PROMPT = """\
You convert a short natural-language description of an AI agent persona into a
strict JSON manifest. Respond with ONLY a JSON object, no prose, matching:

{
  "name": "short human name",
  "description": "one sentence",
  "instructions": "the system prompt body — how the agent should behave",
  "sampleQuestions": ["3-5 example user questions"],
  "skills": [{"name": "kebab-name", "description": "what it does"}],
  "mcpServers": [],
  "traits": ["optional descriptive traits"],
  "workflow_model": "agent"
}

Keep instructions concise and actionable. Do not invent MCP servers or skill
packages the user did not ask for.\
"""


async def _expand_prompt_to_manifest(prompt: str) -> PersonaManifest:
    """Expand a natural-language prompt into a PersonaManifest via the model."""
    from app.routers.admin_analysis import _call_llm

    raw = await _call_llm(_NL_SYSTEM_PROMPT, prompt, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("NL manifest expansion returned invalid JSON: %s", raw[:500])
        raise HTTPException(status_code=502, detail="Model returned invalid manifest JSON") from exc
    try:
        return PersonaManifest.model_validate(data)
    except Exception as exc:  # noqa: BLE001 — surface validation as 502 (model output)
        logger.error("NL manifest failed validation: %s", exc)
        raise HTTPException(status_code=502, detail=f"Model manifest failed validation: {exc}") from exc


# ─── Endpoint ────────────────────────────────────────────────────────────────


@router.post("/import", response_model=PersonaImportResponse, status_code=201)
async def import_persona(
    request: Request,
    body: PersonaImportRequest,
    _principal: dict = _auth_dep,
) -> PersonaImportResponse:
    """Create a Kratos persona from a threadlight manifest (or NL prompt).

    Returns ``201`` with the created persona summary. ``409`` when the slug is
    taken and neither ``overwrite`` nor ``dedupe`` apply. ``422`` for an invalid
    request body. ``502`` when the optional NL expansion fails.
    """
    blob_service: BlobSkillService | None = getattr(request.app.state, "blob_skill_service", None)
    registries: dict[str, SkillRegistry] | None = getattr(request.app.state, "registries", None)
    if blob_service is None or registries is None:
        raise HTTPException(status_code=503, detail="Persona storage is not initialised")

    manifest = body.manifest or await _expand_prompt_to_manifest(body.prompt or "")

    base_slug = _slugify(body.name or manifest.name)
    if not _USE_CASE_NAME_RE.match(base_slug):
        raise HTTPException(status_code=422, detail="Could not derive a valid persona name")

    already_exists = base_slug in registries or await blob_service.use_case_exists(base_slug)
    if already_exists and not body.overwrite and not body.dedupe:
        raise HTTPException(status_code=409, detail=f"Persona '{base_slug}' already exists")

    slug = await _resolve_slug(
        base_slug,
        registries=registries,
        blob_service=blob_service,
        overwrite=body.overwrite,
        dedupe=body.dedupe,
    )
    replaced = body.overwrite and (slug in registries or await blob_service.use_case_exists(slug))

    system_prompt_md = _build_system_prompt(manifest, slug)
    mcp_json = _build_mcp_json(manifest.mcpServers)
    apm_yml = _build_apm_yml(manifest, slug)

    try:
        files = await blob_service.create_use_case(
            slug,
            system_prompt_md=system_prompt_md,
            mcp_json=mcp_json,
            apm_yml=apm_yml,
            overwrite=body.overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Persona '{slug}' already exists") from exc

    apm_service = getattr(request.app.state, "apm_service", None)
    registry = SkillRegistry()
    await registry.load(
        slug,
        blob_service,
        apm_service=apm_service,
        local_root=str(blob_service.local_base_dir),
    )
    registries[slug] = registry

    display = manifest.displayName or manifest.name or slug.replace("-", " ").title()
    logger.info("Imported persona '%s' (replaced=%s, skills=%d)", slug, replaced, len(registry.skills))
    return PersonaImportResponse(
        name=slug,
        displayName=display,
        description=manifest.description,
        skillCount=len(registry.skills),
        created=not replaced,
        files=files,
    )
