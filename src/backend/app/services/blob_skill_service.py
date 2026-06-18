"""Blob Storage service for use-case and skill persistence.

Use-cases are stored as folder trees in Azure Blob Storage:
  use-cases/{use-case}/SYSTEM_PROMPT.md
  use-cases/{use-case}/skills/{skill-name}/SKILL.md
  use-cases/{use-case}/skills/{skill-name}/scripts/...

All skill metadata (name, description, enabled) lives in the SKILL.md YAML
frontmatter.  Each use-case has its own system prompt and skill set.

On startup the registry syncs blob → local filesystem so the Copilot SDK
can read SKILL.md files from disk.  The admin API writes back to blob.
Uses Azure Managed Identity for passwordless authentication.
"""

import contextlib
import logging
from pathlib import Path

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient

from app.config import Settings

logger = logging.getLogger(__name__)

_USE_CASES_PREFIX = "use-cases/"

# Files that live at the root of a use-case directory (alongside SYSTEM_PROMPT.md)
# and are mirrored between blob and the local filesystem.  APM-managed content
# under `apm_modules/` and materialised output under `.github/` is NEVER stored
# in blob — it is regenerated locally by `apm install`.
_APM_MANIFEST_FILES: frozenset[str] = frozenset({"apm.yml", "apm.lock.yaml"})


def _parse_account_name(conn_str: str) -> str:
    """Extract ``AccountName`` from an Azure Storage connection string.

    Args:
        conn_str: A Storage connection string (``key=value;`` pairs).

    Returns:
        The account name if present, otherwise ``"unknown"``. The account key
        is never returned so it is safe to include in logs.
    """
    for part in conn_str.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip().lower() == "accountname":
            return value.strip()
    return "unknown"


