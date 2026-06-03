"""Eval storage — scenarios, runs, results in blob (with local fallback).

Layout (in the ``skills`` container, alongside existing use-case content):

    use-cases/{use_case}/evals/eval_config.json
    use-cases/{use_case}/evals/scenarios/{name}.json
    use-cases/{use_case}/evals/runs/{run_id}/_meta.json
    use-cases/{use_case}/evals/runs/{run_id}/run_results.jsonl
    use-cases/{use_case}/evals/runs/{run_id}/eval_report.json

A repository-local fallback under ``use-cases/{use_case}/evals/`` is used when
blob storage is not configured (local-mode dev without Azurite). Scenarios
checked into Git seed the blob via the existing ``seed_from_local`` flow in
``BlobSkillService`` because they live under the same ``use-cases/`` tree.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import EvalRun, EvalScenario
from app.services.blob_skill_service import BlobSkillService

logger = logging.getLogger(__name__)

_USE_CASES_PREFIX = "use-cases/"
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")


def _evals_root(use_case: str) -> str:
    return f"{_USE_CASES_PREFIX}{use_case}/evals"


def _scenarios_prefix(use_case: str) -> str:
    return f"{_evals_root(use_case)}/scenarios/"


def _runs_prefix(use_case: str) -> str:
    return f"{_evals_root(use_case)}/runs/"


def _validate_name(name: str) -> str:
    if not _NAME_PATTERN.match(name):
        raise ValueError(f"Invalid scenario name '{name}'. Must match {_NAME_PATTERN.pattern}")
    return name


class EvalStorage:
    """Read/write scenarios and runs to blob, falling back to the local repo."""

    def __init__(self, blob: BlobSkillService, local_base_dir: str | Path = "use-cases") -> None:
        self._blob = blob
        self._local_base = Path(local_base_dir)

    # ── Local helpers ────────────────────────────────────────────────────

    def _local_dir(self, use_case: str) -> Path:
        return self._local_base / use_case / "evals"

    def _local_scenarios_dir(self, use_case: str) -> Path:
        return self._local_dir(use_case) / "scenarios"

    def _local_runs_dir(self, use_case: str) -> Path:
        return self._local_dir(use_case) / "results" / "runs"

    # ── Scenarios ────────────────────────────────────────────────────────

    async def list_scenarios(self, use_case: str) -> list[EvalScenario]:
        """Return all scenarios for a use-case.

        Source priority:
          1. blob (if available)
          2. local filesystem (always merged in for repo-shipped scenarios)
        """
        seen: dict[str, EvalScenario] = {}

        # 1) local first — these ship with the repo
        local_dir = self._local_scenarios_dir(use_case)
        if local_dir.is_dir():
            for p in sorted(local_dir.glob("*.json")):
                try:
                    seen[p.stem] = EvalScenario.model_validate_json(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Failed to load local scenario %s: %s", p, exc)

        # 2) blob overrides — UI-edited scenarios win
        if self._blob.is_available:
            prefix = _scenarios_prefix(use_case)
            try:
                client = self._blob._container_client  # noqa: SLF001 — internal access by design
                if client is not None:
                    async for blob in client.list_blobs(name_starts_with=prefix):
                        if not blob.name.endswith(".json"):
                            continue
                        raw = await self._blob.download_blob(blob.name)
                        if not raw:
                            continue
                        try:
                            scenario = EvalScenario.model_validate_json(raw.decode("utf-8"))
                            seen[scenario.name] = scenario
                        except Exception as exc:
                            logger.warning("Failed to load blob scenario %s: %s", blob.name, exc)
            except Exception:
                logger.exception("Failed to list blob scenarios for %s", use_case)

        return sorted(seen.values(), key=lambda s: s.name)

    async def get_scenario(self, use_case: str, name: str) -> EvalScenario | None:
        _validate_name(name)
        # blob first (latest edits), then local fallback
        if self._blob.is_available:
            raw = await self._blob.download_blob(f"{_scenarios_prefix(use_case)}{name}.json")
            if raw:
                try:
                    return EvalScenario.model_validate_json(raw.decode("utf-8"))
                except Exception as exc:
                    logger.warning("Bad scenario in blob %s: %s", name, exc)

        local_path = self._local_scenarios_dir(use_case) / f"{name}.json"
        if local_path.is_file():
            try:
                return EvalScenario.model_validate_json(local_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Bad scenario in repo %s: %s", local_path, exc)
        return None

    async def upsert_scenario(self, use_case: str, scenario: EvalScenario) -> None:
        _validate_name(scenario.name)
        payload = scenario.model_dump_json(indent=2).encode("utf-8")
        if self._blob.is_available:
            await self._blob.upload_file(f"{_scenarios_prefix(use_case)}{scenario.name}.json", payload)
        # Always mirror to local filesystem so devs see the file in their tree
        local_dir = self._local_scenarios_dir(use_case)
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / f"{scenario.name}.json").write_bytes(payload)

    async def delete_scenario(self, use_case: str, name: str) -> bool:
        _validate_name(name)
        removed = False
        if self._blob.is_available and self._blob._container_client is not None:  # noqa: SLF001
            try:
                client = self._blob._container_client.get_blob_client(  # noqa: SLF001
                    f"{_scenarios_prefix(use_case)}{name}.json"
                )
                await client.delete_blob()
                removed = True
            except Exception:
                # already gone or never existed
                pass
        local_path = self._local_scenarios_dir(use_case) / f"{name}.json"
        if local_path.is_file():
            local_path.unlink()
            removed = True
        return removed

    # ── Eval config ──────────────────────────────────────────────────────

    async def get_eval_config(self, use_case: str) -> dict[str, Any]:
        # Blob takes precedence, then local file, then default
        for source in ("blob", "local"):
            if source == "blob" and self._blob.is_available:
                raw = await self._blob.download_blob(f"{_evals_root(use_case)}/eval_config.json")
                if raw:
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except Exception:
                        continue
            if source == "local":
                local = self._local_dir(use_case) / "eval_config.json"
                if local.is_file():
                    try:
                        return json.loads(local.read_text(encoding="utf-8"))
                    except Exception:
                        continue
        return {
            "evaluation": {
                "evaluators": [
                    "Relevance",
                    "Coherence",
                    "TaskAdherence",
                    "IntentResolution",
                    "ToolCallAccuracy",
                ],
                "judge_model_env": "EVAL_MODEL",
                "judge_model_default": "gpt-4.1",
            }
        }

    # ── Runs ─────────────────────────────────────────────────────────────

    async def save_run(self, run: EvalRun) -> None:
        run.updated_at = datetime.now(UTC)
        payload = run.model_dump_json(indent=2).encode("utf-8")
        if self._blob.is_available:
            await self._blob.upload_file(f"{_runs_prefix(run.use_case)}{run.run_id}/_meta.json", payload)
        local_dir = self._local_runs_dir(run.use_case) / run.run_id
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "_meta.json").write_bytes(payload)

    async def load_run(self, use_case: str, run_id: str) -> EvalRun | None:
        if self._blob.is_available:
            raw = await self._blob.download_blob(f"{_runs_prefix(use_case)}{run_id}/_meta.json")
            if raw:
                try:
                    return EvalRun.model_validate_json(raw.decode("utf-8"))
                except Exception as exc:
                    logger.warning("Bad run meta blob %s: %s", run_id, exc)

        local = self._local_runs_dir(use_case) / run_id / "_meta.json"
        if local.is_file():
            try:
                return EvalRun.model_validate_json(local.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Bad run meta locally %s: %s", local, exc)
        return None

    async def list_runs(self, use_case: str, limit: int = 50) -> list[EvalRun]:
        ids: set[str] = set()
        if self._blob.is_available and self._blob._container_client is not None:  # noqa: SLF001
            prefix = _runs_prefix(use_case)
            try:
                async for blob in self._blob._container_client.list_blobs(name_starts_with=prefix):  # noqa: SLF001
                    rel = blob.name.removeprefix(prefix)
                    parts = rel.split("/", 1)
                    if parts and parts[0]:
                        ids.add(parts[0])
            except Exception:
                logger.exception("Failed to list runs for %s", use_case)

        local_runs_dir = self._local_runs_dir(use_case)
        if local_runs_dir.is_dir():
            for child in local_runs_dir.iterdir():
                if child.is_dir() and (child / "_meta.json").is_file():
                    ids.add(child.name)

        runs: list[EvalRun] = []
        for run_id in ids:
            run = await self.load_run(use_case, run_id)
            if run is not None:
                runs.append(run)
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    async def append_jsonl(self, use_case: str, run_id: str, record: dict[str, Any]) -> None:
        line = json.dumps(record, default=str) + "\n"
        local_dir = self._local_runs_dir(use_case) / run_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / "run_results.jsonl"
        with local_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        if self._blob.is_available:
            # Blob append: re-upload the whole file (small per-run, no contention)
            content = local_path.read_bytes()
            await self._blob.upload_file(f"{_runs_prefix(use_case)}{run_id}/run_results.jsonl", content)

    async def write_report(self, use_case: str, run_id: str, report: dict[str, Any]) -> None:
        payload = json.dumps(report, indent=2, default=str).encode("utf-8")
        if self._blob.is_available:
            await self._blob.upload_file(f"{_runs_prefix(use_case)}{run_id}/eval_report.json", payload)
        local_dir = self._local_runs_dir(use_case) / run_id
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "eval_report.json").write_bytes(payload)
