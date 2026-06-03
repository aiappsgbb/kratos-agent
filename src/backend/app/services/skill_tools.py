"""MCP skill implementations as Copilot SDK @define_tool functions.

Each function here corresponds to one skill in skills.yaml.
The SDK calls these when the agent decides to invoke a skill.
"""

import json
import logging
import os
import subprocess
import time
from contextvars import ContextVar
from pathlib import Path

import httpx
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from copilot.tools import define_tool
from opentelemetry import trace
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ─── Kratos context vars — set by copilot_agent.run() so tool spans carry the ─
# ─── same kratos attributes as the parent invoke_agent span.               ─────

_ctx_use_case: ContextVar[str] = ContextVar("kratos_use_case", default="")
_ctx_conversation_id: ContextVar[str] = ContextVar("kratos_conversation_id", default="")
_ctx_eval_run_id: ContextVar[str] = ContextVar("kratos_eval_run_id", default="")


def _set_kratos_attrs(span: trace.Span) -> None:
    """Stamp kratos.* attributes on *span* from the active context vars."""
    use_case = _ctx_use_case.get()
    if use_case:
        span.set_attribute("kratos.use_case", use_case)
    conv_id = _ctx_conversation_id.get()
    if conv_id:
        span.set_attribute("kratos.conversation_id", conv_id)
    eval_run_id = _ctx_eval_run_id.get()
    if eval_run_id:
        span.set_attribute("kratos.eval_run_id", eval_run_id)


# ─── Shared singletons — avoid recreating expensive objects on every tool call ─

_credential: DefaultAzureCredential | None = None
_http_client: httpx.AsyncClient | None = None


def _get_credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


# ─── Web Search ──────────────────────────────────────────────────────────────


class WebSearchParams(BaseModel):
    query: str = Field(default="", description="The search query to look up on the internet")


@define_tool(description="Real-time internet search for current information and market data")
async def web_search(params: WebSearchParams) -> dict:
    """Search the internet using Foundry web_search_preview tool."""
    with tracer.start_as_current_span("skill.web_search") as span:
        _set_kratos_attrs(span)
        t0 = time.monotonic()
        query = params.query
        logger.info("web_search called: query=%r", query)

        if not query:
            return {"error": "Missing required search query for web_search"}

        foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT", "")
        model_deployment = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "")
        if not foundry_endpoint or not model_deployment:
            return {"error": "FOUNDRY_ENDPOINT or FOUNDRY_MODEL_DEPLOYMENT not configured"}

        # Build the Responses API URL from the Foundry endpoint
        # FOUNDRY_ENDPOINT is like https://<account>.cognitiveservices.azure.com/
        # We need https://<account>.services.ai.azure.com/openai/responses
        account_name = foundry_endpoint.rstrip("/").split("//")[1].split(".")[0]
        responses_url = f"https://{account_name}.services.ai.azure.com/openai/responses?api-version=2025-03-01-preview"

        try:
            credential = _get_credential()
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
        except Exception as e:
            logger.error("Failed to get auth token for web search: %s", e)
            return {"error": f"Authentication failed: {e}"}

        t1 = time.monotonic()
        try:
            client = _get_http_client()
            response = await client.post(
                responses_url,
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_deployment,
                    "input": f"Search the web for: {query}. Return only factual search results with sources.",
                    "tools": [{"type": "web_search_preview"}],
                    "tool_choice": {"type": "web_search_preview"},
                },
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error("Foundry web search call failed: %s", e)
            return {"error": f"Web search call failed: {e}"}

        # Extract text and citations from the Responses API output
        text = ""
        citations = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text = content.get("text", "")
                        for ann in content.get("annotations", []):
                            if ann.get("type") == "url_citation":
                                citations.append(
                                    {
                                        "title": ann.get("title", ""),
                                        "url": ann.get("url", ""),
                                    }
                                )

        logger.info(
            "web_search returned %d citations for query=%s auth_ms=%.0f search_ms=%.0f",
            len(citations),
            query,
            (t1 - t0) * 1000,
            (time.monotonic() - t1) * 1000,
        )
        return {"text": text, "citations": citations, "query": query}


# ─── RAG Search ──────────────────────────────────────────────────────────────


