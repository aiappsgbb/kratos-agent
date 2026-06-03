"""Pydantic models for API request/response schemas."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ─── Enums ───


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


# ─── Conversations ───


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    useCase: str = "generic"


class ConversationUpdate(BaseModel):
    title: str | None = None


class Conversation(BaseModel):
    id: str
    userId: str
    title: str
    useCase: str = "generic"
    status: ConversationStatus = ConversationStatus.ACTIVE
    createdAt: datetime
    updatedAt: datetime


class ConversationList(BaseModel):
    conversations: list[Conversation]


# ─── Messages ───


class Message(BaseModel):
    id: str
    conversationId: str
    role: MessageRole
    content: str
    toolCalls: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class MessageCreate(BaseModel):
    content: str


# ─── Attachments ───


class FileAttachment(BaseModel):
    type: Literal["file"] = "file"
    path: str
    displayName: str = ""
    content: str | None = None  # base64-encoded file content from browser uploads


class DirectoryAttachment(BaseModel):
    type: Literal["directory"] = "directory"
    path: str
    displayName: str = ""


class SelectionAttachment(BaseModel):
    type: Literal["selection"] = "selection"
    filePath: str
    displayName: str
    text: str = ""


Attachment = FileAttachment | DirectoryAttachment | SelectionAttachment


# ─── Agent ───


class AgentRequest(BaseModel):
    conversationId: str
    message: str
    useCase: str = "generic"
    attachments: list[Attachment] = Field(default_factory=list)


class ToolCallEvent(BaseModel):
    """Streamed event for tool call progress."""

    type: str = "tool_call"
    skillName: str
    status: str  # "started", "completed", "failed"
    input: str = ""
    output: str = ""
    durationMs: int = 0
    source: str = ""  # "local" | "blob" | "apm:<package>" — populated best-effort from the registry


class ThoughtEvent(BaseModel):
    """Streamed event for agent reasoning."""

    type: str = "thought"
    content: str
    iteration: int = 0


class ContentEvent(BaseModel):
    """Streamed event for response content."""

    type: str = "content"
    content: str


class UsageEvent(BaseModel):
    """Streamed event for token usage from a model turn."""

    type: str = "usage"
    promptTokens: int = 0
    completionTokens: int = 0
    reasoningTokens: int = 0
    totalTokens: int = 0


class DoneEvent(BaseModel):
    """Streamed event signaling completion."""

    type: str = "done"
    conversationId: str
    totalDurationMs: int = 0
    totalToolCalls: int = 0
    promptTokens: int = 0
    completionTokens: int = 0
    reasoningTokens: int = 0
    totalTokens: int = 0
    timeToFirstTokenMs: int = 0
    modelLatencyMs: int = 0


class ErrorEvent(BaseModel):
    """Streamed error event."""

    type: str = "error"
    message: str
    code: str = "UNKNOWN_ERROR"


class FollowUpQuestionsEvent(BaseModel):
    """Streamed event with suggested follow-up questions."""

    type: str = "follow_up_questions"
    questions: list[str] = Field(default_factory=list)


class UserInputRequestEvent(BaseModel):
    """Streamed event when the agent asks the user a question."""

    type: str = "user_input_request"
    requestId: str
    question: str
    choices: list[str] = Field(default_factory=list)
    allowFreeform: bool = True


class UserInputResponseRequest(BaseModel):
    """Payload for responding to a user input request."""

    conversationId: str
    requestId: str
    answer: str


# ─── Copilot Studio (synchronous bridge) ───


class CopilotStudioRequest(BaseModel):
    """Inbound message from Copilot Studio / Teams."""

    message: str = Field(..., description="User message text")
    conversationId: str = Field(
        default="",
        description="Optional conversation ID to continue a multi-turn session. Leave empty to start a new conversation.",
    )
    useCase: str = Field(default="generic", description="Use-case identifier")


class CopilotStudioResponse(BaseModel):
    """Response returned to Copilot Studio / Teams."""

    conversationId: str = Field(description="Conversation ID (new or existing)")
    reply: str = Field(description="Agent's complete response text")


# ─── Settings ───


class AIServiceSettings(BaseModel):
    """AI service configuration submitted by the user."""

    foundryEndpoint: str = Field(default="", description="Microsoft Foundry endpoint URL")
    foundryModelDeployment: str = Field(default="gpt-52", description="Model deployment name")


class AIServiceStatus(BaseModel):
    """Current AI service config status."""

    configured: bool = False
    foundryEndpoint: str = ""
    foundryModelDeployment: str = ""
    code: str = "INTERNAL_ERROR"


# ─── Skills Admin ───


class SkillFile(BaseModel):
    """A file belonging to a skill (non-SKILL.md)."""

    path: str  # relative path from skill root, e.g. "scripts/run.py"
    name: str  # basename
    content: str = ""


class SkillFileList(BaseModel):
    files: list[SkillFile]


class SkillFileUpsert(BaseModel):
    content: str = ""


class SkillResponse(BaseModel):
    """Skill as returned by the admin API."""

    name: str
    description: str
    enabled: bool = True
    instructions: str = ""
    toolName: str = ""
    fileCount: int = 0
    source: str = "local"  # "local" | "blob" | "apm:<package>"


class SkillCreate(BaseModel):
    """Payload for creating a new skill."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    instructions: str = Field(default="", max_length=10000)


