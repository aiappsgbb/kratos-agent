"""Eval service — scenario generation and eval run orchestration.

Two public entry points:
  1. ``generate_scenarios`` — LLM-assisted scenario drafting (no persistence)
  2. ``start_run``          — kick off a background eval run (invoke ± score)

Scoring (FOUNDRY mode) uses ``azure-ai-evaluation`` evaluators lazily imported
so the module loads cleanly even when the package is not installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openai
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from app.config import Settings
from app.models import (
    EvalMode,
    EvalRun,
    EvalRunStatus,
    EvalScenario,
    FoundryEvalSummary,
    ScenarioResult,
)
from app.services.eval_storage import EvalStorage
from app.services.foundry_agent_proxy import FoundryAgentProxy
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_INTERNAL_TOOLS: frozenset[str] = frozenset({"report_intent", "skill", "sql", "ask_user"})
_MCP_PREFIX = "mcp-tools-"

# Use-case → industry canon mapping (FSI covers insurance/banking/wealth)
_FSI_USE_CASES = {"insurance", "retail-banking", "wealth-management"}
_CANON_BASE = Path("/Users/ricchi/Repos/awesome-gbb/skills/threadlight-demo-data-factory/references")

# Warmup parameters (tuned per foundry-evals skill guidance)
_WARMUP_ATTEMPTS = 6
_WARMUP_BACKOFF_S = 5.0

# Request timeout for the Foundry OpenAI client (seconds)
# Bumped to 300s — complex multi-tool scenarios (PDF report generation, multi-step
# triage flows) routinely exceed 120s; gateway throttle bursts also push tail latency.
_REQUEST_TIMEOUT = 300.0

# Scenario count cap
_SCENARIO_COUNT_MAX = 24


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _load_canon(use_case: str) -> str:
    """Return the industry realism canon text, or empty string if absent."""
    industry = "fsi" if use_case in _FSI_USE_CASES else None
    if industry:
        canon_path = _CANON_BASE / f"{industry}.md"
        if canon_path.is_file():
            try:
                return canon_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("Could not read canon %s: %s", canon_path, exc)
    return ""


def _build_generator_system_prompt(
    use_case: str,
    registry: SkillRegistry,
    count: int,
    instructions: str,
) -> str:
    """Build the system prompt for the LLM scenario generator."""
    skill_bullets = "\n".join(
        f"- **{s.name}** (enabled={s.enabled}): {s.description}" for s in registry.skills.values()
    )

    canon = _load_canon(use_case)
    canon_section = f"\n\n## Industry Realism Canon\n\n{canon}" if canon else ""

    extra = f"\n\n## Extra Instructions\n\n{instructions}" if instructions.strip() else ""

    schema_hint = json.dumps(
        {
            "scenarios": [
                {
                    "name": "lowercase-hyphenated-slug",
                    "category": "standard | edge_case | error_handling | boundary | compliance",
                    "description": "What this scenario tests",
                    "input_message": "The user message sent to the agent",
                    "input_data": {},
                    "expected_behavior": "Plain-language expected behavior",
                    "expected_tool_calls": ["tool_name_without_mcp_prefix"],
                    "evaluators": ["Relevance", "Coherence", "TaskAdherence", "IntentResolution", "ToolCallAccuracy"],
                }
            ]
        },
        indent=2,
    )

    return f"""You are an expert QA engineer generating evaluation scenarios for an AI agent.

## Agent System Prompt

{registry.system_prompt or "(not available)"}

## Available Skills

{skill_bullets or "(none registered)"}
{canon_section}{extra}

## Task

Generate exactly {count} distinct evaluation scenarios that cover happy-path,
edge-case, error-handling, boundary, and compliance categories.  Make the
scenarios realistic and grounded in the domain.

Respond with a single JSON object matching this exact schema — no prose,
no markdown fencing, just the JSON:

{schema_hint}

