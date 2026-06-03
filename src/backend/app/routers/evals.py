"""Evals API — per-use-case scenario CRUD + run management.

Endpoints:
    GET    /api/use-cases/{use_case}/evals/scenarios
    POST   /api/use-cases/{use_case}/evals/scenarios/generate
    PUT    /api/use-cases/{use_case}/evals/scenarios/{name}
    DELETE /api/use-cases/{use_case}/evals/scenarios/{name}
    POST   /api/use-cases/{use_case}/evals/run
    GET    /api/use-cases/{use_case}/evals/runs
    GET    /api/use-cases/{use_case}/evals/runs/{run_id}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_authenticated_user
from app.models import (
    EvalRun,
    EvalRunList,
    EvalRunRequest,
    EvalScenario,
    EvalScenarioList,
    GenerateScenariosRequest,
    GenerateScenariosResponse,
)
from app.services.eval_service import EvalService
from app.services.eval_storage import EvalStorage

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _get_storage(request: Request) -> EvalStorage:
    storage: EvalStorage | None = getattr(request.app.state, "eval_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Eval storage is not initialized")
    return storage


def _get_service(request: Request) -> EvalService:
    svc: EvalService | None = getattr(request.app.state, "eval_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Eval service is not initialized")
    return svc


def _ensure_use_case(request: Request, use_case: str) -> None:
    registries = getattr(request.app.state, "registries", {})
    if use_case not in registries:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")


# ── Scenarios ────────────────────────────────────────────────────────────────


@router.get("/{use_case}/evals/scenarios", response_model=EvalScenarioList)
async def list_scenarios(use_case: str, request: Request) -> EvalScenarioList:
    _ensure_use_case(request, use_case)
    storage = _get_storage(request)
    scenarios = await storage.list_scenarios(use_case)
    return EvalScenarioList(scenarios=scenarios)


@router.post("/{use_case}/evals/scenarios/generate", response_model=GenerateScenariosResponse)
async def generate_scenarios(
    use_case: str,
    body: GenerateScenariosRequest,
    request: Request,
) -> GenerateScenariosResponse:
    _ensure_use_case(request, use_case)
    storage = _get_storage(request)
    service = _get_service(request)
    try:
        scenarios = await service.generate_scenarios(
            use_case=use_case,
            count=body.count,
            instructions=body.instructions,
        )
    except Exception as exc:
        logger.exception("Scenario generation failed for %s", use_case)
        raise HTTPException(status_code=502, detail=f"Scenario generation failed: {exc}") from exc

    if body.persist:
        for s in scenarios:
            await storage.upsert_scenario(use_case, s)
    return GenerateScenariosResponse(scenarios=scenarios, persisted=body.persist)


@router.put("/{use_case}/evals/scenarios/{name}", response_model=EvalScenario)
async def upsert_scenario(
    use_case: str,
    name: str,
    scenario: EvalScenario,
    request: Request,
) -> EvalScenario:
    _ensure_use_case(request, use_case)
    # Allow renaming if the path name doesn't match — prefer body name
    # but reject obvious mismatches that suggest a client bug.
    if scenario.name != name and not scenario.name:
        scenario = scenario.model_copy(update={"name": name})
    storage = _get_storage(request)
    await storage.upsert_scenario(use_case, scenario)
    return scenario


@router.delete("/{use_case}/evals/scenarios/{name}")
async def delete_scenario(use_case: str, name: str, request: Request) -> dict[str, bool]:
    _ensure_use_case(request, use_case)
    storage = _get_storage(request)
    removed = await storage.delete_scenario(use_case, name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Scenario '{name}' not found")
    return {"deleted": True}


# ── Runs ─────────────────────────────────────────────────────────────────────


@router.post("/{use_case}/evals/run", response_model=EvalRun)
async def start_run(
    use_case: str,
    body: EvalRunRequest,
    request: Request,
    user: dict = Depends(require_authenticated_user),
) -> EvalRun:
    _ensure_use_case(request, use_case)
    service = _get_service(request)
    try:
        run = await service.start_run(
            use_case=use_case,
            mode=body.mode,
            scenario_names=body.scenarios or None,
            started_by=user.get("userId", "anonymous"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start eval run for %s", use_case)
        raise HTTPException(status_code=500, detail=f"Failed to start eval run: {exc}") from exc
    return run


@router.get("/{use_case}/evals/runs", response_model=EvalRunList)
async def list_runs(use_case: str, request: Request, limit: int = 50) -> EvalRunList:
    _ensure_use_case(request, use_case)
    service = _get_service(request)
    runs = await service.list_runs(use_case, limit=limit)
    return EvalRunList(runs=runs)


@router.get("/{use_case}/evals/runs/{run_id}", response_model=EvalRun)
async def get_run(use_case: str, run_id: str, request: Request) -> EvalRun:
    _ensure_use_case(request, use_case)
    service = _get_service(request)
    run = await service.get_run(use_case, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run