class RAGSearchParams(BaseModel):
    query: str = Field(description="The query to search in the knowledge base")
    index_name: str = Field(
        default="",
        description="The Azure AI Search index name to query. Each use case has its own index (e.g. 'wm-knowledge-base' for wealth management, 'ins-knowledge-base' for insurance).",
    )
    top: int = Field(default=5, description="Number of results to return")


@define_tool(description="Azure AI Search knowledge base for grounded answers from internal documents")
async def rag_search(params: RAGSearchParams) -> dict:
    """Search the Azure AI Search knowledge base."""
    with tracer.start_as_current_span("skill.rag_search") as span:
        _set_kratos_attrs(span)
        ai_search_endpoint = os.environ.get("AZURE_AI_SEARCH_ENDPOINT", "")
        if not ai_search_endpoint:
            return {"error": "AZURE_AI_SEARCH_ENDPOINT not configured"}

        index_name = params.index_name.strip() if params.index_name else os.environ.get("AI_SEARCH_INDEX", "")
        if not index_name:
            return {"error": "index_name must be provided (e.g. 'wm-knowledge-base')"}
        credential = _get_credential()
        async with SearchClient(
            endpoint=ai_search_endpoint,
            index_name=index_name,
            credential=credential,
        ) as client:
            results = await client.search(
                search_text=params.query,
                top=params.top,
                query_type="semantic",
                semantic_configuration_name="default",
            )
            docs = []
            async for result in results:
                docs.append(
                    {
                        "content": str(result.get("content", ""))[:500],
                        "title": result.get("title", ""),
                        "source": result.get("source", ""),
                        "page": result.get("page_number", ""),
                        "score": result.get("@search.score", 0),
                    }
                )
            return {"results": docs, "query": params.query}


# ─── Code Interpreter ─────────────────────────────────────────────────────────


class CodeInterpreterParams(BaseModel):
    code: str = Field(description="Python code to execute in a sandboxed environment")