Rules:
- `name` must be a unique lowercase-hyphenated slug (max 80 chars).
- `category` must be one of: standard, edge_case, error_handling, boundary, compliance.
- `input_message` must be a natural user message (1-3 sentences).
- `expected_tool_calls` must NOT include the `mcp-tools-` prefix.
- Include all five evaluator names in `evaluators`.
- Vary the categories; do not produce all `standard` scenarios.
"""


def _build_foundry_oai_client(settings: Settings) -> Any:
    """Return an AIProjectClient-derived OpenAI client bound to the hosted agent."""
    from azure.ai.projects import AIProjectClient

    endpoint = settings.eval_foundry_project_endpoint or settings.foundry_project_endpoint
    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    return project.get_openai_client(agent_name=settings.foundry_agent_name)


def _build_model_config(settings: Settings) -> dict[str, Any]:
    """Return the model config dict for azure-ai-evaluation evaluators."""
    azure_endpoint = settings.foundry_endpoint.rstrip("/")
    # Prefer the actual deployment name (e.g. ``gpt-54``) — ``eval_model``'s
    # default of ``gpt-4.1`` is only used if the runtime model isn't set.
    model = settings.foundry_model_deployment or settings.eval_model or "gpt-4.1"
    api_key = os.environ.get("FOUNDRY_API_KEY", "").strip()
    config: dict[str, Any] = {
        "azure_endpoint": azure_endpoint,
        "azure_deployment": model,
        "api_version": "2024-12-01-preview",
    }
    if api_key:
        config["api_key"] = api_key
    else:
        config["credential"] = DefaultAzureCredential()
    return config


def _apply_validate_model_config_patch() -> None:
    """Patch azure-ai-evaluation's validate_model_config.

    Two reasons this must run on ALL Python versions:

    1. Python 3.13 changed ``isinstance(v, typing.Any)`` to raise TypeError;
       this breaks the credential-field check inside azure-ai-evaluation.
    2. azure-ai-evaluation's TypedDict for AzureOpenAIModelConfiguration does
       NOT accept ``credential`` (only ``api_key`` / ``api_version``), so a
       managed-identity-flavored dict fails strict validation on 3.11 too.

    The patch short-circuits validation when the config already has
    ``azure_endpoint`` — the only field we actually need to be well-formed.
    """
    try:
        import azure.ai.evaluation._common.utils as _eval_utils
        import azure.ai.evaluation._evaluators._common._base_prompty_eval as _bpe

        _orig = _eval_utils.validate_model_config

        def _patched(config: Any) -> Any:
            if isinstance(config, dict) and "azure_endpoint" in config:
                return config
            return _orig(config)

        _eval_utils.validate_model_config = _patched
        _bpe.validate_model_config = _patched
    except Exception:
        pass  # graceful degradation if internals change


def _extract_response_text(response: Any) -> str:
    """Extract the assistant text from an OpenAI Responses API response."""
    text: str = getattr(response, "output_text", "") or ""
    if not text and hasattr(response, "output"):
        for item in response.output:
            if getattr(item, "type", "") == "message":
                for content in getattr(item, "content", []):
                    text += getattr(content, "text", "")
    return text


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    """Extract tool calls from an OpenAI Responses API response."""
    calls: list[dict[str, Any]] = []
    if not hasattr(response, "output"):
        return calls
    for item in response.output:
        if getattr(item, "type", "") == "function_call":
            raw_args = getattr(item, "arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}
            result_text = ""
            calls.append(
                {
                    "name": getattr(item, "name", ""),
                    "arguments": args,
                    "result": result_text,
                }
            )
        elif getattr(item, "type", "") == "function_call_output":
            # Pair results back to the most recent call with matching call_id
            call_id = getattr(item, "call_id", "")
            output_val = getattr(item, "output", "")
            for call in reversed(calls):
                if call.get("_call_id") == call_id:
                    call["result"] = output_val
                    break
    # Strip internal _call_id bookkeeping
    for call in calls:
        call.pop("_call_id", None)
    return calls


def _filter_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove internal GHCP SDK tools and normalise MCP prefix."""
    filtered: list[dict[str, Any]] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if name in _INTERNAL_TOOLS:
            continue
        if name and not name.startswith(_MCP_PREFIX):
            tc = {**tc, "name": _MCP_PREFIX + name}
        filtered.append(tc)
    return filtered


