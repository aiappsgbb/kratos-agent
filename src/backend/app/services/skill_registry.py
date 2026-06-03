"""Skill registry — loads and manages skills from Azure Blob Storage.

Skills are organized into use-cases:
  use-cases/{use-case}/SYSTEM_PROMPT.md
  use-cases/{use-case}/skills/{name}/SKILL.md
  use-cases/{use-case}/skills/{name}/scripts/...

All metadata (name, description, enabled) lives in the SKILL.md YAML
frontmatter.  Each use-case has its own SkillRegistry instance and
system prompt.  On startup, the service loads all use-cases from blob
(or local fallback) into an in-memory dict of registries.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from app.services.apm_service import ApmService
    from app.services.blob_skill_service import BlobSkillService

logger = logging.getLogger(__name__)

# Regex matching YAML frontmatter block: ---\n...\n---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md content.

    Returns (frontmatter_dict, body_without_frontmatter).
    If no frontmatter is found, returns ({}, original_text).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    body = text[match.end() :]
    return fm, body


def _update_frontmatter(text: str, **updates: object) -> str:
    """Update YAML frontmatter fields, preserving body and other fields."""
    fm, body = _parse_frontmatter(text)
    fm.update(updates)
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{fm_str}\n---\n\n{body.lstrip()}"


def _skill_from_md(name: str, instructions: str, local_path: str = "") -> SkillMetadata:
    """Build a SkillMetadata from a SKILL.md string, using frontmatter for all fields."""
    fm, _ = _parse_frontmatter(instructions)
    return SkillMetadata(
        name=fm.get("name", name),
        description=fm.get("description", ""),
        enabled=fm.get("enabled", True),
        instructions=instructions,
        tool_name=fm.get("name", name).replace("-", "_"),
        local_path=local_path,
    )


@dataclass
class SkillMetadata:
    """Metadata for a registered skill."""

    name: str
    description: str
    enabled: bool = True
    instructions: str = ""
    tool_name: str = ""  # maps to the @define_tool function name
    local_path: str = ""  # local filesystem path after sync
    source: str = "local"  # origin: "local", "blob", or "apm:{package}"


@dataclass
class SkillRegistry:
    """Registry of available skills for a single use-case.

    Each use-case gets its own SkillRegistry loaded from blob or local disk.
    """

    use_case: str = "generic"
    system_prompt: str = ""
    skills: dict[str, SkillMetadata] = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)
    mcp_sources: dict[str, str] = field(default_factory=dict)
    _blob_service: BlobSkillService | None = field(default=None, repr=False)

    async def load(
        self,
        use_case: str,
        blob_service: BlobSkillService | None = None,
        apm_service: ApmService | None = None,
        local_root: str = "use-cases",
    ) -> None:
        """Load skills for a use-case from blob storage.

        After the local/blob load pass completes, materialised APM skill
        directories (if any) are merged in via ``_load_apm_skills``.
        Local/blob skills win on name collisions.
        """
        self.use_case = use_case
        self._blob_service = blob_service
        self.mcp_sources = {}

        if blob_service is not None and blob_service.is_available:
            # Sync this use-case from blob → local filesystem
            await blob_service.sync_to_local(use_case)
            local_dir = blob_service.local_dir(use_case)

            # Read system prompt
            prompt_path = local_dir / "SYSTEM_PROMPT.md"
            if prompt_path.exists():
                self.system_prompt = prompt_path.read_text()

            # Load MCP servers config
            mcp_path = local_dir / ".mcp.json"
            if mcp_path.exists():
                try:
                    self.mcp_servers = json.loads(mcp_path.read_text())
                    self.mcp_sources = dict.fromkeys(self.mcp_servers, "blob")
                    logger.info("Loaded MCP servers (blob) for '%s': %s", use_case, list(self.mcp_servers.keys()))
                except json.JSONDecodeError:
                    logger.warning("Invalid .mcp.json for use-case '%s'", use_case)
            else:
                logger.info("No .mcp.json found at %s (blob path)", mcp_path)

            # Load skills
            for skill_name in await blob_service.list_skill_names(use_case):
                skill_md_path = local_dir / "skills" / skill_name / "SKILL.md"
                if not skill_md_path.exists():
                    continue
                instructions = skill_md_path.read_text()
                skill = _skill_from_md(skill_name, instructions, str(local_dir / "skills" / skill_name))
                skill.source = "blob"
                self.skills[skill.name] = skill

            logger.info("Loaded use-case '%s': %d skills from blob", use_case, len(self.skills))
        else:
            # No blob available — fall back to local use-cases/ directory
            await self._load_from_local(use_case, local_root)

        # Merge APM-materialised skills (local/blob wins on name collision)
        if apm_service is not None:
            await self._load_apm_skills(apm_service)
            await self._load_apm_mcp_servers(apm_service)

    async def _load_from_local(self, use_case: str, local_root: str = "use-cases") -> None:
        """Load a use-case from the baked-in use-cases/ directory (local dev fallback)."""
        uc_dir = Path(local_root) / use_case
        if not uc_dir.exists():
            logger.warning("No local use-case directory found: %s", uc_dir)
            return

        # Read system prompt
        prompt_path = uc_dir / "SYSTEM_PROMPT.md"
        if prompt_path.exists():
            self.system_prompt = prompt_path.read_text()

        # Load MCP servers config
        mcp_path = uc_dir / ".mcp.json"
        if mcp_path.exists():
            try:
                self.mcp_servers = json.loads(mcp_path.read_text())
                self.mcp_sources = dict.fromkeys(self.mcp_servers, "local")
                logger.info("Loaded MCP servers for '%s': %s", use_case, list(self.mcp_servers.keys()))
            except json.JSONDecodeError:
                logger.warning("Invalid .mcp.json for use-case '%s'", use_case)
        else:
            logger.info("No .mcp.json found at %s", mcp_path)

        # Load skills
        skills_dir = uc_dir / "skills"
        if not skills_dir.exists():
            logger.warning("No skills directory in use-case: %s", use_case)
            return

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            instructions = skill_md.read_text()
            skill = _skill_from_md(skill_dir.name, instructions, str(skill_dir))
            self.skills[skill.name] = skill
            logger.info("Registered skill: %s/%s (enabled=%s)", use_case, skill.name, skill.enabled)

        logger.info("Loaded use-case '%s': %d skills from local", use_case, len(self.skills))

    async def _load_apm_skills(self, apm_service: ApmService) -> None:
        """Merge skills from materialised APM packages into the registry.

        Scans ``use-cases/{uc}/.github/skills/{folder}/SKILL.md`` directories
        returned by the APM service. Skills whose names already exist in
        ``self.skills`` (from local/blob) are skipped — local/blob wins.
        """
        try:
            skill_dirs = await apm_service.list_materialised_skill_dirs(self.use_case)
        except Exception:  # noqa: BLE001 — APM failures must not break skill loading
            logger.exception("Failed to list APM skill dirs for use-case '%s'", self.use_case)
            return

        merged = 0
        for skill_dir in skill_dirs:
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                instructions = skill_md.read_text()
            except OSError:
                logger.warning("Unable to read APM SKILL.md at %s", skill_md)
                continue

            folder_name = skill_dir.name
            skill = _skill_from_md(folder_name, instructions, str(skill_dir))
            skill.source = f"apm:{folder_name}"

            if skill.name in self.skills:
                logger.debug(
                    "APM skill '%s' shadowed by local/blob skill for use-case '%s'",
                    skill.name,
                    self.use_case,
                )
                continue

            self.skills[skill.name] = skill
            merged += 1

        logger.info("Merged %d APM skills for use-case '%s'", merged, self.use_case)

    async def _load_apm_mcp_servers(self, apm_service: ApmService) -> None:
        """Merge MCP servers declared via APM into ``self.mcp_servers``.

        Reads the resolved entries from ``apm.lock.yaml`` (falling back to
        ``apm.yml`` for newly-declared-not-yet-installed rows) and merges
        each into the Copilot-SDK-shaped ``mcp_servers`` dict. Entries that
        already exist (from local/blob ``.mcp.json``) are preserved — local
        wins on name collision — matching the skills merge policy.

        Registry-only entries (just a name, no resolved command/url) are
        skipped: they can't be started until ``apm install`` runs. They
        still appear in the APM status API so the UI can prompt a sync.
        """
        try:
            servers = await apm_service.list_mcp_servers(self.use_case)
        except Exception:  # noqa: BLE001 — APM failures must not break MCP loading
            logger.exception("Failed to list APM MCP servers for use-case '%s'", self.use_case)
            return

        merged = 0
        for server in servers:
            if server.name in self.mcp_servers:
                logger.debug(
                    "APM MCP server '%s' shadowed by local/blob config for use-case '%s'",
                    server.name,
                    self.use_case,
                )
                continue
            # Registry-only aliases have no command/url yet — skip until
            # `apm install` resolves them.
            if not server.command and not server.url:
                continue
            self.mcp_servers[server.name] = server.to_copilot_config()
            self.mcp_sources[server.name] = f"apm:{server.name}"
            merged += 1

        if merged:
            logger.info(
                "Merged %d APM MCP servers for use-case '%s': %s",
                merged,
                self.use_case,
                [s.name for s in servers if s.name in self.mcp_sources and self.mcp_sources[s.name].startswith("apm:")],
            )

    def get_enabled_skills(self) -> list[SkillMetadata]:
        """Return all enabled skills."""
        return [s for s in self.skills.values() if s.enabled]

    def get_skill(self, name: str) -> SkillMetadata | None:
        """Get a specific skill by name."""
        return self.skills.get(name)

    def get_skill_directories(self) -> list[str]:
        """Return local directory paths for enabled skills with instructions.

        The SDK expects directory paths containing SKILL.md files.
        After blob sync, these are already on the local filesystem.

        If a skill directory contains auxiliary files (scripts, references,
        data), a ``## Available Files`` section is appended to SKILL.md so
        the agent knows it can ``read_file`` them at runtime.
        """
        dirs: list[str] = []
        for skill in self.get_enabled_skills():
            if skill.local_path:
                skill_dir = Path(skill.local_path)
                # Ensure SKILL.md is written (may have been updated via admin)
                if skill.instructions:
                    skill_dir.mkdir(parents=True, exist_ok=True)
                    enriched = self._enrich_skill_md(skill.instructions, skill_dir)
                    (skill_dir / "SKILL.md").write_text(enriched)
                if skill_dir.exists():
                    dirs.append(str(skill_dir))
        return dirs

    @staticmethod
    def _enrich_skill_md(instructions: str, skill_dir: Path) -> str:
        """Append an inventory of auxiliary files to the SKILL.md content.

        The SDK only reads SKILL.md, but the Copilot CLI has a built-in
        ``read_file`` tool.  By listing the files that exist alongside
        SKILL.md the agent learns about them and can read them on demand.
        """
        aux_files: list[str] = []
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file() and f.name != "SKILL.md":
                aux_files.append(str(f.relative_to(skill_dir)))

        if not aux_files:
            return instructions

        # Strip any previously appended inventory (idempotent)
        marker = "\n\n<!-- skill-files -->"
        base = instructions.split(marker)[0]

        listing = "\n".join(f"- `{p}`" for p in aux_files)
        return (
            f"{base}{marker}\n"
            f"## Available Files\n\n"
            f"This skill directory contains the following files you can read "
            f"with `read_file` using their absolute paths (prefix `{skill_dir}/`):\n\n"
            f"{listing}\n"
        )

    def get_enabled_tool_names(self) -> set[str]:
        """Return tool function names for enabled skills."""
        return {s.tool_name or s.name.replace("-", "_") for s in self.get_enabled_skills()}

    def list_skill_files(self, name: str) -> list[dict[str, str]]:
        """List non-SKILL.md files in a skill's local directory."""
        skill = self.skills.get(name)
        if not skill or not skill.local_path:
            return []
        skill_dir = Path(skill.local_path)
        if not skill_dir.exists():
            return []
        files = []
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file() and f.name != "SKILL.md":
                relative = str(f.relative_to(skill_dir))
                files.append({"path": relative, "name": f.name})
        return files

    async def upsert_skill_file(self, skill_name: str, file_path: str, content: bytes) -> None:
        """Upload or update a file in a skill folder (local + blob)."""
        skill = self.skills.get(skill_name)
        if not skill:
            return
        if skill.local_path:
            local_file = Path(skill.local_path) / file_path
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(content)
        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.upload_skill_file(self.use_case, skill_name, file_path, content)

    async def remove_skill_file(self, skill_name: str, file_path: str) -> bool:
        """Delete a file from a skill folder (local + blob)."""
        skill = self.skills.get(skill_name)
        if not skill:
            return False
        if skill.local_path:
            local_file = Path(skill.local_path) / file_path
            if local_file.is_file():
                local_file.unlink()
        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.delete_skill_file(self.use_case, skill_name, file_path)
        return True

    # ─── Admin operations ─────────────────────────────────────────────────

    async def update_skill(self, name: str, updates: dict) -> SkillMetadata | None:
        """Update a skill in the registry and persist to blob via SKILL.md.

        Note: operates on blob-local skills only. Updating an ``apm:*`` skill
        writes a blob copy that shadows the APM original on next load.
        """
        skill = self.skills.get(name)
        if not skill:
            return None

        if "enabled" in updates:
            skill.enabled = updates["enabled"]

        if "instructions" in updates:
            skill.instructions = updates["instructions"]
            fm, _ = _parse_frontmatter(skill.instructions)
            if fm.get("description"):
                skill.description = fm["description"]

        if "description" in updates:
            skill.description = updates["description"]

        # Ensure frontmatter reflects current state
        skill.instructions = _update_frontmatter(
            skill.instructions,
            name=skill.name,
            description=skill.description,
            enabled=skill.enabled,
        )

        self.skills[name] = skill

        # Persist SKILL.md to blob
        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.upload_skill_file(self.use_case, name, "SKILL.md", skill.instructions.encode())

        # Update local copy
        if skill.local_path:
            local_dir = Path(skill.local_path)
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "SKILL.md").write_text(skill.instructions)

        return skill

    async def add_skill(self, skill: SkillMetadata) -> SkillMetadata:
        """Add a new skill to the registry and persist to blob via SKILL.md."""
        if skill.instructions:
            fm, _ = _parse_frontmatter(skill.instructions)
            if fm.get("description"):
                skill.description = fm["description"]

        # Ensure frontmatter contains all metadata
        skill.instructions = _update_frontmatter(
            skill.instructions,
            name=skill.name,
            description=skill.description,
            enabled=skill.enabled,
        )

        # Set local path
        if self._blob_service and self._blob_service.is_available:
            skill.local_path = str(self._blob_service.local_dir(self.use_case) / "skills" / skill.name)
        else:
            skill.local_path = str(Path("use-cases") / self.use_case / "skills" / skill.name)

        self.skills[skill.name] = skill

        # Persist SKILL.md to blob
        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.upload_skill_file(
                self.use_case, skill.name, "SKILL.md", skill.instructions.encode()
            )

        # Write local copy
        local_dir = Path(skill.local_path)
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "SKILL.md").write_text(skill.instructions)

        logger.info("Added skill: %s/%s", self.use_case, skill.name)
        return skill

    async def remove_skill(self, name: str) -> bool:
        """Remove a skill from the registry and blob storage.

        Note: operates on blob-local skills only. Removing an ``apm:*`` skill
        from blob does not delete the APM-materialised source; it will
        reappear on the next load.
        """
        if name not in self.skills:
            return False

        del self.skills[name]

        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.delete_skill(name)

        logger.info("Removed skill: %s", name)
        return True

    async def update_mcp_servers(self, servers: dict) -> None:
        """Persist the MCP servers config as .mcp.json (local + blob)."""
        self.mcp_servers = servers
        # Manual edits are always blob- (or local-) authored. APM-sourced
        # entries that are also in this payload get re-classified — the
        # user just overrode them.
        source_label = "blob" if self._blob_service and self._blob_service.is_available else "local"
        self.mcp_sources = dict.fromkeys(servers, source_label)
        content = json.dumps(servers, indent=2).encode()

        # Write to local filesystem so in-process sessions can reload
        if self._blob_service and self._blob_service.is_available:
            local_path = self._blob_service.local_dir(self.use_case) / ".mcp.json"
        else:
            local_path = Path("use-cases") / self.use_case / ".mcp.json"

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)

        # Upload to blob so it persists across restarts
        if self._blob_service and self._blob_service.is_available:
            await self._blob_service.upload_mcp_config(self.use_case, content)

        logger.info("MCP servers config updated for use-case '%s': %d servers", self.use_case, len(servers))