@define_tool(description="Sandboxed Python execution for computation, data analysis, and code generation")
async def code_interpreter(params: CodeInterpreterParams) -> dict:
    """Execute Python code in a sandboxed subprocess."""
    with tracer.start_as_current_span("skill.code_interpreter") as span:
        _set_kratos_attrs(span)
        try:
            result = subprocess.run(
                ["python", "-c", params.code],
                capture_output=True,
                text=True,
                timeout=30,
                cwd="/tmp",  # noqa: S108
                check=False,
            )
            return {
                "stdout": result.stdout[:4000],
                "stderr": result.stderr[:1000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Code execution timed out (30s limit)"}
        except Exception as e:
            return {"error": str(e)}


# ─── Foundry Agent ────────────────────────────────────────────────────────────


class FoundryAgentParams(BaseModel):
    task: str = Field(description="The task to delegate to the specialized Foundry sub-agent")
    agent_name: str = Field(default="default", description="Name of the Foundry sub-agent to invoke")


@define_tool(description="Delegate complex or specialized tasks to Microsoft Foundry sub-agents")
async def foundry_agent(params: FoundryAgentParams) -> dict:
    """Delegate a task to a Microsoft Foundry specialized sub-agent."""
    with tracer.start_as_current_span("skill.foundry_agent") as span:
        _set_kratos_attrs(span)
        foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT", "")
        if not foundry_endpoint:
            return {"error": "FOUNDRY_ENDPOINT not configured"}

        credential = _get_credential()
        token = await credential.get_token("https://cognitiveservices.azure.com/.default")

        client = _get_http_client()
        response = await client.post(
            f"{foundry_endpoint}/agents/{params.agent_name}/run",
            headers={"Authorization": f"Bearer {token.token}"},
            json={"task": params.task},
        )
        return response.json()


# ─── CRM — Client Relationship Management ────────────────────────────────────

# Lazy-loaded CRM data
_wealth_crm_clients: list[dict] | None = None
_insurance_crm_clients: list[dict] | None = None


def _load_crm_json(relative_path: str) -> list[dict]:
    """Load CRM data from JSON, searching workspace-relative and repo-root paths."""
    candidates = [
        Path(relative_path),
        Path(__file__).resolve().parent.parent.parent.parent / relative_path,
    ]
    for path in candidates:
        if path.exists():
            clients = json.loads(path.read_text(encoding="utf-8"))
            logger.info("CRM data loaded from %s (%d clients)", path, len(clients))
            return clients

    logger.warning("CRM data file not found in any candidate path: %s", [str(path) for path in candidates])
    return []


def _load_wealth_crm_clients() -> list[dict]:
    """Load wealth-management CRM client data."""
    global _wealth_crm_clients
    if _wealth_crm_clients is None:
        _wealth_crm_clients = _load_crm_json("use-cases/wealth-management/skills/crm/data/customer-banking.json")
    return _wealth_crm_clients


def _load_insurance_crm_clients() -> list[dict]:
    """Load insurance CRM customer data."""
    global _insurance_crm_clients
    if _insurance_crm_clients is None:
        _insurance_crm_clients = _load_crm_json("use-cases/insurance/skills/crm/data/customer-insurance.json")
    return _insurance_crm_clients


def _sanitize_crm_client(client: dict) -> dict:
    """Return client dict with portfolio summary (without full positions list)."""
    result = {}
    for key in (
        "clientID",
        "status",
        "fullName",
        "firstName",
        "lastName",
        "dateOfBirth",
        "nationality",
        "contactDetails",
        "address",
        "financialInformation",
        "investmentProfile",
        "pep_status",
        "documents_provided",
        "name_screening_result",
    ):
        if key in client:
            result[key] = client[key]
    if "portfolio" in client:
        p = client["portfolio"]
        result["portfolio"] = {
            "strategy": p.get("strategy", ""),
            "riskProfile": p.get("riskProfile", ""),
            "performanceYTD": p.get("performanceYTD", ""),
            "performanceSinceInception": p.get("performanceSinceInception", ""),
            "inceptionDate": p.get("inceptionDate", ""),
            "positionCount": len(p.get("positions", [])),
        }
    return result


def _sanitize_insurance_client(client: dict) -> dict:
    """Return insurance customer dict with a compact policy summary."""
    result = {}
    for key in (
        "id",
        "clientID",
        "fullName",
        "firstName",
        "lastName",
        "dateOfBirth",
        "nationality",
        "contactDetails",
        "address",
    ):
        if key in client:
            result[key] = client[key]

    policies = client.get("policies", [])
    result["policySummary"] = {
        "policyCount": len(policies),
        "activePolicyCount": sum(1 for policy in policies if str(policy.get("PolicyStatus", "")).lower() == "active"),
        "policies": [
            {
                "PolicyNo": policy.get("PolicyNo", ""),
                "ProductType": policy.get("ProductType", ""),
                "PolicyStatus": policy.get("PolicyStatus", ""),
                "EffectiveDate": policy.get("EffectiveDate", ""),
                "ExpiryDate": policy.get("ExpiryDate", ""),
            }
            for policy in policies
        ],
    }
    return result


class CRMParams(BaseModel):
    domain: str = Field(
        default="wealth-management",
        description="CRM domain to query: 'wealth-management' or 'insurance'.",
    )
    action: str = Field(
        description=(
            "Action to perform: "
            "'search_name' (search client by name), "
            "'search_id' (lookup client by ID), "
            "'portfolio' (get full portfolio by client ID), "
            "'policies' (get full insurance policies by client ID), "
            "'list' (list all clients)"
        )
    )
    query: str = Field(
        default="",
        description="Client full name for search_name, or client ID for search_id/portfolio/policies. Leave empty for list.",
    )


@define_tool(
    description="Search and retrieve wealth-management or insurance customer profiles and holdings from the CRM system"
)
async def crm(params: CRMParams) -> dict:
    """CRM lookup for wealth-management clients or insurance customers."""
    with tracer.start_as_current_span("skill.crm") as span:
        _set_kratos_attrs(span)
        domain = params.domain.strip().lower()
        action = params.action.strip().lower()
        query = params.query.strip()

        if domain in {"wealth", "wealth-management", "wealth_management", "wm"}:
            clients = _load_wealth_crm_clients()
            if action == "list":
                summaries = [
                    {
                        "clientID": client.get("clientID"),
                        "fullName": client.get("fullName"),
                        "status": client.get("status"),
                        "riskProfile": client.get("investmentProfile", {}).get("riskProfile", ""),
                    }
                    for client in clients
                ]
                return {
                    "status": "success",
                    "domain": "wealth-management",
                    "count": len(summaries),
                    "clients": summaries,
                }

            if action == "search_name":
                if not query:
                    return {"status": "error", "message": "query (client name) is required for search_name"}
                normalized_query = query.lower()
                matches = [
                    _sanitize_crm_client(client)
                    for client in clients
                    if normalized_query in client.get("fullName", "").lower()
                    or normalized_query in client.get("firstName", "").lower()
                    or normalized_query in client.get("lastName", "").lower()
                ]
                if not matches:
                    return {"status": "not_found", "message": f"No clients found matching '{query}'"}
                return {"status": "success", "domain": "wealth-management", "count": len(matches), "clients": matches}

            if action == "search_id":
                if not query:
                    return {"status": "error", "message": "query (client ID) is required for search_id"}
                for client in clients:
                    if client.get("clientID") == query or client.get("id") == query:
                        return {
                            "status": "success",
                            "domain": "wealth-management",
                            "client": _sanitize_crm_client(client),
                        }
                return {"status": "not_found", "message": f"No client found with ID '{query}'"}

            if action == "portfolio":
                if not query:
                    return {"status": "error", "message": "query (client ID) is required for portfolio"}
                for client in clients:
                    if client.get("clientID") == query or client.get("id") == query:
                        return {
                            "status": "success",
                            "domain": "wealth-management",
                            "clientID": client.get("clientID"),
                            "fullName": client.get("fullName"),
                            "portfolio": client.get("portfolio", {}),
                        }
                return {"status": "not_found", "message": f"No client found with ID '{query}'"}

            return {
                "status": "error",
                "message": f"Unknown action '{action}' for wealth-management. Use: search_name, search_id, portfolio, list",
            }

        if domain in {"insurance", "ins"}:
            clients = _load_insurance_crm_clients()
            if action == "list":
                summaries = [
                    {
                        "clientID": client.get("clientID"),
                        "fullName": client.get("fullName"),
                        "activePolicyCount": sum(
                            1
                            for policy in client.get("policies", [])
                            if str(policy.get("PolicyStatus", "")).lower() == "active"
                        ),
                    }
                    for client in clients
                ]
                return {"status": "success", "domain": "insurance", "count": len(summaries), "clients": summaries}

            if action == "search_name":
                if not query:
                    return {"status": "error", "message": "query (customer name) is required for search_name"}
                normalized_query = query.lower()
                matches = [
                    _sanitize_insurance_client(client)
                    for client in clients
                    if normalized_query in client.get("fullName", "").lower()
                    or normalized_query in client.get("firstName", "").lower()
                    or normalized_query in client.get("lastName", "").lower()
                ]
                if not matches:
                    return {"status": "not_found", "message": f"No insurance customers found matching '{query}'"}
                return {"status": "success", "domain": "insurance", "count": len(matches), "clients": matches}

            if action == "search_id":
                if not query:
                    return {"status": "error", "message": "query (customer ID) is required for search_id"}
                for client in clients:
                    if client.get("clientID") == query or client.get("id") == query:
                        return {
                            "status": "success",
                            "domain": "insurance",
                            "client": _sanitize_insurance_client(client),
                        }
                return {"status": "not_found", "message": f"No insurance customer found with ID '{query}'"}

            if action == "policies":
                if not query:
                    return {"status": "error", "message": "query (customer ID) is required for policies"}
                for client in clients:
                    if client.get("clientID") == query or client.get("id") == query:
                        return {
                            "status": "success",
                            "domain": "insurance",
                            "clientID": client.get("clientID"),
                            "fullName": client.get("fullName"),
                            "policies": client.get("policies", []),
                        }
                return {"status": "not_found", "message": f"No insurance customer found with ID '{query}'"}

            return {
                "status": "error",
                "message": f"Unknown action '{action}' for insurance. Use: search_name, search_id, policies, list",
            }

        return {
            "status": "error",
            "message": f"Unknown CRM domain '{params.domain}'. Use: wealth-management or insurance",
        }


# ─── Tool registry ────────────────────────────────────────────────────────────

# All tools to register with every SDK session
ALL_TOOLS = [web_search, rag_search, code_interpreter, foundry_agent, crm]

# Map from tool function name → tool object (used by CopilotAgent to filter by enabled skills)
TOOL_MAP = {tool.name: tool for tool in ALL_TOOLS}
