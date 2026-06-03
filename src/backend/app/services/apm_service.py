"""APM (Agent Package Manager) service.

Thin async wrapper around the `apm` CLI (https://microsoft.github.io/apm/).
Each use-case has its own ``apm.yml`` manifest living at
``use-cases/{use_case}/apm.yml``; this service shells out to the ``apm``
binary with that directory as the working directory so manifests stay
isolated per use-case.

Responsibilities:
  * Run ``apm install``/``uninstall``/``update`` in a subprocess with
    per-use-case serialisation (asyncio.Lock).
  * Parse ``apm.yml`` / ``apm.lock.yaml`` directly for read operations
    (faster and deterministic than shelling out to ``apm list``).
  * Push manifest changes back to blob via :class:`BlobSkillService`.
  * Expose helpers consumed by the skill registry and startup sync.

All mutating calls require ``settings.apm_enabled`` to be True; read
operations work regardless so the UI can still show the declared deps
even when APM is disabled.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import Settings
from app.services.blob_skill_service import BlobSkillService

logger = logging.getLogger(__name__)

_STDERR_TAIL_BYTES = 2048
_APM_MANIFEST = "apm.yml"
_APM_LOCKFILE = "apm.lock.yaml"
_APM_MODULES_DIR = "apm_modules"


@dataclass
class ApmCommandResult:
    """Outcome of a single `apm` subprocess invocation."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    success: bool = field(init=False)

    def __post_init__(self) -> None:
        self.success = self.returncode == 0


@dataclass
class ApmDependency:
    """A single declared APM dependency for a use-case.

    Attributes:
        name: Package identifier without ref (e.g. ``microsoft/apm-sample-package``).
        ref: Requested git ref (tag/branch/sha) or ``None`` if unpinned.
        resolved: Resolved commit SHA from ``apm.lock.yaml`` if available.
        source: Raw spec string as it appears in ``apm.yml``.
    """

    name: str
    ref: str | None
    resolved: str | None
    source: str


@dataclass
class ApmMcpServer:
    """A single MCP server declared in ``apm.yml``/``apm.lock.yaml``.

    The APM CLI lets a use-case declare MCP servers under
    ``dependencies.mcp``. Each entry is either a registry alias
    (``- microsoft/markitdown``) or an inline spec (``name``, ``command``,
    ``args`` …). The lockfile flattens both forms into ``mcp_configs``.

    Attributes:
        name: Server name (used as the key in the Copilot SDK config dict).
        transport: ``stdio`` | ``http`` | ``sse``.
        command: Executable for stdio transports (``uvx``, ``npx`` …).
        args: Command-line arguments for stdio transports.
        url: Endpoint for http/sse transports.
        env: Environment variables passed to the server process.
        registry: True if the entry was resolved via the APM MCP registry.
    """

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    registry: bool = False

    def to_copilot_config(self) -> dict[str, object]:
        """Render as a Copilot-SDK MCP server entry (matches ``mcp-config.json``).

        The Copilot runtime expects ``type: local`` for stdio servers and
        ``type: http`` (or ``sse``) for remote ones. ``tools: ["*"]`` opts into
        every tool the server advertises — same default the CLI writes.
        """
        if self.transport in ("http", "sse"):
            cfg: dict[str, object] = {
                "type": self.transport,
                "url": self.url or "",
                "tools": ["*"],
            }
        else:
            cfg = {
                "type": "local",
                "command": self.command or "",
                "args": list(self.args),
                "tools": ["*"],
            }
        if self.env:
            cfg["env"] = dict(self.env)
        return cfg