class SkillUpdate(BaseModel):
    """Payload for updating a skill. All fields optional."""

    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    instructions: str | None = Field(default=None, max_length=10000)


class SkillList(BaseModel):
    """List of skills."""

    skills: list[SkillResponse]


# ─── System Prompt Admin ───


class UseCaseInfo(BaseModel):
    """Use-case metadata as returned by the API."""

    name: str
    displayName: str = ""
    description: str = ""
    skillCount: int = 0
    sampleQuestions: list[str] = Field(default_factory=list)


class UseCaseList(BaseModel):
    """List of available use-cases."""

    useCases: list[UseCaseInfo]


class SystemPromptResponse(BaseModel):
    """System prompt as returned by the admin API."""

    content: str
    isDefault: bool = False


class SystemPromptUpdate(BaseModel):
    """Payload for updating the system prompt."""

    content: str = Field(..., min_length=1, max_length=50000)


# ─── MCP Servers Admin ───


class MCPConfigResponse(BaseModel):
    """MCP servers config as returned by the admin API."""

    servers: dict
    sources: dict[str, str] = {}


class MCPConfigUpdate(BaseModel):
    """Payload for updating the MCP servers config."""

    servers: dict


# ─── Evals ───────────────────────────────────────────────────────────────────


class ScenarioCategory(str, Enum):
    """Category of evaluation scenario — mirrors the threadlight-vnext taxonomy."""

    STANDARD = "standard"
    EDGE_CASE = "edge_case"
    ERROR_HANDLING = "error_handling"
    BOUNDARY = "boundary"
    COMPLIANCE = "compliance"


class EvalScenario(BaseModel):
    """A single evaluation scenario for a use-case."""

    name: str = Field(..., description="Unique slug, used as filename (lowercase, hyphenated)")
    category: ScenarioCategory = ScenarioCategory.STANDARD
    description: str = Field(default="", description="What this scenario tests")
    input_message: str = Field(..., description="The user message sent to the agent")
    input_data: dict[str, Any] = Field(default_factory=dict, description="Optional structured context")
    expected_behavior: str = Field(default="", description="Plain-language expected behavior")
    expected_tool_calls: list[str] = Field(
        default_factory=list,
        description="Tool names the agent is expected to call (without the mcp-tools- prefix)",
    )
    evaluators: list[str] = Field(
        default_factory=lambda: ["Relevance", "Coherence", "TaskAdherence", "IntentResolution", "ToolCallAccuracy"],
        description="Evaluator names to apply",
    )


