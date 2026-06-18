"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.observability import instrument_fastapi_app, setup_telemetry
from app.routers import (
    admin_analysis,
    admin_apm,
    admin_mcp,
    admin_prompt,
    admin_skills,
    agent,
    conversations,
    copilot_studio,
    evals,
    export,
    files,
    health,
    import_persona,
    settings,
    traces,
    use_cases,
)
from app.services.apm_service import ApmError, ApmService
from app.services.blob_skill_service import BlobSkillService
from app.services.cosmos_service import CosmosService
from app.services.eval_service import EvalService
from app.services.eval_storage import EvalStorage
from app.services.foundry_agent_proxy import FoundryAgentProxy
from app.services.skill_registry import SkillRegistry
from app.services.traces_service import TracesService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# Silence chatty Azure SDK HTTP loggers — they log full request/response headers at INFO
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def _apm_startup_sync(apm_service: ApmService, use_cases_root: str) -> tuple[int, int]:
    """Run ``apm install`` for each local use-case that needs syncing.

    Returns a ``(synced, total)`` tuple where ``total`` is the number of
    use-case directories considered and ``synced`` the number that were
    successfully installed. APM failures are logged as warnings and never
    propagate — the app must still boot so local skills remain usable.
    """
    root = Path(use_cases_root)
    if not root.is_dir():
        logger.info("APM use-cases root %s does not exist — skipping startup sync", root)
        return (0, 0)

    synced = 0
    total = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        use_case = entry.name
        total += 1
        try:
            if not await apm_service.needs_sync(use_case):
                continue
            await apm_service.sync(use_case)
            synced += 1
            logger.info("APM sync succeeded for use-case '%s'", use_case)
        except ApmError as exc:
            logger.warning("APM sync failed for use-case '%s': %s", use_case, exc)
    return (synced, total)