class ApmError(RuntimeError):
    """Raised when an APM operation fails.

    The original :class:`ApmCommandResult` is attached (when available) so
    callers can surface stdout/stderr and the exact command in responses.
    """

    def __init__(self, message: str, result: ApmCommandResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class ApmService:
    """Async facade over the ``apm`` CLI, scoped per use-case.

    A per-use-case :class:`asyncio.Lock` serialises mutating commands
    (install/uninstall/sync/update) while allowing different use-cases to
    run in parallel. Read-only helpers (``list_dependencies``,
    ``list_materialised_skill_dirs``, ``needs_sync``) do not take the lock.
    """

    def __init__(
        self,
        settings: Settings,
        blob_service: BlobSkillService | None = None,
    ) -> None:
        self.settings = settings
        self.blob_service = blob_service
        self._locks: dict[str, asyncio.Lock] = {}
        self._version_cache: str | None = None

    # ─── Paths & locks ────────────────────────────────────────────────────

    def _use_case_dir(self, use_case: str) -> Path:
        """Return absolute path to the use-case working dir, raising if missing."""
        path = (Path(self.settings.apm_use_cases_root) / use_case).resolve()
        if not path.is_dir():
            raise ApmError(f"Use case '{use_case}' not found at {path}")
        return path

    def _lock_for(self, use_case: str) -> asyncio.Lock:
        lock = self._locks.get(use_case)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[use_case] = lock
        return lock

    # ─── Subprocess plumbing ──────────────────────────────────────────────

    async def _run(
        self,
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ApmCommandResult:
        """Run ``apm <args>`` and return a populated :class:`ApmCommandResult`.

        Raises:
            ApmError: if the binary is missing, or the process exits non-zero.
        """
        command = [self.settings.apm_binary, *args]
        logger.info("apm: running %s (cwd=%s)", " ".join(command), cwd)

        # When caller supplies env overrides, merge into the current env so
        # we don't accidentally drop PATH, HOME, etc. required by the CLI.
        proc_env: dict[str, str] | None = None
        if env:
            proc_env = {**os.environ, **{str(k): str(v) for k, v in env.items()}}

        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
            )
        except FileNotFoundError as exc:
            raise ApmError(f"apm binary '{self.settings.apm_binary}' not found on PATH: {exc}") from exc

        stdout_b, stderr_b = await proc.communicate()
        duration_ms = (time.perf_counter() - start) * 1000.0

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        result = ApmCommandResult(
            command=command,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

        logger.info(
            "apm: done %s rc=%d duration_ms=%.1f",
            " ".join(command),
            result.returncode,
            duration_ms,
        )

        if not result.success:
            tail = stderr[-_STDERR_TAIL_BYTES:] if stderr else ""
            logger.warning(
                "apm command failed: %s (rc=%d)\nstderr tail:\n%s",
                " ".join(command),
                result.returncode,
                tail,
            )
            raise ApmError(
                f"apm command failed (rc={result.returncode}): {' '.join(command)}",
                result=result,
            )
        return result

    def _ensure_enabled(self) -> None:
        if not self.settings.apm_enabled:
            raise ApmError("APM is disabled in settings")

    # ─── Version ──────────────────────────────────────────────────────────

    async def version(self) -> str:
        """Return the ``apm --version`` output (cached for the life of the service).

        Raises:
            ApmError: if the binary is unavailable or fails.
        """
        if self._version_cache is not None:
            return self._version_cache
        result = await self._run(["--version"])
        self._version_cache = result.stdout.strip() or result.stderr.strip()
        return self._version_cache

    # ─── Read-only helpers ────────────────────────────────────────────────

    async def list_dependencies(self, use_case: str) -> list[ApmDependency]:
        """Return declared dependencies for ``use_case`` merged with lockfile refs.

        Parses ``use-cases/{use_case}/apm.yml`` directly (no subprocess).
        Missing manifest returns an empty list. Only the ``dependencies.apm``
        array is walked today (mirrors the manifest format in the plan).

        Raises:
            ApmError: if the use-case directory does not exist.
        """
        uc_dir = self._use_case_dir(use_case)
        manifest_path = uc_dir / _APM_MANIFEST
        if not manifest_path.is_file():
            return []

        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ApmError(f"Failed to parse {manifest_path}: {exc}") from exc

        deps_section = manifest.get("dependencies") or {}
        raw_deps: list[str] = []
        if isinstance(deps_section, dict):
            apm_list = deps_section.get("apm") or []
            if isinstance(apm_list, list):
                raw_deps = [str(d) for d in apm_list if d]
        elif isinstance(deps_section, list):
            raw_deps = [str(d) for d in deps_section if d]

        lock_resolved = self._load_lock_resolved(uc_dir / _APM_LOCKFILE)

        out: list[ApmDependency] = []
        for spec in raw_deps:
            name, ref = _split_spec(spec)
            out.append(
                ApmDependency(
                    name=name,
                    ref=ref,
                    resolved=lock_resolved.get(name),
                    source=spec,
                )
            )
        return out

    async def list_materialised_skill_dirs(self, use_case: str) -> list[Path]:
        """Return absolute paths to APM-materialised skill directories.

        Walks ``use-cases/{use_case}/.github/skills/*/`` and yields each
        subdirectory that contains a ``SKILL.md`` file. Used by the skill
        registry to merge APM-installed skills alongside blob-backed ones.

        Raises:
            ApmError: if the use-case directory does not exist.
        """
        uc_dir = self._use_case_dir(use_case)
        skills_root = uc_dir / ".github" / "skills"
        if not skills_root.is_dir():
            return []
        result: list[Path] = []
        for entry in sorted(skills_root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                result.append(entry.resolve())
        return result

    async def list_mcp_servers(self, use_case: str) -> list[ApmMcpServer]:
        """Return MCP servers declared via APM for ``use_case``.

        The lockfile's ``mcp_configs`` section is the authoritative source
        because ``apm install`` flattens registry references into concrete
        command/args entries there. When a lockfile entry is missing we fall
        back to the raw ``dependencies.mcp`` array in ``apm.yml`` so UI can
        still show newly-added (not yet installed) servers.

        Missing manifest → empty list. Parse errors raise :class:`ApmError`.
        """
        uc_dir = self._use_case_dir(use_case)
        manifest_path = uc_dir / _APM_MANIFEST
        if not manifest_path.is_file():
            return []

        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ApmError(f"Failed to parse {manifest_path}: {exc}") from exc

        deps_section = manifest.get("dependencies") or {}
        raw_mcp: list = []
        if isinstance(deps_section, dict):
            mcp_list = deps_section.get("mcp") or []
            if isinstance(mcp_list, list):
                raw_mcp = list(mcp_list)

        lock_mcp = self._load_lock_mcp_configs(uc_dir / _APM_LOCKFILE)

        servers: list[ApmMcpServer] = []
        seen: set[str] = set()

        # Prefer lockfile entries — they're resolved and canonical.
        for name, cfg in lock_mcp.items():
            server = _mcp_entry_from_dict({"name": name, **cfg})
            if server is not None and server.name not in seen:
                servers.append(server)
                seen.add(server.name)

        # Add manifest-only entries (declared but not yet installed).
        for entry in raw_mcp:
            if isinstance(entry, str):
                # Registry alias form: ``- microsoft/markitdown``. Unresolved
                # until `apm install` runs; expose the name so the UI can
                # render a "pending install" row.
                name = entry.strip()
                if not name or name in seen:
                    continue
                servers.append(ApmMcpServer(name=name, registry=True))
                seen.add(name)
            elif isinstance(entry, dict):
                server = _mcp_entry_from_dict(entry)
                if server is not None and server.name not in seen:
                    servers.append(server)
                    seen.add(server.name)

        return servers

    async def needs_sync(self, use_case: str) -> bool:
        """Return True if ``apm install`` should run at startup for this use-case.

        True when ``apm.yml`` exists AND either ``apm_modules/`` is missing,
        or ``apm.lock.yaml`` is newer than ``apm_modules/``.
        """
        try:
            uc_dir = self._use_case_dir(use_case)
        except ApmError:
            return False
        manifest = uc_dir / _APM_MANIFEST
        if not manifest.is_file():
            return False
        modules_dir = uc_dir / _APM_MODULES_DIR
        if not modules_dir.is_dir():
            return True
        lockfile = uc_dir / _APM_LOCKFILE
        if lockfile.is_file():
            try:
                if lockfile.stat().st_mtime > modules_dir.stat().st_mtime:
                    return True
            except OSError:
                return True
        return False

    # ─── Mutating operations ──────────────────────────────────────────────

    async def install_mcp_server(
        self,
        use_case: str,
        name: str,
        *,
        transport: str = "stdio",
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ApmCommandResult:
        """Install an MCP server into ``apm.yml`` via ``apm mcp install``.

        For stdio servers the CLI syntax is::

            apm mcp install <name> -- <command> [args...]

        For remote servers (http/sse)::

            apm mcp install <name> --transport <http|sse> --url <url>

        The CLI writes the entry into ``dependencies.mcp`` of ``apm.yml``
        and configures the Copilot-CLI MCP config. We then upload the
        refreshed manifests back to blob so a subsequent registry reload
        doesn't clobber them with a stale copy.

        Raises:
            ApmError: if APM is disabled, inputs are invalid, or the
                subprocess fails.
        """
        self._ensure_enabled()
        if not name.strip():
            raise ApmError("MCP server name is required")
        uc_dir = self._use_case_dir(use_case)

        transport = transport.lower()
        cli_args: list[str] = ["mcp", "install", name]

        if transport in ("http", "sse"):
            if not url:
                raise ApmError(f"URL is required for {transport} transport")
            cli_args += ["--transport", transport, "--url", url]
        else:
            if not command:
                raise ApmError("command is required for stdio transport")
            # The CLI consumes everything after `--` as the server process
            # argv; we must place it at the end.
            cli_args.append("--")
            cli_args.append(command)
            if args:
                cli_args.extend(str(a) for a in args)

        # Environment variables: the CLI doesn't accept them via a flag in
        # 0.9.x, so pass them through the subprocess env so the resulting
        # apm.yml captures any interpolations the server expects at setup
        # time. Server-side env for RUNTIME invocation goes straight into
        # apm.yml via a post-install patch below.
        env_override = dict(env) if env else None

        async with self._lock_for(use_case):
            result = await self._run(cli_args, cwd=uc_dir, env=env_override)
            if env:
                self._patch_mcp_env(uc_dir, name, env)
            await self._upload_manifests(use_case, uc_dir)
        return result

    async def uninstall_mcp_server(self, use_case: str, name: str) -> ApmCommandResult:
        """Remove an MCP server from ``apm.yml``.

        The APM CLI doesn't have a dedicated ``mcp uninstall`` command in
        0.9.x, so we patch ``apm.yml`` directly, then run ``apm install``
        to clean up any side effects (materialised configs etc.), and
        finally upload the refreshed manifests.
        """
        self._ensure_enabled()
        uc_dir = self._use_case_dir(use_case)
        async with self._lock_for(use_case):
            self._remove_mcp_from_manifest(uc_dir, name)
            result = await self._run(["install"], cwd=uc_dir)
            await self._upload_manifests(use_case, uc_dir)
        return result

    def _patch_mcp_env(self, uc_dir: Path, name: str, env: dict[str, str]) -> None:
        """Merge an ``env`` mapping into the named MCP entry in ``apm.yml``."""
        manifest_path = uc_dir / _APM_MANIFEST
        if not manifest_path.is_file():
            return
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("Skipping env patch — failed to parse %s: %s", manifest_path, exc)
            return
        mcp_list = (data.get("dependencies") or {}).get("mcp") or []
        if not isinstance(mcp_list, list):
            return
        patched = False
        for entry in mcp_list:
            if isinstance(entry, dict) and entry.get("name") == name:
                existing = entry.get("env") or {}
                if not isinstance(existing, dict):
                    existing = {}
                existing.update({str(k): str(v) for k, v in env.items()})
                entry["env"] = existing
                patched = True
                break
        if patched:
            manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _remove_mcp_from_manifest(self, uc_dir: Path, name: str) -> None:
        """Drop the MCP entry matching ``name`` from ``apm.yml``."""
        manifest_path = uc_dir / _APM_MANIFEST
        if not manifest_path.is_file():
            raise ApmError(f"Use case '{uc_dir.name}' has no apm.yml")
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ApmError(f"Failed to parse {manifest_path}: {exc}") from exc
        deps = data.get("dependencies") or {}
        mcp_list = deps.get("mcp") or []
        if not isinstance(mcp_list, list):
            return
        new_list = []
        removed = False
        for entry in mcp_list:
            entry_name = entry if isinstance(entry, str) else (entry.get("name") if isinstance(entry, dict) else None)
            if entry_name == name:
                removed = True
                continue
            new_list.append(entry)
        if not removed:
            raise ApmError(f"MCP server '{name}' not found in apm.yml")
        deps["mcp"] = new_list
        data["dependencies"] = deps
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    async def install(
        self,
        use_case: str,
        package: str | None = None,
        ref: str | None = None,
        dev: bool = False,
    ) -> ApmCommandResult:
        """Run ``apm install`` for a use-case and sync manifests to blob.

        Args:
            use_case: Use-case name; must correspond to a directory under
                ``settings.apm_use_cases_root``.
            package: Optional package spec (e.g. ``owner/repo`` or
                ``owner/repo/subpath``). When ``None`` installs everything
                declared in ``apm.yml``.
            ref: Optional git ref appended to ``package`` as ``#{ref}``.
            dev: If True, pass ``--dev`` to install dev dependencies.

        Returns:
            The completed :class:`ApmCommandResult`.

        Raises:
            ApmError: if APM is disabled, the use-case is unknown, or the
                subprocess fails.
        """
        self._ensure_enabled()
        uc_dir = self._use_case_dir(use_case)

        args: list[str] = ["install"]
        if package:
            spec = f"{package}#{ref}" if ref else package
            args.append(spec)
        if dev:
            args.append("--dev")

        async with self._lock_for(use_case):
            result = await self._run(args, cwd=uc_dir)
            await self._upload_manifests(use_case, uc_dir)
        return result

    async def uninstall(self, use_case: str, package: str) -> ApmCommandResult:
        """Run ``apm uninstall PACKAGE`` and sync manifests to blob.

        Raises:
            ApmError: if APM is disabled, the use-case is unknown, or the
                subprocess fails.
        """
        self._ensure_enabled()
        if not package:
            raise ApmError("uninstall requires a package name")
        uc_dir = self._use_case_dir(use_case)

        async with self._lock_for(use_case):
            result = await self._run(["uninstall", package], cwd=uc_dir)
            await self._upload_manifests(use_case, uc_dir)
        return result

    async def sync(self, use_case: str) -> ApmCommandResult:
        """Idempotent resync — equivalent to ``apm install`` with no package.

        Manifests are NOT re-uploaded to blob; sync only materialises what
        ``apm.yml`` already declares, so the authoritative copy in blob is
        unchanged.

        If no ``apm.yml`` manifest exists in the use-case directory the
        operation is a no-op and returns a synthetic success result.

        Raises:
            ApmError: if APM is disabled, the use-case is unknown, or the
                subprocess fails.
        """
        self._ensure_enabled()
        uc_dir = self._use_case_dir(use_case)
        manifest = uc_dir / _APM_MANIFEST
        if not manifest.is_file():
            logger.info("apm: no %s in %s — sync is a no-op", _APM_MANIFEST, uc_dir)
            return ApmCommandResult(
                command=["apm", "install"],
                returncode=0,
                stdout="No apm.yml found — nothing to sync.",
                stderr="",
                duration_ms=0.0,
            )
        async with self._lock_for(use_case):
            return await self._run(["install"], cwd=uc_dir)

    async def update(
        self,
        use_case: str,
        package: str | None = None,
    ) -> ApmCommandResult:
        """Run ``apm update [PACKAGE]`` and upload the refreshed lockfile.

        Args:
            use_case: Use-case name.
            package: If given, update only that package; otherwise update all.

        Raises:
            ApmError: if APM is disabled, the use-case is unknown, or the
                subprocess fails.
        """
        self._ensure_enabled()
        uc_dir = self._use_case_dir(use_case)
        args: list[str] = ["update"]
        if package:
            args.append(package)

        async with self._lock_for(use_case):
            result = await self._run(args, cwd=uc_dir)
            await self._upload_manifests(use_case, uc_dir)
        return result

    # ─── Internal helpers ─────────────────────────────────────────────────

    async def _upload_manifests(self, use_case: str, uc_dir: Path) -> None:
        """Best-effort upload of apm.yml / apm.lock.yaml after a mutating op."""
        if self.blob_service is None:
            return
        for filename in (_APM_MANIFEST, _APM_LOCKFILE):
            path = uc_dir / filename
            if not path.is_file():
                continue
            try:
                content = path.read_bytes()
                await self.blob_service.upload_apm_manifest(use_case, filename, content)
            except Exception as exc:  # noqa: BLE001 — best effort, logged
                logger.warning(
                    "Failed to upload %s for use-case '%s' to blob: %s",
                    filename,
                    use_case,
                    exc,
                )

    @staticmethod
    def _load_lock_resolved(lock_path: Path) -> dict[str, str]:
        """Return ``{package_name: resolved_sha}`` from ``apm.lock.yaml`` if present."""
        if not lock_path.is_file():
            return {}
        try:
            data = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse lockfile %s: %s", lock_path, exc)
            return {}

        resolved: dict[str, str] = {}
        # Tolerate several plausible lockfile shapes — the APM lockfile format
        # is still evolving.  We look for a mapping of name→sha or a list of
        # entries with 'name' and 'resolved'/'sha'/'ref'.
        packages = data.get("packages") or data.get("dependencies") or data
        if isinstance(packages, dict):
            for name, meta in packages.items():
                if isinstance(meta, dict):
                    sha = meta.get("resolved") or meta.get("sha") or meta.get("ref")
                    if sha:
                        resolved[str(name)] = str(sha)
                elif isinstance(meta, str):
                    resolved[str(name)] = meta
        elif isinstance(packages, list):
            for entry in packages:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("package")
                sha = entry.get("resolved") or entry.get("sha") or entry.get("ref")
                if name and sha:
                    resolved[str(name)] = str(sha)
        return resolved

    @staticmethod
    def _load_lock_mcp_configs(lock_path: Path) -> dict[str, dict]:
        """Return ``{server_name: config_dict}`` from ``apm.lock.yaml`` ``mcp_configs``.

        APM writes fully-resolved MCP server configs (transport, command,
        args, url, env …) under ``mcp_configs`` after ``apm install`` runs.
        Malformed or missing lockfiles return an empty dict (callers then
        fall back to the raw ``apm.yml`` manifest).
        """
        if not lock_path.is_file():
            return {}
        try:
            data = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse lockfile %s: %s", lock_path, exc)
            return {}

        mcp = data.get("mcp_configs") or {}
        if not isinstance(mcp, dict):
            return {}
        out: dict[str, dict] = {}
        for name, cfg in mcp.items():
            if isinstance(cfg, dict):
                out[str(name)] = cfg
        return out


def _mcp_entry_from_dict(entry: dict) -> ApmMcpServer | None:
    """Convert a raw apm.yml/lockfile MCP entry into an :class:`ApmMcpServer`.

    Accepts the shape produced by ``apm mcp install`` and the richer
    lockfile form. Returns ``None`` if ``name`` is missing — skipped by
    callers so malformed entries never break the merge.
    """
    name = str(entry.get("name") or "").strip()
    if not name:
        return None

    transport = str(entry.get("transport") or "stdio").strip().lower()
    command = entry.get("command")
    raw_args = entry.get("args") or []
    args = [str(a) for a in raw_args] if isinstance(raw_args, list) else []
    url = entry.get("url")
    env_raw = entry.get("env") or {}
    env = {str(k): str(v) for k, v in env_raw.items()} if isinstance(env_raw, dict) else {}
    registry = bool(entry.get("registry"))

    return ApmMcpServer(
        name=name,
        transport=transport if transport in ("stdio", "http", "sse") else "stdio",
        command=str(command) if command else None,
        args=args,
        url=str(url) if url else None,
        env=env,
        registry=registry,
    )


def _split_spec(spec: str) -> tuple[str, str | None]:
    """Split ``owner/repo[/subpath][#ref]`` into ``(name, ref)``."""
    if "#" in spec:
        name, ref = spec.split("#", 1)
        return name.strip(), ref.strip() or None
    return spec.strip(), None