class BlobSkillService:
    """Manages use-case and skill storage in Azure Blob Storage."""

    def __init__(self, settings: Settings, local_base_dir: str = "use-cases") -> None:
        self.settings = settings
        self.local_base_dir = Path(local_base_dir)
        self._container_client: ContainerClient | None = None
        self._credential: DefaultAzureCredential | None = None

    async def initialize(self) -> None:
        """Initialize the blob container client.

        Prefers ``blob_storage_connection_string`` (e.g. Azurite) when set.
        Falls back to ``blob_storage_endpoint`` + ``DefaultAzureCredential``
        (Managed Identity / dev Entra ID). If neither is configured the
        service no-ops.
        """
        conn_str = self.settings.blob_storage_connection_string
        endpoint = self.settings.blob_storage_endpoint
        container = self.settings.blob_skills_container

        if conn_str:
            self._container_client = ContainerClient.from_connection_string(conn_str, container_name=container)
            account = _parse_account_name(conn_str)
            logger.info(
                "Blob skill service initialized (connection string, account=%s) container=%s",
                account,
                container,
            )
        elif endpoint:
            self._credential = DefaultAzureCredential()
            self._container_client = ContainerClient(
                account_url=endpoint,
                container_name=container,
                credential=self._credential,
            )
            logger.info("Blob skill service initialized — endpoint=%s container=%s", endpoint, container)
        else:
            logger.warning("Blob storage not configured — skill persistence disabled")
            return

        with contextlib.suppress(Exception):
            await self._container_client.create_container()
            # Container likely already exists

    @property
    def is_available(self) -> bool:
        return self._container_client is not None

    def local_dir(self, use_case: str) -> Path:
        """Return the local directory for a specific use-case."""
        return self.local_base_dir / use_case

    # ─── Use-case operations ──────────────────────────────────────────────

    async def list_use_cases(self) -> list[str]:
        """Return a list of use-case names (top-level folders under use-cases/)."""
        if not self._container_client:
            return []
        names: set[str] = set()
        async for blob in self._container_client.list_blobs(name_starts_with=_USE_CASES_PREFIX):
            parts = blob.name.removeprefix(_USE_CASES_PREFIX).split("/")
            if parts and parts[0]:
                names.add(parts[0])
        return sorted(names)

    async def seed_from_local(self) -> list[str]:
        """Upload each local use-case folder to blob if it isn't already present.

        Used in local/dev mode where Azurite starts empty but the repository
        ships several use-case directories under ``use-cases/``. Only folders
        that contain a ``SYSTEM_PROMPT.md`` are considered. Returns the list of
        use-case names that were newly seeded.
        """
        if not self._container_client or not self.local_base_dir.is_dir():
            return []
        existing = set(await self.list_use_cases())
        seeded: list[str] = []
        # APM-materialised output must never leak into blob.
        _skip_dir_parts = {"apm_modules", ".github", "__pycache__", ".pytest_cache", "results"}
        for uc_dir in sorted(self.local_base_dir.iterdir()):
            if not uc_dir.is_dir() or uc_dir.name in existing:
                continue
            if not (uc_dir / "SYSTEM_PROMPT.md").is_file():
                continue
            uploaded = 0
            for path in uc_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel_parts = path.relative_to(uc_dir).parts
                if any(part in _skip_dir_parts for part in rel_parts[:-1]):
                    continue
                rel = "/".join(rel_parts)
                blob_path = f"{_USE_CASES_PREFIX}{uc_dir.name}/{rel}"
                await self.upload_file(blob_path, path.read_bytes())
                uploaded += 1
            logger.info("Seeded use-case '%s' to blob (%d files)", uc_dir.name, uploaded)
            seeded.append(uc_dir.name)
        return seeded

    async def download_system_prompt(self, use_case: str) -> str | None:
        """Download the SYSTEM_PROMPT.md for a use-case."""
        content = await self._download_file(f"{_USE_CASES_PREFIX}{use_case}/SYSTEM_PROMPT.md")
        return content.decode() if content else None

    # ─── Skill read operations ────────────────────────────────────────────

    async def list_skill_names(self, use_case: str) -> list[str]:
        """Return skill names for a specific use-case."""
        if not self._container_client:
            return []
        prefix = f"{_USE_CASES_PREFIX}{use_case}/skills/"
        names: set[str] = set()
        async for blob in self._container_client.list_blobs(name_starts_with=prefix):
            parts = blob.name.removeprefix(prefix).split("/")
            if parts and parts[0]:
                names.add(parts[0])
        return sorted(names)

    async def download_skill_file(self, use_case: str, skill_name: str, relative_path: str) -> bytes | None:
        """Download a single file from a skill folder."""
        blob_path = f"{_USE_CASES_PREFIX}{use_case}/skills/{skill_name}/{relative_path}"
        return await self._download_file(blob_path)

    async def sync_to_local(self, use_case: str) -> None:
        """Download all files for a use-case from blob to local filesystem."""
        if not self._container_client:
            return

        prefix = f"{_USE_CASES_PREFIX}{use_case}/"
        local = self.local_dir(use_case)
        local.mkdir(parents=True, exist_ok=True)
        count = 0

        async for blob in self._container_client.list_blobs(name_starts_with=prefix):
            relative = blob.name.removeprefix(prefix)
            if not relative:
                continue

            blob_client = self._container_client.get_blob_client(blob.name)
            stream = await blob_client.download_blob()
            content = await stream.readall()

            local_path = local / relative
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)

            if relative.endswith("SKILL.md"):
                count += 1

        logger.info("Synced use-case '%s': %d skills to %s", use_case, count, local)

    # ─── Write operations ─────────────────────────────────────────────────

    async def upload_file(self, blob_path: str, content: bytes) -> None:
        """Upload a file to an arbitrary blob path."""
        if not self._container_client:
            return
        blob = self._container_client.get_blob_client(blob_path)
        await blob.upload_blob(content, overwrite=True)

    async def upload_skill_file(self, use_case: str, skill_name: str, relative_path: str, content: bytes) -> None:
        """Upload a single file to a skill folder within a use-case."""
        blob_path = f"{_USE_CASES_PREFIX}{use_case}/skills/{skill_name}/{relative_path}"
        await self.upload_file(blob_path, content)

    async def upload_skill_folder(self, use_case: str, skill_name: str, local_folder: Path) -> None:
        """Upload an entire local skill folder to blob."""
        if not self._container_client:
            return
        for local_path in local_folder.rglob("*"):
            if local_path.is_file():
                relative = str(local_path.relative_to(local_folder))
                await self.upload_skill_file(use_case, skill_name, relative, local_path.read_bytes())
        logger.info("Uploaded skill folder: %s/%s", use_case, skill_name)

    async def delete_skill(self, use_case: str, skill_name: str) -> None:
        """Delete all blobs for a skill within a use-case."""
        if not self._container_client:
            return
        prefix = f"{_USE_CASES_PREFIX}{use_case}/skills/{skill_name}/"
        async for blob in self._container_client.list_blobs(name_starts_with=prefix):
            blob_client = self._container_client.get_blob_client(blob.name)
            await blob_client.delete_blob()
        logger.info("Deleted skill from blob: %s/%s", use_case, skill_name)

    async def delete_skill_file(self, use_case: str, skill_name: str, file_path: str) -> None:
        """Delete a single file from a skill folder in blob storage."""
        if not self._container_client:
            return
        blob_path = f"{_USE_CASES_PREFIX}{use_case}/skills/{skill_name}/{file_path}"
        with contextlib.suppress(Exception):
            # Already deleted or doesn't exist
            blob = self._container_client.get_blob_client(blob_path)
            await blob.delete_blob()

    async def upload_mcp_config(self, use_case: str, content: bytes) -> None:
        """Upload the .mcp.json config for a use-case."""
        blob_path = f"{_USE_CASES_PREFIX}{use_case}/.mcp.json"
        await self.upload_file(blob_path, content)

    async def upload_apm_manifest(self, use_case: str, filename: str, content: bytes) -> None:
        """Upload an APM manifest (``apm.yml`` or ``apm.lock.yaml``) for a use-case.

        Only the root-level APM manifest files are synced to blob; materialised
        output under ``apm_modules/`` and ``.github/`` is regenerated locally by
        ``apm install`` and must never be persisted in blob storage.
        """
        if filename not in _APM_MANIFEST_FILES:
            raise ValueError(f"Invalid APM manifest filename '{filename}'. Allowed: {sorted(_APM_MANIFEST_FILES)}")
        blob_path = f"{_USE_CASES_PREFIX}{use_case}/{filename}"
        await self.upload_file(blob_path, content)

    async def use_case_exists(self, use_case: str) -> bool:
        """Return True if a use-case already exists in blob or on local disk."""
        if self._container_client and use_case in await self.list_use_cases():
            return True
        local = self.local_dir(use_case)
        return local.is_dir() and (local / "SYSTEM_PROMPT.md").exists()

    async def create_use_case(
        self,
        use_case: str,
        *,
        system_prompt_md: str,
        mcp_json: str,
        apm_yml: str,
        overwrite: bool = False,
    ) -> list[str]:
        """Create a new use-case from its three core persona files.

        Writes ``SYSTEM_PROMPT.md``, ``.mcp.json`` and ``apm.yml`` to blob
        storage (when configured) and always mirrors them to the local
        filesystem so a freshly constructed :class:`SkillRegistry` can read
        them immediately — both via the blob→local sync path and the
        local-fallback path.

        Args:
            use_case: The (already validated) use-case slug.
            system_prompt_md: Full SYSTEM_PROMPT.md content incl. frontmatter.
            mcp_json: Serialized ``.mcp.json`` (Copilot MCP config shape).
            apm_yml: Serialized ``apm.yml`` APM manifest.
            overwrite: When False and the use-case exists, raise FileExistsError.

        Returns:
            The list of relative file paths that were written.
        """
        if not overwrite and await self.use_case_exists(use_case):
            raise FileExistsError(use_case)

        files: dict[str, bytes] = {
            "SYSTEM_PROMPT.md": system_prompt_md.encode("utf-8"),
            ".mcp.json": mcp_json.encode("utf-8"),
            "apm.yml": apm_yml.encode("utf-8"),
        }

        local_dir = self.local_dir(use_case)
        local_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (local_dir / name).write_bytes(content)

        if self._container_client:
            await self.upload_file(f"{_USE_CASES_PREFIX}{use_case}/SYSTEM_PROMPT.md", files["SYSTEM_PROMPT.md"])
            await self.upload_mcp_config(use_case, files[".mcp.json"])
            await self.upload_apm_manifest(use_case, "apm.yml", files["apm.yml"])

        logger.info("Created use-case '%s' (%d files, blob=%s)", use_case, len(files), self.is_available)
        return [f"{_USE_CASES_PREFIX}{use_case}/{name}" for name in files]

    # ─── Internal helpers ─────────────────────────────────────────────────

    async def download_blob(self, blob_path: str) -> bytes | None:
        """Download a blob by its full path. Returns None if not found."""
        return await self._download_file(blob_path)

    async def _download_file(self, blob_path: str) -> bytes | None:
        """Download a single blob by path."""
        if not self._container_client:
            return None
        try:
            blob = self._container_client.get_blob_client(blob_path)
            stream = await blob.download_blob()
            return await stream.readall()
        except Exception:
            return None

    async def close(self) -> None:
        """Clean up resources."""
        if self._container_client:
            await self._container_client.close()
        if self._credential:
            await self._credential.close()