async def _keep_warm_loop(proxy: FoundryAgentProxy, interval_s: int) -> None:
    """Maintain the hosted-agent warm pool so new conversations start fast AND
    stay isolated.

    Foundry hosted agents scale per-session: each conversation's sandbox has its
    own /tmp, so sandboxes must NOT be shared between conversations. This loop
    keeps a small pool of pre-provisioned, unclaimed sandboxes warm (pinging each
    to reset its 15-min idle timer) and replenishes the pool after claims. A new
    conversation pops its own dedicated warm sandbox — fast and fully isolated.
    Runs until cancelled on shutdown; never lets a transient error kill the loop.
    """
    import asyncio

    while True:
        try:
            size, target = await proxy.maintain_warm_pool()
            logger.info("Warm-pool: ready (%d/%d sandboxes provisioned)", size, target)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep the loop alive across any transient error
            logger.warning("Warm-pool: unexpected error in loop", exc_info=True)
        await asyncio.sleep(interval_s)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize services on startup, cleanup on shutdown."""
    settings = get_settings()

    # Fail fast if the hosted agent endpoint is not configured
    if not settings.foundry_agent_invocations_endpoint and not settings.foundry_project_endpoint:
        raise RuntimeError(
            "Missing required configuration: set FOUNDRY_AGENT_INVOCATIONS_ENDPOINT "
            "or FOUNDRY_PROJECT_ENDPOINT + FOUNDRY_AGENT_NAME"
        )

    # Setup OpenTelemetry (traces, metrics, logs/events exporters)
    setup_telemetry(settings)

    # Initialize Cosmos DB service
    cosmos_service = CosmosService(settings)
    await cosmos_service.initialize()
    application.state.cosmos_service = cosmos_service

    # Initialize Blob Storage service for skills
    blob_skill_service = BlobSkillService(settings)
    await blob_skill_service.initialize()
    application.state.blob_skill_service = blob_skill_service

    # Initialize APM service (shared across use-cases)
    apm_service = ApmService(settings, blob_skill_service)
    application.state.apm_service = apm_service

    # Run APM startup sync for each local use-case directory so that
    # apm_modules/ is materialised before the skill registries load.
    if settings.apm_enabled and settings.apm_startup_sync:
        synced, total = await _apm_startup_sync(apm_service, settings.apm_use_cases_root)
        logger.info("APM startup sync complete: %d/%d use-cases synced", synced, total)

    # Load all use-case registries from blob storage
    registries: dict[str, SkillRegistry] = {}
    if not blob_skill_service.is_available:
        logger.error("Blob storage is not configured — no skills will be available")
    else:
        try:
            # In local/dev mode Azurite starts empty — seed use-case folders
            # from the repository so all personas show up in the UI.
            seeded = await blob_skill_service.seed_from_local()
            if seeded:
                logger.info("Seeded %d use-case(s) into blob: %s", len(seeded), seeded)
            use_case_names = await blob_skill_service.list_use_cases()
            for uc_name in use_case_names:
                registry = SkillRegistry()
                await registry.load(uc_name, blob_skill_service, apm_service=apm_service)
                registries[uc_name] = registry
        except Exception:
            logger.exception("Failed to load use-cases from blob storage")

    application.state.registries = registries
    # Keep backward compat: skill_registry points to "generic"
    application.state.skill_registry = registries.get("generic", SkillRegistry())
    logger.info("Loaded %d use-cases: %s", len(registries), list(registries.keys()))

    # Initialize Foundry hosted agent proxy (Copilot SDK runs in the hosted agent only)
    foundry_proxy = FoundryAgentProxy(settings)
    await foundry_proxy.start()
    application.state.foundry_proxy = foundry_proxy
    application.state.settings = settings

    # Start the keep-warm background task so the hosted-agent container never
    # scales to zero (avoids cold-start latency and gateway 408s). Skipped in
    # local mode where the hosted agent is a localhost stub.
    keep_warm_task = None
    if settings.keep_warm_enabled and not settings.is_local_mode:
        import asyncio

        keep_warm_task = asyncio.create_task(_keep_warm_loop(foundry_proxy, settings.keep_warm_interval_s))
        logger.info(
            "Warm-pool task started — maintaining %d pre-warmed sandboxes, refresh every %ds",
            settings.warm_pool_size,
            settings.keep_warm_interval_s,
        )
    application.state.keep_warm_task = keep_warm_task

    # Initialize Eval storage + service (per-use-case scenarios, runs, results)
    eval_storage = EvalStorage(blob_skill_service, local_base_dir=settings.apm_use_cases_root)
    application.state.eval_storage = eval_storage
    eval_service = EvalService(settings, eval_storage, registries, foundry_proxy=foundry_proxy)
    application.state.eval_service = eval_service

    # Initialize Traces service (App Insights waterfall queries)
    traces_service = TracesService(settings)
    application.state.traces_service = traces_service

    logger.info("Kratos Agent Service started — environment=%s", settings.environment)
    yield

    # Cleanup
    if keep_warm_task is not None:
        import asyncio
        import contextlib

        keep_warm_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keep_warm_task
    await eval_service.shutdown()
    await traces_service.close()
    await foundry_proxy.stop()
    await blob_skill_service.close()
    await cosmos_service.close()
    logger.info("Kratos Agent Service shutting down")


app = FastAPI(
    title="Kratos Agent Service",
    description="Agentic AI backend powered by GitHub Copilot SDK & Microsoft Foundry",
    version="0.1.0",
    lifespan=lifespan,
)

# Instrument FastAPI BEFORE first request (middleware must be added before stack is built).
# Uses global ProxyTracerProvider; real provider is set by setup_telemetry() in the lifespan.
instrument_fastapi_app(app)

# CORS — configured for Static Web App frontend
_cors_settings = get_settings()
_cors_origins = [o.strip() for o in _cors_settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["health"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(admin_skills.router, prefix="/api/admin/skills", tags=["admin"])
app.include_router(admin_prompt.router, prefix="/api/admin/system-prompt", tags=["admin"])
app.include_router(admin_mcp.router, prefix="/api/admin/mcp-servers", tags=["admin"])
app.include_router(admin_apm.router, prefix="/api/admin/use-cases/{use_case}/apm", tags=["admin"])
app.include_router(admin_analysis.router, prefix="/api/admin/analysis", tags=["admin"])
app.include_router(use_cases.router, prefix="/api/use-cases", tags=["use-cases"])
app.include_router(import_persona.router, prefix="/api/use-cases", tags=["import"])
app.include_router(export.router, prefix="/api/use-cases", tags=["export"])
app.include_router(evals.router, prefix="/api/use-cases", tags=["evals"])
app.include_router(traces.router, prefix="/api/traces", tags=["traces"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(copilot_studio.router, prefix="/api/copilot-studio", tags=["copilot-studio"])