def _build_tool_definitions(expected_tool_calls: list[str]) -> list[dict[str, Any]]:
    """Build the tool_definitions list for evaluators from expected tool names.

    ToolCallAccuracyEvaluator requires each definition to carry a ``parameters``
    field (JSON Schema shape). We don't know the real schema of expected tools,
    so emit an empty-object schema which matches the evaluator's contract while
    staying generic.
    """
    filtered = [t for t in expected_tool_calls if t not in _INTERNAL_TOOLS]
    return [
        {
            "name": t if t.startswith(_MCP_PREFIX) else _MCP_PREFIX + t,
            "description": f"Skill: {t}",
            "parameters": {"type": "object", "properties": {}},
        }
        for t in filtered
    ]


def _apply_openai_max_tokens_patch() -> None:
    """Translate ``max_tokens`` → ``max_completion_tokens`` on OpenAI calls.

    gpt-5.x / o1-* models reject ``max_tokens`` and require the new
    ``max_completion_tokens`` parameter. azure-ai-evaluation's prompty
    templates still hardcode ``max_tokens``, so we monkey-patch the OpenAI
    chat-completions ``create`` method to rewrite the parameter at call time.
    Idempotent.
    """
    try:
        from openai.resources.chat import completions as _cc  # noqa: PLC0415

        for cls_name in ("Completions", "AsyncCompletions"):
            cls = getattr(_cc, cls_name, None)
            if cls is None:
                continue
            orig = cls.create
            if getattr(orig, "_kratos_max_tokens_patched", False):
                continue

            if cls_name == "AsyncCompletions":

                async def _patched_async(self, *args, _orig=orig, **kwargs):  # type: ignore[no-untyped-def]
                    if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
                        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    return await _orig(self, *args, **kwargs)

                _patched_async._kratos_max_tokens_patched = True  # type: ignore[attr-defined]
                cls.create = _patched_async  # type: ignore[assignment]
            else:

                def _patched_sync(self, *args, _orig=orig, **kwargs):  # type: ignore[no-untyped-def]
                    if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
                        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    return _orig(self, *args, **kwargs)

                _patched_sync._kratos_max_tokens_patched = True  # type: ignore[attr-defined]
                cls.create = _patched_sync  # type: ignore[assignment]
    except Exception:
        pass


# ── EvalService ───────────────────────────────────────────────────────────────


