"""Project Exporter — pack a Kratos use-case into a self-contained ZIP.

V2 ("full-clone") design — the exported project is a structural mirror of
the subset of the Kratos repo that the hosted-agent runtime needs, with
**only the chosen use-case present** under ``use-cases/``. ``azd up`` runs
against the same Dockerfile and ``main.py`` that Kratos itself runs, so the
exported agent's behaviour matches Kratos byte-for-byte for that persona.

ZIP layout
==========

.. code-block:: text

    <use-case>-agent/
    ├── azure.yaml                       (rendered: single hosted-agent service)
    ├── README.md, .env.template, .gitignore, .dockerignore  (rendered/copied)
    ├── src/
    │   ├── hosted-agent/                (5 files: 3 verbatim + 2 rendered)
    │   │   ├── main.py                  ← src/hosted-agent/main.py verbatim
    │   │   ├── pyproject.toml           ← verbatim
    │   │   ├── Dockerfile               ← verbatim (uses repo-root context)
    │   │   ├── agent.yaml               ← rendered (slug + persona name)
    │   │   └── agent.manifest.yaml      ← rendered (slug + persona name)
    │   └── backend/app/                 ← copied recursively (no exporter_templates,
    │                                       no __pycache__, no *.pyc)
    ├── use-cases/<chosen>/              ← the chosen use-case ONLY
    ├── mocks/                           ← copied verbatim (package.json + packages/*)
    └── infra/                           (vendored trimmed Bicep + Kratos modules)
        ├── main.bicep                   ← vendored trimmed copy
        ├── main.parameters.json         ← vendored
        ├── abbreviations.json           ← copied from Kratos infra/
        └── modules/
            ├── role-assignments.bicep   ← vendored trimmed copy
            └── (9 others)               ← copied from Kratos infra/modules/

The vendored Bicep lives under ``app/exporter_templates/infra/`` so it ships
inside the wheel; the other 9 modules + abbreviations.json are read from the
checkout via ``self.repo_root`` (defaults to cwd) to stay in sync with any
Kratos infra changes.
"""

from __future__ import annotations

import io
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

# Directories that should never be copied into the export — build artefacts
# or per-environment state that would defeat the point of a portable ZIP.
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
        "dist",  # JS build artefacts
        "build",
        "exporter_templates",  # Don't ship the exporter's own templates
    }
)
_SKIP_FILE_SUFFIXES: frozenset[str] = frozenset({".pyc", ".pyo", ".DS_Store"})

# YAML frontmatter delimiter used by all SYSTEM_PROMPT.md / SKILL.md files.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Where the parameterised + vendored templates live inside the wheel.
_TEMPLATES_PACKAGE = "app.exporter_templates"

# Mapping of source-template filename → final filename in the exported tree
# **at the root**. Templates with ``.template`` suffix are stripped;
# ``dot-foo`` files are rewritten as ``.foo``.
_ROOT_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("azure.yaml.template", "azure.yaml"),
    ("README.md.template", "README.md"),
    ("dot-env.template", ".env.template"),
    ("dot-dockerignore.template", ".dockerignore"),
    ("dot-gitignore.template", ".gitignore"),
)

# Templates rendered into ``src/hosted-agent/``.
_HOSTED_AGENT_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("agent.yaml.template", "agent.yaml"),
    ("agent.manifest.yaml.template", "agent.manifest.yaml"),
)

# Templates rendered into ``hooks/`` at the project root. These are azd
# lifecycle hooks (``postdeploy``) and need the exec bit set on the POSIX
# variant. A PowerShell sibling ships alongside so ``azd up`` also works on
# Windows (azd picks the OS-specific variant declared in ``azure.yaml``).
_HOOKS_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("hooks/postdeploy.sh.template", "postdeploy.sh"),
    ("hooks/postdeploy.ps1.template", "postdeploy.ps1"),
)

# Subset of templates that need ``${placeholder}`` substitution.
_PARAMETERIZED: frozenset[str] = frozenset(
    {
        "azure.yaml.template",
        "README.md.template",
        "dot-env.template",
        "agent.yaml.template",
        "agent.manifest.yaml.template",
        "hooks/postdeploy.sh.template",
        "hooks/postdeploy.ps1.template",
    }
)

# Files in ``src/hosted-agent/`` copied verbatim into the export.
_HOSTED_AGENT_VERBATIM: tuple[str, ...] = ("main.py", "pyproject.toml", "Dockerfile")

