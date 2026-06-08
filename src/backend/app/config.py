"""Application configuration via environment variables and Azure Key Vault."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All production secrets are accessed via Managed Identity — no secrets in code.
    """

    # Azure service endpoints (set by Bicep / azd)
    cosmos_db_endpoint: str = ""
    azure_ai_search_endpoint: str = ""
    key_vault_uri: str = ""

    # Microsoft Foundry (deployed by Bicep)
    foundry_endpoint: str = ""
    foundry_model_deployment: str = ""
    foundry_project_name: str = ""

    # Hosted agent proxy — backend forwards requests to the Foundry hosted agent
    foundry_project_endpoint: str = ""  # e.g. https://host/api/projects/proj
    foundry_agent_name: str = "kratos-agent"
    foundry_agent_invocations_endpoint: str = ""  # full URL override (optional)
    foundry_api_version: str = "v1"

    # Hosted-agent keep-warm — the backend keeps a small pool of pre-provisioned,
    # UNCLAIMED hosted-agent sandboxes ready. Each new conversation claims its own
    # warm sandbox (fast startup) that it owns exclusively (its own /tmp — no file
    # leakage between conversations). The keep-warm loop pings pooled sandboxes to
    # reset their idle timer and replenishes the pool. Disabled in local mode.
    keep_warm_enabled: bool = True
    keep_warm_interval_s: int = 300  # ping cadence; must be shorter than the per-session 15-min idle timeout
    warm_pool_size: int = 2  # number of pre-warmed, unclaimed sandboxes kept ready for new conversations

    # Azure Blob Storage for skills
    blob_storage_endpoint: str = ""
    blob_skills_container: str = "skills"

    # Observability
    applicationinsights_connection_string: str = ""
    otel_service_name: str = "kratos-agent-service"

    # Server
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    environment: str = "development"

    # CORS — comma-separated allowed origins; "*" for development only
    allowed_origins: str = "*"

    # Admin auth — set to "true" after configuring Easy Auth on Container Apps / SWA
    admin_auth_enabled: str = "false"

    # Cosmos DB database
    cosmos_db_database: str = "kratos-agent"

    # APM (Agent Package Manager) — materialises remote skills / prompts /
    # instructions / agents into each use-case via the `apm` CLI.
    apm_enabled: bool = True
    apm_binary: str = "apm"
    apm_default_target: str = "copilot"
    apm_use_cases_root: str = "use-cases"
    apm_startup_sync: bool = True

    # Local mode — run the backend without any Azure services.
    #   * SQLite replaces Cosmos DB (persistence under ``local_data_dir``)
    #   * GitHub OAuth token replaces Foundry / Managed Identity for the model call
    #   * Azurite (or any blob connection string) replaces MSI-backed blob
    # ``local_mode`` defaults to True when ``cosmos_db_endpoint`` is empty.
    local_mode: bool | None = None  # None → auto-detect; True/False → explicit override
    copilot_github_token: str = ""
    local_data_dir: str = ".local"
    blob_storage_connection_string: str = ""  # set for Azurite / local emulators

    # ── Evals ────────────────────────────────────────────────────────────
    # Optional override for the judge model used by azure-ai-evaluation
    # (defaults to ``gpt-4.1`` per the foundry-evals skill recommendation —
    # azure-ai-evaluation still expects ``max_tokens`` which gpt-5.x rejects).
    eval_model: str = "gpt-4.1"
    # App Insights ARM resource ID for resource-scoped KQL queries used by
    # the Traces panel. Falls back to ``application_insights_workspace_id``
    # (workspace-scoped) when the resource ID is not set.
    application_insights_resource_id: str = ""
    application_insights_workspace_id: str = ""
    # Foundry project endpoint used by the eval submitter (overrides the
    # value already on Settings if set explicitly for evals).
    eval_foundry_project_endpoint: str = ""

    @property
    def is_local_mode(self) -> bool:
        """True when the backend should run without Azure services."""
        if self.local_mode is not None:
            return self.local_mode
        return not self.cosmos_db_endpoint

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