class EvalScenarioList(BaseModel):
    scenarios: list[EvalScenario]


class GenerateScenariosRequest(BaseModel):
    """Body for the LLM-generation endpoint."""

    count: int = Field(default=10, ge=1, le=24, description="Number of scenarios to draft")
    persist: bool = Field(default=False, description="When True, persist the generated scenarios to blob")
    instructions: str = Field(
        default="",
        description="Optional extra guidance to inject into the generator prompt",
        max_length=4000,
    )


class GenerateScenariosResponse(BaseModel):
    scenarios: list[EvalScenario]
    persisted: bool = False


class EvalMode(str, Enum):
    """Eval execution mode."""

    VALIDATION = "validation"  # in-process invoke only, no Foundry evaluators
    FOUNDRY = "foundry"  # two-phase invoke + score via Foundry evaluators


class EvalRunStatus(str, Enum):
    PENDING = "pending"
    INVOKING = "invoking"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"


class EvalRunRequest(BaseModel):
    """Body to start an eval run."""

    mode: EvalMode = EvalMode.VALIDATION
    scenarios: list[str] = Field(
        default_factory=list,
        description="Subset of scenario names to run. Empty = all scenarios for the use-case.",
    )


class ScenarioResult(BaseModel):
    """Per-scenario invocation + score record."""

    scenario: str
    query: str
    response: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "completed"
    error: str = ""
    duration_ms: int = 0
    scores: dict[str, dict[str, Any]] = Field(default_factory=dict)


class FoundryEvalSummary(BaseModel):
    """Summary block from Foundry evaluators."""

    eval_id: str = ""
    eval_run_id: str = ""
    run_status: str = ""
    result_counts: dict[str, int] = Field(default_factory=dict)
    per_testing_criteria_results: list[dict[str, Any]] = Field(default_factory=list)
    output_items: list[dict[str, Any]] = Field(default_factory=list)
    report_url: str = ""


class EvalRun(BaseModel):
    """An eval run record."""

    run_id: str
    use_case: str
    mode: EvalMode
    status: EvalRunStatus
    scenarios: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_by: str = ""
    progress: str = ""
    error: str = ""
    results: list[ScenarioResult] = Field(default_factory=list)
    foundry: FoundryEvalSummary | None = None


class EvalRunList(BaseModel):
    runs: list[EvalRun]


# ─── Traces ──────────────────────────────────────────────────────────────────


class TraceSpan(BaseModel):
    """A single span in an operation waterfall."""

    id: str
    parent_id: str = ""
    name: str
    duration_ms: float = 0
    offset_ms: float = 0
    timestamp: str = ""
    success: bool = True
    result_code: str = ""
    type: str = ""
    cloud_role: str = ""
    category: str = "other"  # llm | agent | agent_internal | tool | skill | http | platform | error | other
    depth: int = 0
    attributes: dict[str, str | int | float] = Field(default_factory=dict)


class TraceLog(BaseModel):
    timestamp: str = ""
    message: str = ""
    severity: int = 0
    cloud_role: str = ""


class TraceOperation(BaseModel):
    """One operation (root span + its descendants)."""

    operation_id: str
    timestamp: str = ""
    total_duration_ms: float = 0
    span_count: int = 0
    use_case: str = ""
    conversation_id: str = ""
    eval_run_id: str = ""
    spans: list[TraceSpan] = Field(default_factory=list)
    logs: list[TraceLog] = Field(default_factory=list)


class TraceSummary(BaseModel):
    total_operations: int = 0
    avg_latency_ms: float = 0
    total_tokens: int = 0
    models_used: list[str] = Field(default_factory=list)
    error: str = ""


class TraceList(BaseModel):
    operations: list[TraceOperation]
    summary: TraceSummary