class EvalService:
    """Orchestrates eval scenario generation and run execution."""

    def __init__(
        self,
        settings: Settings,
        storage: EvalStorage,
        registries: dict[str, SkillRegistry],
        foundry_proxy: FoundryAgentProxy | None = None,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._registries = registries
        self._foundry_proxy = foundry_proxy
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    # ── Hosted-agent invocation helper (uses Invocations protocol via FoundryAgentProxy) ──

    async def _invoke_hosted_agent(
        self,
        message: str,
        conversation_id: str,
        use_case: str,
        run_id: str | None = None,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> tuple[str, list[dict[str, Any]], str | None]:
        """Invoke the hosted agent once and aggregate the SSE stream.

        Returns ``(response_text, tool_calls, error_message)``. ``error_message``
        is non-empty when the agent stream emitted an error event.
        """
        if self._foundry_proxy is None:
            raise RuntimeError("EvalService: foundry_proxy is not configured — cannot invoke hosted agent.")

        chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        error_msg: str | None = None

        async def _drain() -> None:
            nonlocal error_msg
            async for ev in self._foundry_proxy.invoke(
                message=message,
                conversation_id=conversation_id,
                use_case=use_case,
                eval_run_id=run_id,
            ):
                etype = ev.get("event") or ev.get("type") or ""
                data = ev.get("data") or {}
                if etype == "content":
                    txt = data.get("content") or data.get("text") or ""
                    if txt:
                        chunks.append(str(txt))
                elif etype == "tool_call":
                    tool_calls.append(data if isinstance(data, dict) else {"raw": str(data)})
                elif etype == "error":
                    error_msg = str(data.get("message") or data)

        try:
            await asyncio.wait_for(_drain(), timeout=timeout)
        except TimeoutError:
            error_msg = error_msg or f"Hosted agent invocation timed out after {timeout}s"

        return "".join(chunks), tool_calls, error_msg

    # ── Public API ────────────────────────────────────────────────────────

    async def generate_scenarios(
        self,
        use_case: str,
        count: int,
        instructions: str = "",
    ) -> list[EvalScenario]:
        """Generate ``count`` evaluation scenarios for ``use_case`` via LLM."""
        count = min(count, _SCENARIO_COUNT_MAX)
        registry = self._registries.get(use_case) or SkillRegistry(use_case=use_case)
        system_prompt = _build_generator_system_prompt(use_case, registry, count, instructions)

        azure_endpoint = self._settings.foundry_endpoint.rstrip("/")
        model = self._settings.foundry_model_deployment or self._settings.eval_model or "gpt-4.1"
        api_key = os.environ.get("FOUNDRY_API_KEY", "").strip()

        if api_key:
            oai_client = openai.AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version="2024-12-01-preview",
            )
        else:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default",
            )
            oai_client = openai.AzureOpenAI(
                azure_endpoint=azure_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-12-01-preview",
            )

        logger.info("Generating %d scenarios for use-case '%s'", count, use_case)
        try:
            completion = oai_client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
        except Exception as exc:
            logger.exception("Scenario generation LLM call failed for '%s'", use_case)
            raise RuntimeError(f"Scenario generation failed: {exc}") from exc

        raw = completion.choices[0].message.content or ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Generator returned non-JSON: %s", raw[:200])
            raise RuntimeError(f"LLM did not return valid JSON: {exc}") from exc

        raw_scenarios = parsed.get("scenarios", [])
        scenarios: list[EvalScenario] = []
        for item in raw_scenarios:
            try:
                scenarios.append(EvalScenario.model_validate(item))
            except Exception as exc:
                logger.warning("Skipping malformed scenario item: %s — %s", item, exc)

        if not scenarios:
            raise RuntimeError("LLM generated zero valid scenarios — check the model output.")

        logger.info("Generated %d scenarios for '%s'", len(scenarios), use_case)
        return scenarios

    async def start_run(
        self,
        use_case: str,
        mode: EvalMode,
        scenario_names: list[str] | None,
        started_by: str = "",
    ) -> EvalRun:
        """Create an EvalRun record, persist it, and kick off the background task."""
        run_id = uuid.uuid4().hex

        # Resolve scenario list
        if scenario_names:
            scenarios = scenario_names
        else:
            all_scenarios = await self._storage.list_scenarios(use_case)
            scenarios = [s.name for s in all_scenarios]

        now = _now()
        run = EvalRun(
            run_id=run_id,
            use_case=use_case,
            mode=mode,
            status=EvalRunStatus.PENDING,
            scenarios=scenarios,
            created_at=now,
            updated_at=now,
            started_by=started_by,
        )
        await self._storage.save_run(run)

        task = asyncio.create_task(
            self._execute_run(run),
            name=f"eval-{use_case}-{run_id}",
        )
        self._tasks[(use_case, run_id)] = task
        task.add_done_callback(lambda t: self._tasks.pop((use_case, run_id), None))

        logger.info("Started eval run %s for '%s' (mode=%s, %d scenarios)", run_id, use_case, mode, len(scenarios))
        return run

    async def get_run(self, use_case: str, run_id: str) -> EvalRun | None:
        return await self._storage.load_run(use_case, run_id)

    async def list_runs(self, use_case: str, limit: int = 50) -> list[EvalRun]:
        return await self._storage.list_runs(use_case, limit)

    async def shutdown(self) -> None:
        """Cancel all in-flight eval tasks gracefully."""
        tasks = list(self._tasks.values())
        if not tasks:
            return
        logger.info("Cancelling %d in-flight eval tasks", len(tasks))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # ── Background execution ──────────────────────────────────────────────

    async def _execute_run(self, run: EvalRun) -> None:
        """Full eval run: warmup → invoke → (score) → report."""
        run_id = run.run_id

        try:
            await self._do_execute_run(run)
        except asyncio.CancelledError:
            logger.info("Eval run %s cancelled", run_id)
            run.status = EvalRunStatus.FAILED
            run.error = "Cancelled"
            await self._storage.save_run(run)
        except Exception as exc:
            logger.exception("Eval run %s failed", run_id)
            run.status = EvalRunStatus.FAILED
            run.error = str(exc)
            await self._storage.save_run(run)

    async def _do_execute_run(self, run: EvalRun) -> None:
        use_case = run.use_case
        run_id = run.run_id
        settings = self._settings

        # ── Phase 0: resolve scenarios ────────────────────────────────────
        all_stored = await self._storage.list_scenarios(use_case)
        stored_map: dict[str, EvalScenario] = {s.name: s for s in all_stored}
        scenarios_to_run: list[EvalScenario] = []
        for name in run.scenarios:
            sc = stored_map.get(name)
            if sc is None:
                logger.warning("Scenario '%s' not found in storage — skipping", name)
                continue
            scenarios_to_run.append(sc)

        if not scenarios_to_run:
            raise RuntimeError("No valid scenarios found for this run.")

        # ── Phase 1: INVOKING ─────────────────────────────────────────────
        run.status = EvalRunStatus.INVOKING
        await self._storage.save_run(run)

        # Build Foundry OpenAI client (used later for scoring evaluators in FOUNDRY mode)
        _oai = _build_foundry_oai_client(settings) if run.mode == EvalMode.FOUNDRY else None

        # Warmup loop — handles scale-from-zero hosted agents (uses Invocations protocol)
        logger.info("[eval %s] warmup start (max %d attempts)", run_id, _WARMUP_ATTEMPTS)
        backoff = _WARMUP_BACKOFF_S
        for attempt in range(1, _WARMUP_ATTEMPTS + 1):
            try:
                wtext, _, werr = await self._invoke_hosted_agent(
                    message="ping",
                    conversation_id=f"warmup-{run_id}-{attempt}",
                    use_case=use_case,
                    run_id=run_id,
                    timeout=60.0,
                )
                if werr:
                    logger.warning("[eval %s] warmup attempt=%d error: %s", run_id, attempt, werr[:160])
                elif wtext:
                    logger.info("[eval %s] warmup READY (chars=%d)", run_id, len(wtext))
                    break
                else:
                    logger.warning("[eval %s] warmup attempt=%d empty response", run_id, attempt)
            except Exception as exc:
                logger.warning("[eval %s] warmup attempt=%d exc: %s", run_id, attempt, str(exc)[:160])
            if attempt < _WARMUP_ATTEMPTS:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        else:
            raise RuntimeError(f"Hosted agent failed to warm up after {_WARMUP_ATTEMPTS} attempts.")

        # Sequential invocation
        total = len(scenarios_to_run)
        for idx, scenario in enumerate(scenarios_to_run):
            t_start = time.monotonic()
            try:
                resp_text, raw_tool_calls, err = await self._invoke_hosted_agent(
                    message=scenario.input_message,
                    conversation_id=f"eval-{run_id}-{scenario.name}",
                    use_case=use_case,
                    run_id=run_id,
                    timeout=_REQUEST_TIMEOUT,
                )
                # Retry once on empty response (and no explicit error)
                if not resp_text and not err:
                    await asyncio.sleep(3)
                    resp_text, raw_tool_calls, err = await self._invoke_hosted_agent(
                        message=scenario.input_message,
                        conversation_id=f"eval-{run_id}-{scenario.name}-retry",
                        use_case=use_case,
                        run_id=run_id,
                        timeout=_REQUEST_TIMEOUT,
                    )
                duration_ms = int((time.monotonic() - t_start) * 1000)

                if err and not resp_text:
                    result = ScenarioResult(
                        scenario=scenario.name,
                        query=scenario.input_message,
                        status="error",
                        error=err,
                        duration_ms=duration_ms,
                    )
                else:
                    result = ScenarioResult(
                        scenario=scenario.name,
                        query=scenario.input_message,
                        response=resp_text,
                        tool_calls=raw_tool_calls,
                        status="completed",
                        duration_ms=duration_ms,
                    )
            except Exception as exc:
                duration_ms = int((time.monotonic() - t_start) * 1000)
                logger.warning("[eval %s] scenario '%s' failed: %s", run_id, scenario.name, exc)
                result = ScenarioResult(
                    scenario=scenario.name,
                    query=scenario.input_message,
                    status="error",
                    error=str(exc),
                    duration_ms=duration_ms,
                )

            run.results.append(result)
            run.progress = f"{idx + 1}/{total}"

            await self._storage.append_jsonl(
                use_case,
                run_id,
                {
                    "scenario": result.scenario,
                    "query": result.query,
                    "response": result.response,
                    "tool_calls": result.tool_calls,
                    "status": result.status,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                },
            )

            # Persist run meta periodically (every 5 scenarios or at end)
            if (idx + 1) % 5 == 0 or (idx + 1) == total:
                await self._storage.save_run(run)

            # Pace invocations per foundry-evals guidance
            if idx < total - 1:
                await asyncio.sleep(5)

        # ── Phase 2: SCORING (both validation + foundry modes) ──────────
        # The mode label is purely a pacing/strictness hint — both flows
        # benefit from per-evaluator scores. Without this, results[].scores
        # is empty and the eval panel can't render per-evaluator bars.
        # Scoring is best-effort enrichment; never let a scoring failure
        # mark the whole run as failed when invocations succeeded.
        try:
            await self._score_run(run, scenarios_to_run, use_case, run_id)
        except Exception as exc:
            logger.exception("[eval %s] scoring failed (invocations OK)", run_id)
            run.error = f"Scoring failed: {exc}"

        # ── Phase 3: Write report ─────────────────────────────────────────
        report = self._build_report(run, use_case)
        await self._storage.write_report(use_case, run_id, report)

        run.status = EvalRunStatus.COMPLETED
        run.progress = f"{total}/{total}"
        await self._storage.save_run(run)
        logger.info("[eval %s] COMPLETED (%d scenarios)", run_id, total)

    async def _score_run(
        self,
        run: EvalRun,
        scenarios: list[EvalScenario],
        use_case: str,
        run_id: str,
    ) -> None:
        """Score invocation results with azure-ai-evaluation evaluators."""
        run.status = EvalRunStatus.SCORING
        await self._storage.save_run(run)
        logger.info("[eval %s] scoring %d results", run_id, len(run.results))

        # Lazy import — azure-ai-evaluation may not be installed
        _apply_validate_model_config_patch()
        _apply_openai_max_tokens_patch()
        try:
            from azure.ai.evaluation import (  # noqa: PLC0415
                CoherenceEvaluator,
                IntentResolutionEvaluator,
                RelevanceEvaluator,
                TaskAdherenceEvaluator,
                ToolCallAccuracyEvaluator,
            )
        except ImportError as exc:
            logger.error("[eval %s] azure-ai-evaluation not installed: %s — skipping scoring", run_id, exc)
            return

        model_config = _build_model_config(self._settings)
        # Lazy per-evaluator instantiation — if one evaluator class fails to
        # construct (e.g. version-specific validation), the rest still run.
        evaluator_classes = {
            "TaskAdherence": TaskAdherenceEvaluator,
            "IntentResolution": IntentResolutionEvaluator,
            "Coherence": CoherenceEvaluator,
            "Relevance": RelevanceEvaluator,
            "ToolCallAccuracy": ToolCallAccuracyEvaluator,
        }
        evaluators: dict[str, Any] = {}
        for name, cls in evaluator_classes.items():
            try:
                evaluators[name] = cls(model_config=model_config)
            except Exception as exc:
                logger.warning("[eval %s] evaluator %s init failed: %s", run_id, name, exc)
        if not evaluators:
            logger.error("[eval %s] no evaluators could be instantiated", run_id)
            return

        scenario_map: dict[str, EvalScenario] = {s.name: s for s in scenarios}
        criteria_totals: dict[str, dict[str, int]] = {}

        for result in run.results:
            if result.status == "error":
                continue

            sc = scenario_map.get(result.scenario)
            expected_behavior = sc.expected_behavior if sc else ""
            expected_tools = sc.expected_tool_calls if sc else []

            eval_query = f"{result.query}\n\nExpected: {expected_behavior}" if expected_behavior else result.query

            filtered_tool_calls = _filter_tool_calls(result.tool_calls)
            tool_defs = _build_tool_definitions(expected_tools)

            scores: dict[str, dict[str, Any]] = {}
            for eval_name, evaluator in evaluators.items():
                try:
                    kwargs: dict[str, Any] = {
                        "query": eval_query,
                        "response": result.response,
                    }
                    if eval_name == "ToolCallAccuracy" and filtered_tool_calls:
                        kwargs["tool_calls"] = filtered_tool_calls
                        kwargs["tool_definitions"] = tool_defs
                    # Run synchronous evaluator in executor to avoid blocking event loop
                    score_result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda ev=evaluator, kw=kwargs: ev(**kw)
                    )
                    scores[eval_name] = score_result if isinstance(score_result, dict) else {"score": score_result}
                except Exception as exc:
                    logger.warning(
                        "[eval %s] evaluator %s failed for '%s': %s",
                        run_id,
                        eval_name,
                        result.scenario,
                        exc,
                    )
                    scores[eval_name] = {"error": str(exc)}

            result.scores = scores

            # Accumulate per-criterion pass/fail
            for criterion, sd in scores.items():
                if criterion not in criteria_totals:
                    criteria_totals[criterion] = {"passed": 0, "failed": 0}
                passed = sd.get("passed", False)
                if not passed:
                    # Treat numeric score >= 3 as pass (5-point scale)
                    score_val = next((v for v in sd.values() if isinstance(v, (int, float))), None)
                    passed = bool(score_val is not None and score_val >= 3)
                if passed:
                    criteria_totals[criterion]["passed"] += 1
                else:
                    criteria_totals[criterion]["failed"] += 1

        # Aggregate: scenario "passed" if ALL criteria passed
        passed_count = 0
        failed_count = 0
        for result in run.results:
            if result.status == "error":
                failed_count += 1
                continue
            all_passed = all(
                sd.get("passed", False)
                or (
                    next((v for v in sd.values() if isinstance(v, (int, float))), None) is not None
                    and next((v for v in sd.values() if isinstance(v, (int, float))), 0) >= 3
                )
                for sd in result.scores.values()
                if "error" not in sd
            )
            if all_passed and result.scores:
                passed_count += 1
            else:
                failed_count += 1

        per_criteria: list[dict[str, Any]] = [{"criterion": k, **v} for k, v in criteria_totals.items()]
        run.foundry = FoundryEvalSummary(
            eval_id="",
            eval_run_id="",
            run_status="completed",
            result_counts={"passed": passed_count, "failed": failed_count},
            per_testing_criteria_results=per_criteria,
            output_items=[],
            report_url="",
        )
        await self._storage.save_run(run)

    def _build_report(self, run: EvalRun, use_case: str) -> dict[str, Any]:
        """Build the eval_report.json dict."""
        return {
            "run_id": run.run_id,
            "use_case": use_case,
            "mode": run.mode,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
            "total_scenarios": len(run.results),
            "foundry_summary": run.foundry.model_dump() if run.foundry else None,
            "scenarios": [
                {
                    "scenario": r.scenario,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "scores": r.scores,
                    "error": r.error,
                }
                for r in run.results
            ],
        }
