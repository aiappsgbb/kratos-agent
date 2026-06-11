"""Project Exporter — pack a Kratos use-case into a self-contained ZIP.

This service mirrors the pattern used by ``threadlight-vnext``'s
``ProjectAssembler.assemble_export_package`` but adapted for Kratos:

* TL generates raw files with an LLM and *then* wraps them; Kratos's raw
  files are already on disk under ``use-cases/<name>/`` — we only need the
  "wrap and ship" half.
* Standalone runtime — the exported agent does NOT depend on Kratos's
  multi-tenant backend (no Cosmos, no Blob, no SkillRegistry).
* MCP mocks are bundled into the ZIP so it works out-of-the-box: the
  Dockerfile ``npm install -g``-s them.
* Templates live inside the wheel under ``app/exporter_templates/`` and are
  resolved via ``importlib.resources`` so the service works both in dev
  (editable install) and in a Docker image.

The router calls ``ProjectExporter.assemble(...)`` which materialises a
project tree on disk, then ``build_zip(...)`` to stream it as
``application/zip``. A temporary directory holds the build; everything is
cleaned up by the router.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import string
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Directories and files that must never be copied into the exported project —
# either build artefacts or per-environment state that would defeat the
# point of a portable ZIP.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "node_modules",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".azure",
        "evals",  # Eval scenarios are a Kratos-only authoring tool
        "apm_modules",  # APM-materialised content — re-installed by `apm install`
        ".github",  # APM-managed materialisation
    }
)
_SKIP_FILE_SUFFIXES: frozenset[str] = frozenset({".pyc", ".pyo", ".DS_Store"})

# YAML frontmatter delimiter used by all SYSTEM_PROMPT.md / SKILL.md files.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Where the static + parameterised templates live inside the wheel.
_TEMPLATES_PACKAGE = "app.exporter_templates"

# Mapping of source-template filename → final filename in the exported tree.
# Templates with ``.template`` suffix are stripped; ``dot-foo`` files are
# rewritten as ``.foo``; everything else passes through. Files that need
# placeholder substitution are noted in ``_PARAMETERIZED``.
_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("main.py.template", "main.py"),
    ("Dockerfile.template", "Dockerfile"),
    ("pyproject.toml.template", "pyproject.toml"),
    ("agent.yaml.template", "agent.yaml"),
    ("agent.manifest.yaml.template", "agent.manifest.yaml"),
    ("azure.yaml.template", "azure.yaml"),
    ("README.md.template", "README.md"),
    ("dot-env.template", ".env.template"),
    ("dot-dockerignore.template", ".dockerignore"),
    ("dot-gitignore.template", ".gitignore"),
)

# Subset of templates that contain ``${placeholder}`` markers and must be
# rendered with the use-case metadata.
_PARAMETERIZED: frozenset[str] = frozenset(
    {
        "pyproject.toml.template",
        "agent.yaml.template",
        "agent.manifest.yaml.template",
        "azure.yaml.template",
        "README.md.template",
        "Dockerfile.template",
    }
)


@dataclass(frozen=True)
class ExportContext:
    """All metadata needed to render the templates for one use-case."""

    use_case: str
    slug: str  # kebab-case identifier safe for filenames + azd service names
    name: str  # human-readable display name from frontmatter
    description: str


class ProjectExporter:
    """Assemble a Kratos use-case into a Foundry-Hosted-Agent project tree."""

    def __init__(self, use_cases_root: Path | str = "use-cases", mocks_root: Path | str = "mocks") -> None:
        self.use_cases_root = Path(use_cases_root)
        self.mocks_root = Path(mocks_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(self, use_case: str, output_dir: Path) -> Path:
        """Materialise the exported project tree.

        Args:
            use_case: The use-case folder name (e.g. ``"finance-close"``).
            output_dir: An EMPTY directory that will receive the project tree.
                Caller is responsible for creating/cleaning it.

        Returns:
            The path to the populated project directory (== ``output_dir``).
        """
        src_dir = self.use_cases_root / use_case
        if not src_dir.is_dir():
            raise FileNotFoundError(f"Use-case directory not found: {src_dir}")

        ctx = self._build_context(use_case, src_dir)
        logger.info("Exporting use-case '%s' → %s", use_case, output_dir)

        self._copy_system_prompt(src_dir, output_dir)
        self._copy_skills(src_dir, output_dir)
        mcp_servers = self._copy_mcp_config(src_dir, output_dir)
        self._copy_apm_manifest(src_dir, output_dir)
        self._copy_referenced_mocks(mcp_servers, output_dir)
        self._render_templates(ctx, output_dir)
        self._copy_infra(output_dir)
        return output_dir

    @staticmethod
    def build_zip(project_dir: Path) -> bytes:
        """Pack a project directory into an in-memory ZIP byte string."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(_iter_zipable_files(project_dir)):
                arcname = path.relative_to(project_dir).as_posix()
                zf.write(path, arcname)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(use_case: str, src_dir: Path) -> ExportContext:
        """Parse use-case frontmatter to derive display name / description."""
        prompt_path = src_dir / "SYSTEM_PROMPT.md"
        fm: dict = {}
        if prompt_path.is_file():
            match = _FRONTMATTER_RE.match(prompt_path.read_text(encoding="utf-8"))
            if match:
                try:
                    fm = yaml.safe_load(match.group(1)) or {}
                except yaml.YAMLError:
                    fm = {}

        slug = _slugify(use_case)
        name = str(fm.get("name") or use_case.replace("-", " ").title()).strip()
        description = str(
            fm.get("description") or f"Standalone Foundry Hosted Agent exported from Kratos use-case '{use_case}'."
        ).strip()
        return ExportContext(use_case=use_case, slug=slug, name=name, description=description)

    @staticmethod
    def _copy_system_prompt(src_dir: Path, dst_dir: Path) -> None:
        """Copy SYSTEM_PROMPT.md → copilot-instructions.md (verbatim)."""
        src = src_dir / "SYSTEM_PROMPT.md"
        if not src.is_file():
            logger.warning("No SYSTEM_PROMPT.md in %s — exporting empty instructions", src_dir)
            (dst_dir / "copilot-instructions.md").write_text("", encoding="utf-8")
            return
        shutil.copy2(src, dst_dir / "copilot-instructions.md")

    def _copy_skills(self, src_dir: Path, dst_dir: Path) -> None:
        """Recursively copy the ``skills/`` tree, filtering out junk."""
        src = src_dir / "skills"
        if not src.is_dir():
            logger.info("Use-case %s has no skills/ directory — skipping", src_dir.name)
            return
        dst = dst_dir / "skills"
        _copy_tree(src, dst)

    @staticmethod
    def _copy_mcp_config(src_dir: Path, dst_dir: Path) -> dict:
        """Copy ``.mcp.json`` → ``mcp-config.json`` and return parsed dict."""
        src = src_dir / ".mcp.json"
        if not src.is_file():
            return {}
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Invalid .mcp.json in %s — skipping MCP wiring", src_dir)
            return {}
        if not isinstance(data, dict):
            logger.warning(".mcp.json in %s is not an object — skipping", src_dir)
            return {}
        # Write canonical, sorted, 2-space JSON for diff stability.
        (dst_dir / "mcp-config.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return data

    @staticmethod
    def _copy_apm_manifest(src_dir: Path, dst_dir: Path) -> None:
        """Copy ``apm.yml`` only when it declares at least one dependency."""
        src = src_dir / "apm.yml"
        if not src.is_file():
            return
        try:
            parsed = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            logger.warning("Invalid apm.yml in %s — skipping", src_dir)
            return
        deps = parsed.get("dependencies") if isinstance(parsed, dict) else None
        has_deps = isinstance(deps, dict) and any(isinstance(v, list) and len(v) > 0 for v in deps.values())
        if not has_deps:
            logger.info("apm.yml in %s has no dependencies — omitting", src_dir)
            return
        shutil.copy2(src, dst_dir / "apm.yml")

    def _copy_referenced_mocks(self, mcp_servers: dict, dst_dir: Path) -> list[str]:
        """Bundle each ``local`` MCP server whose command matches a mock package.

        Returns the list of bundled package directory names (for logging /
        tests). When ``mocks/packages/`` doesn't exist (e.g. in tests) or the
        command doesn't match a known package, the entry is silently skipped —
        the user can install or wire the server themselves.
        """
        if not self.mocks_root.is_dir():
            return []
        packages_dir = self.mocks_root / "packages"
        if not packages_dir.is_dir():
            return []

        bundled: list[str] = []
        for name, server in mcp_servers.items():
            if not isinstance(server, dict):
                continue
            if server.get("type") != "local":
                continue
            command = server.get("command")
            if not isinstance(command, str) or not command:
                continue
            # Direct match: command == package directory name.
            candidate = packages_dir / command
            if not candidate.is_dir():
                logger.info("No bundled mock package for MCP server '%s' (command=%r)", name, command)
                continue
            dest = dst_dir / "mocks" / "packages" / command
            _copy_tree(candidate, dest)
            bundled.append(command)
            logger.info("Bundled MCP mock package: %s", command)
        return bundled

    @staticmethod
    def _render_templates(ctx: ExportContext, dst_dir: Path) -> None:
        """Render every entry in ``_TEMPLATE_FILES`` into the output tree."""
        substitutions = {
            "name": ctx.name,
            "slug": ctx.slug,
            "description": ctx.description,
            "use_case": ctx.use_case,
        }
        for src_name, dst_name in _TEMPLATE_FILES:
            raw = _read_template_text(src_name)
            rendered = string.Template(raw).safe_substitute(substitutions) if src_name in _PARAMETERIZED else raw
            target = dst_dir / dst_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")

    @staticmethod
    def _copy_infra(dst_dir: Path) -> None:
        """Vendor the entire ``infra/`` Bicep subtree from the templates package."""
        src = resources.files(_TEMPLATES_PACKAGE).joinpath("infra")
        dst = dst_dir / "infra"
        dst.mkdir(parents=True, exist_ok=True)
        _copy_resource_tree(src, dst)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Make a string filesystem-/azd-service-name-safe (kebab-case, [a-z0-9-])."""
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return slug or "agent"


def _iter_zipable_files(root: Path) -> Iterable[Path]:
    """Walk ``root`` yielding files that should be archived."""
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        # Skip if any path segment is in the skip-list.
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in _SKIP_FILE_SUFFIXES:
            continue
        yield path


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy ``src`` into ``dst`` while honouring the global skip rules."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            if path.suffix in _SKIP_FILE_SUFFIXES:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _read_template_text(name: str) -> str:
    """Return a template's text via ``importlib.resources`` (wheel-friendly)."""
    return resources.files(_TEMPLATES_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def _copy_resource_tree(src, dst: Path) -> None:  # noqa: ANN001 — Traversable
    """Recursively copy an ``importlib.resources`` Traversable into ``dst``."""
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            _copy_resource_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())