# Infra/modules files copied verbatim from the Kratos checkout. Five modules
# from Kratos's main.bicep are intentionally dropped because the exported
# agent doesn't need them (no Container App backend, no APIM, no frontend,
# no Bing): ``agent-service``, ``container-apps-env``, ``ai-gateway``,
# ``static-web-app``, ``bing-search``.
_INFRA_MODULES_FROM_KRATOS: tuple[str, ...] = (
    "network.bicep",
    "log-analytics.bicep",
    "app-insights.bicep",
    "key-vault.bicep",
    "cosmos-db.bicep",
    "ai-search.bicep",
    "ai-services.bicep",
    "blob-storage.bicep",
    "container-registry.bicep",
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

    def __init__(self, repo_root: Path | str = ".") -> None:
        """Construct an exporter rooted at a Kratos checkout.

        Args:
            repo_root: Path to the Kratos repo (the directory containing
                ``src/hosted-agent/``, ``src/backend/``, ``use-cases/``,
                ``mocks/``, and ``infra/``). Defaults to the current
                working directory.
        """
        self.repo_root = Path(repo_root).resolve()
        self.hosted_agent_dir = self.repo_root / "src" / "hosted-agent"
        self.backend_app_dir = self.repo_root / "src" / "backend" / "app"
        self.use_cases_dir = self.repo_root / "use-cases"
        self.mocks_dir = self.repo_root / "mocks"
        self.infra_dir = self.repo_root / "infra"

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
        src_use_case = self.use_cases_dir / use_case
        if not src_use_case.is_dir():
            raise FileNotFoundError(f"Use-case directory not found: {src_use_case}")
        if not self.hosted_agent_dir.is_dir():
            raise FileNotFoundError(f"Hosted-agent dir not found: {self.hosted_agent_dir}")
        if not self.backend_app_dir.is_dir():
            raise FileNotFoundError(f"Backend app dir not found: {self.backend_app_dir}")

        ctx = self._build_context(use_case, src_use_case)
        logger.info("Exporting use-case '%s' (slug=%s) → %s", use_case, ctx.slug, output_dir)

        # 1. Hosted-agent runtime
        self._copy_hosted_agent(output_dir, ctx)
        # 2. Backend app modules (CopilotAgent, SkillRegistry, …)
        self._copy_backend_app(output_dir)
        # 3. The chosen use-case
        self._copy_use_case(use_case, output_dir)
        # 4. Mocks (npm workspaces with all stdio MCP servers)
        self._copy_mocks(output_dir)
        # 5. Trimmed infra (Bicep)
        self._copy_infra(output_dir)
        # 6. Root files: azure.yaml, README, .env.template, .gitignore, .dockerignore
        self._render_root_templates(ctx, output_dir)
        # 7. azd lifecycle hooks (hooks/postdeploy.sh — grants RBAC to
        #    hosted-agent managed identities that Foundry creates AFTER bicep)
        self._render_hooks(ctx, output_dir)
        return output_dir

    @staticmethod
    def build_zip(project_dir: Path) -> bytes:
        """Pack a project directory into an in-memory ZIP byte string.

        Carries the source file's Unix permission bits into the zip's
        external_attr so ``unzip`` restores the exec bit on shell hooks
        (otherwise ``./hooks/postdeploy.sh`` would land non-executable).
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(_iter_zipable_files(project_dir)):
                arcname = path.relative_to(project_dir).as_posix()
                info = zipfile.ZipInfo.from_file(path, arcname=arcname)
                # Preserve unix mode bits in the high 16 bits of external_attr,
                # mirroring what `zip` does on Linux/macOS.
                mode = path.stat().st_mode & 0xFFFF
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as fh:
                    zf.writestr(info, fh.read())
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(use_case: str, src_use_case: Path) -> ExportContext:
        """Parse SYSTEM_PROMPT.md frontmatter to derive name / description."""
        prompt_path = src_use_case / "SYSTEM_PROMPT.md"
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

    def _copy_hosted_agent(self, dst_dir: Path, ctx: ExportContext) -> None:
        """Mirror ``src/hosted-agent/`` into the export.

        Three files (main.py, pyproject.toml, Dockerfile) are copied verbatim
        — these are the runtime entry point + dependencies + container build,
        and they assume the repo-root layout (Dockerfile uses ``COPY src/``,
        ``COPY mocks/``, ``COPY use-cases/``) which the export mirrors.

        Two files (agent.yaml, agent.manifest.yaml) are rendered from
        templates so the persona name / slug / Cosmos DB scope reflect the
        chosen use-case.
        """
        dst = dst_dir / "src" / "hosted-agent"
        dst.mkdir(parents=True, exist_ok=True)

        for name in _HOSTED_AGENT_VERBATIM:
            src = self.hosted_agent_dir / name
            if not src.is_file():
                raise FileNotFoundError(f"Required hosted-agent file missing: {src}")
            shutil.copy2(src, dst / name)

        substitutions = _substitutions(ctx)
        for src_name, dst_name in _HOSTED_AGENT_TEMPLATE_FILES:
            raw = _read_template_text(src_name)
            rendered = string.Template(raw).safe_substitute(substitutions) if src_name in _PARAMETERIZED else raw
            (dst / dst_name).write_text(rendered, encoding="utf-8")

    def _copy_backend_app(self, dst_dir: Path) -> None:
        """Copy ``src/backend/app/`` recursively into the export.

        Skips ``exporter_templates/`` (the exporter shouldn't ship its own
        templates), ``__pycache__``, ``*.pyc`` and other junk per
        ``_SKIP_DIRS`` / ``_SKIP_FILE_SUFFIXES``.
        """
        dst = dst_dir / "src" / "backend" / "app"
        _copy_tree(self.backend_app_dir, dst)
        # Also bring src/backend/pyproject.toml if present — required for
        # local-dev installs of the backend modules.
        backend_pyproject = self.backend_app_dir.parent / "pyproject.toml"
        if backend_pyproject.is_file():
            shutil.copy2(backend_pyproject, dst.parent / "pyproject.toml")

    def _copy_use_case(self, use_case: str, dst_dir: Path) -> None:
        """Copy ONLY the chosen use-case under ``use-cases/<use_case>/``."""
        src = self.use_cases_dir / use_case
        dst = dst_dir / "use-cases" / use_case
        _copy_tree(src, dst)

    def _copy_mocks(self, dst_dir: Path) -> None:
        """Copy the whole ``mocks/`` tree (workspaces + all stdio servers).

        Even mocks that the chosen use-case doesn't reference are bundled —
        the npm workspace install is fast, and shipping the full set lets
        the user extend the persona without re-exporting.
        """
        if not self.mocks_dir.is_dir():
            logger.info("No mocks/ directory at %s — skipping", self.mocks_dir)
            return
        dst = dst_dir / "mocks"
        _copy_tree(self.mocks_dir, dst)

    def _copy_infra(self, dst_dir: Path) -> None:
        """Copy the trimmed infra/ subtree.

        Sources:
        * ``main.bicep`` + ``main.parameters.json`` + ``modules/role-assignments.bicep``
          come from the wheel (``app/exporter_templates/infra/``) — these
          are the *trimmed* versions that drop the modules the export
          doesn't need.
        * ``abbreviations.json`` + 9 other modules come from the Kratos
          checkout (``infra/`` and ``infra/modules/``) so they stay in sync
          with any Kratos infra changes.
        """
        dst_infra = dst_dir / "infra"
        dst_modules = dst_infra / "modules"
        dst_modules.mkdir(parents=True, exist_ok=True)

        # 1. Vendored trimmed Bicep (3 files) from the templates package.
        vendored = resources.files(_TEMPLATES_PACKAGE).joinpath("infra")
        (dst_infra / "main.bicep").write_text(
            vendored.joinpath("main.bicep").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (dst_infra / "main.parameters.json").write_text(
            vendored.joinpath("main.parameters.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (dst_modules / "role-assignments.bicep").write_text(
            vendored.joinpath("modules/role-assignments.bicep").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        # 2. Verbatim copies from the Kratos checkout.
        kratos_infra = self.infra_dir
        if not kratos_infra.is_dir():
            raise FileNotFoundError(f"Kratos infra/ not found at {kratos_infra}")

        abbreviations = kratos_infra / "abbreviations.json"
        if abbreviations.is_file():
            shutil.copy2(abbreviations, dst_infra / "abbreviations.json")
        else:
            raise FileNotFoundError(f"abbreviations.json not found at {abbreviations}")

        kratos_modules = kratos_infra / "modules"
        if not kratos_modules.is_dir():
            raise FileNotFoundError(f"Kratos infra/modules/ not found at {kratos_modules}")

        for module_name in _INFRA_MODULES_FROM_KRATOS:
            src = kratos_modules / module_name
            if not src.is_file():
                raise FileNotFoundError(f"Required infra module missing in Kratos: {src}")
            shutil.copy2(src, dst_modules / module_name)

    @staticmethod
    def _render_root_templates(ctx: ExportContext, dst_dir: Path) -> None:
        """Render every entry in ``_ROOT_TEMPLATE_FILES`` into the project root."""
        substitutions = _substitutions(ctx)
        for src_name, dst_name in _ROOT_TEMPLATE_FILES:
            raw = _read_template_text(src_name)
            rendered = string.Template(raw).safe_substitute(substitutions) if src_name in _PARAMETERIZED else raw
            target = dst_dir / dst_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")

    @staticmethod
    def _render_hooks(ctx: ExportContext, dst_dir: Path) -> None:
        """Render ``hooks/*`` templates and set the executable bit on shell scripts."""
        substitutions = _substitutions(ctx)
        hooks_dir = dst_dir / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for src_name, dst_name in _HOOKS_TEMPLATE_FILES:
            raw = _read_template_text(src_name)
            rendered = string.Template(raw).safe_substitute(substitutions) if src_name in _PARAMETERIZED else raw
            target = hooks_dir / dst_name
            target.write_text(rendered, encoding="utf-8")
            if target.suffix == ".sh":
                # rwxr-xr-x — Foundry / azd run this via /bin/sh; needs exec bit.
                target.chmod(0o755)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _substitutions(ctx: ExportContext) -> dict[str, str]:
    """Build the ``${placeholder}`` map used by ``string.Template``."""
    return {
        "name": ctx.name,
        "slug": ctx.slug,
        "description": ctx.description,
        "use_case": ctx.use_case,
    }


def _slugify(value: str) -> str:
    """Make a string filesystem-/azd-service-name-safe (kebab-case, [a-z0-9-])."""
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return slug or "agent"


def _iter_zipable_files(root: Path) -> Iterable[Path]:
    """Walk ``root`` yielding files that should be archived."""
    for path in root.rglob("*"):
        if path.is_dir():
            continue
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
