"""Admin API for analyzing use-case consistency — detects contradictions, overlaps, and gaps."""

import json
import logging
import os
import re
import time

import httpx
from azure.identity.aio import DefaultAzureCredential
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_authenticated_user
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])

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
        _http_client = httpx.AsyncClient(timeout=120.0)
    return _http_client


def _get_registry(request: Request, use_case: str) -> SkillRegistry:
    """Resolve the SkillRegistry for the given use-case."""
    registries = getattr(request.app.state, "registries", {})
    registry = registries.get(use_case)
    if registry is None:
        registry = getattr(request.app.state, "skill_registry", None)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Use-case '{use_case}' not found")
    return registry


ANALYSIS_SYSTEM_PROMPT = """You are an expert AI configuration auditor. Your job is to analyze an AI agent's system prompt and skill definitions for inconsistencies, contradictions, overlaps, and gaps that could confuse the LLM during runtime.

You will receive:
1. The SYSTEM PROMPT that the agent uses
2. A list of all SKILL DEFINITIONS (each with name, description, enabled status, and full instructions)

Perform a thorough analysis and return a JSON object with the following structure:

{
  "summary": "A 2-3 sentence overall assessment",
  "overallScore": <number 0-100>,
  "issues": [
    {
      "severity": "critical" | "warning" | "info",
      "category": "contradiction" | "overlap" | "gap" | "terminology" | "tone" | "ambiguity" | "unused",
      "title": "Short title of the issue",
      "description": "Detailed explanation of the issue",
      "affectedSkills": ["skill-name-1", "skill-name-2"],
      "recommendation": "How to fix this"
    }
  ],
  "strengths": [
    "A positive aspect of the current configuration"
  ]
}

Categories explained:
- **contradiction**: The system prompt says one thing but a skill says the opposite (e.g. "never share PII" vs a skill that exposes PII)
- **overlap**: Two or more skills claim to handle the same domain/scenario, causing the LLM to pick inconsistently
- **gap**: The system prompt promises a capability that no skill implements, or a skill exists but is never referenced in routing logic
- **terminology**: Inconsistent naming — the system prompt calls something by one name, skills call it differently
- **tone**: Persona/style conflicts between the system prompt's expected tone and how skill instructions are written
- **ambiguity**: Instructions that are vague or could be interpreted multiple ways by the LLM
- **unused**: Skills that are enabled but seem disconnected from the system prompt's workflow

Rules:
- Be specific — cite exact phrases from the system prompt or skills when pointing out issues
- Rate severity accurately: critical = will definitely confuse the LLM, warning = may cause issues, info = minor style improvement
- The overallScore should reflect: 90+ = excellent, 70-89 = good with some issues, 50-69 = needs attention, <50 = significant problems
- Always find at least a few strengths to highlight
- Return ONLY the JSON object, no markdown wrapping, no code fences"""


class AnalysisRequest(BaseModel):
    """Optional overrides for the analysis."""

    includeDisabled: bool = Field(default=True, description="Include disabled skills in the analysis")


class AnalysisIssue(BaseModel):
    severity: str
    category: str
    title: str
    description: str
    affectedSkills: list[str] = Field(default_factory=list)
    recommendation: str = ""


class AnalysisResponse(BaseModel):
    summary: str
    overallScore: int
    issues: list[AnalysisIssue]
    strengths: list[str] = Field(default_factory=list)
    durationMs: int = 0


class ApplyFixRequest(BaseModel):
    """Describes the issue to fix."""

    category: str
    title: str
    description: str
    recommendation: str = ""
    affectedSkills: list[str] = Field(default_factory=list)


class FixChange(BaseModel):
    """A single change that was applied."""

    target: str  # "system-prompt" or skill name
    changeType: str  # "modified" or "disabled"
    summary: str


class ApplyFixResponse(BaseModel):
    """Result of applying a fix."""

    success: bool
    changes: list[FixChange] = Field(default_factory=list)
    error: str = ""


FIX_SYSTEM_PROMPT = """You are an expert AI configuration editor. You will receive:
1. An ISSUE describing a problem in an AI agent's configuration
2. The CURRENT CONTENT that needs to be fixed (either a system prompt or skill instructions)

Your job is to produce the FIXED version of the content that resolves the issue.

Rules:
- Make minimal, targeted changes — only fix what the issue describes
- Preserve the overall structure, tone, and formatting of the original content
- If the content has YAML frontmatter (--- block at the top), preserve it exactly
- Do NOT add comments explaining your changes
- Do NOT remove content unrelated to the issue
- Return ONLY the fixed content, nothing else — no markdown fences, no explanations"""


def _build_analysis_content(registry: SkillRegistry, include_disabled: bool) -> str:
    """Build the user-message content with the system prompt and all skills."""
    parts: list[str] = []

    # System prompt
    prompt = registry.system_prompt or "(No system prompt configured)"
    # Strip YAML frontmatter for analysis
    m = re.match(r"^---\s*\n.*?\n---\s*\n?", prompt, re.DOTALL)
    if m:
        prompt = prompt[m.end() :].strip()
    parts.append("=== SYSTEM PROMPT ===\n")
    parts.append(prompt)
    parts.append("\n\n")

    # Skills
    skills = list(registry.skills.values())
    if not include_disabled:
        skills = [s for s in skills if s.enabled]

    parts.append(f"=== SKILL DEFINITIONS ({len(skills)} skills) ===\n\n")
    for skill in sorted(skills, key=lambda s: s.name):
        parts.append(f"--- Skill: {skill.name} ---")
        parts.append(f"Description: {skill.description}")
        parts.append(f"Enabled: {skill.enabled}")
        parts.append(f"Tool Name: {skill.tool_name}")
        if skill.instructions:
            # Strip frontmatter from skill instructions too
            instr = skill.instructions
            m = re.match(r"^---\s*\n.*?\n---\s*\n?", instr, re.DOTALL)
            if m:
                instr = instr[m.end() :].strip()
            parts.append(f"Instructions:\n{instr}")
        else:
            parts.append("Instructions: (none)")
        parts.append("")

    return "\n".join(parts)


@router.post("/consistency", response_model=AnalysisResponse)
async def analyze_consistency(
    request: Request,
    body: AnalysisRequest | None = None,
    use_case: str = Query("generic"),
) -> AnalysisResponse:
    """Analyze a use-case's system prompt and skills for inconsistencies."""
    t0 = time.monotonic()
    registry = _get_registry(request, use_case)
    include_disabled = body.includeDisabled if body else True

    content = _build_analysis_content(registry, include_disabled)
    logger.info("Consistency analysis for '%s': %d chars", use_case, len(content))

    raw_content = await _call_llm(ANALYSIS_SYSTEM_PROMPT, content, json_mode=True)

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse analysis response: %s", e)
        raise HTTPException(status_code=502, detail="Failed to parse LLM response") from e

    duration_ms = int((time.monotonic() - t0) * 1000)

    return AnalysisResponse(
        summary=result.get("summary", ""),
        overallScore=result.get("overallScore", 0),
        issues=[AnalysisIssue(**issue) for issue in result.get("issues", [])],
        strengths=result.get("strengths", []),
        durationMs=duration_ms,
    )


# ─── Shared LLM helper ───


async def _call_llm(system_prompt: str, user_content: str, *, json_mode: bool = False) -> str:
    """Call the Foundry model and return the raw response content string."""
    foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT", "")
    model_deployment = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "")
    if not foundry_endpoint or not model_deployment:
        raise HTTPException(status_code=503, detail="FOUNDRY_ENDPOINT or FOUNDRY_MODEL_DEPLOYMENT not configured")

    account_name = foundry_endpoint.rstrip("/").split("//")[1].split(".")[0]
    chat_url = (
        f"https://{account_name}.services.ai.azure.com/openai/deployments/"
        f"{model_deployment}/chat/completions?api-version=2024-12-01-preview"
    )

    try:
        credential = _get_credential()
        token = await credential.get_token("https://cognitiveservices.azure.com/.default")
    except Exception as e:
        logger.error("Auth failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Authentication failed: {e}") from e

    payload: dict = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_completion_tokens": 4096,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        client = _get_http_client()
        resp = await client.post(
            chat_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Foundry API error: %s %s", e.response.status_code, e.response.text[:500])
        raise HTTPException(status_code=502, detail=f"LLM API error: {e.response.status_code}") from e
    except Exception as e:
        logger.error("Failed to call Foundry: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}") from e

    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ─── Apply Fix endpoint ───


def _reset_sessions(request: Request) -> None:
    """No-op — sessions are managed by the Foundry hosted agent."""
    logger.debug("Session reset skipped — Copilot SDK runs in hosted agent")


@router.post("/apply-fix", response_model=ApplyFixResponse)
async def apply_fix(
    request: Request,
    body: ApplyFixRequest,
    use_case: str = Query("generic"),
) -> ApplyFixResponse:
    """Apply an AI-generated fix for a specific consistency issue."""
    registry = _get_registry(request, use_case)
    changes: list[FixChange] = []

    # ── Simple case: disable unused skills ──
    if body.category == "unused" and body.affectedSkills:
        for skill_name in body.affectedSkills:
            skill = registry.get_skill(skill_name)
            if skill and skill.enabled:
                await registry.update_skill(skill_name, {"enabled": False})
                changes.append(
                    FixChange(
                        target=skill_name,
                        changeType="disabled",
                        summary=f"Disabled unused skill '{skill_name}'",
                    )
                )
        if changes:
            _reset_sessions(request)
            return ApplyFixResponse(success=True, changes=changes)
        return ApplyFixResponse(success=False, error="No matching enabled skills found to disable")

    # ── Determine what to fix ──
    targets_prompt = _issue_touches_prompt(body)
    targets_skills = body.affectedSkills if body.affectedSkills else []

    issue_text = (
        f"Category: {body.category}\n"
        f"Title: {body.title}\n"
        f"Description: {body.description}\n"
        f"Recommendation: {body.recommendation}"
    )

    # ── Fix system prompt if issue involves it ──
    if targets_prompt:
        prompt = registry.system_prompt or ""
        if prompt:
            user_msg = f"=== ISSUE ===\n{issue_text}\n\n=== CURRENT SYSTEM PROMPT ===\n{prompt}"
            fixed = await _call_llm(FIX_SYSTEM_PROMPT, user_msg)
            fixed = fixed.strip()
            # Strip markdown code fences if the model wrapped it
            if fixed.startswith("```"):
                fixed = re.sub(r"^```\w*\n?", "", fixed)
                fixed = re.sub(r"\n?```$", "", fixed)

            if fixed and fixed != prompt:
                # Update in Cosmos and registry
                cosmos = request.app.state.cosmos_service
                await cosmos.upsert_setting(
                    {
                        "id": "system-prompt",
                        "category": "system",
                        "content": fixed,
                    }
                )
                registry.system_prompt = fixed
                changes.append(
                    FixChange(
                        target="system-prompt",
                        changeType="modified",
                        summary="Updated system prompt to address the issue",
                    )
                )

    # ── Fix affected skills ──
    for skill_name in targets_skills:
        skill = registry.get_skill(skill_name)
        if not skill or not skill.instructions:
            continue

        user_msg = (
            f"=== ISSUE ===\n{issue_text}\n\n=== CURRENT SKILL INSTRUCTIONS ({skill_name}) ===\n{skill.instructions}"
        )
        fixed = await _call_llm(FIX_SYSTEM_PROMPT, user_msg)
        fixed = fixed.strip()
        if fixed.startswith("```"):
            fixed = re.sub(r"^```\w*\n?", "", fixed)
            fixed = re.sub(r"\n?```$", "", fixed)

        if fixed and fixed != skill.instructions:
            await registry.update_skill(skill_name, {"instructions": fixed})
            changes.append(
                FixChange(
                    target=skill_name,
                    changeType="modified",
                    summary=f"Updated instructions for skill '{skill_name}'",
                )
            )

    if changes:
        _reset_sessions(request)
        return ApplyFixResponse(success=True, changes=changes)

    return ApplyFixResponse(success=False, error="No changes were needed or the LLM returned identical content")


def _issue_touches_prompt(issue: ApplyFixRequest) -> bool:
    """Heuristic: does this issue likely require editing the system prompt?"""
    prompt_categories = {"gap", "ambiguity", "tone", "terminology", "contradiction"}
    if issue.category in prompt_categories:
        desc_lower = (issue.description + " " + issue.title + " " + issue.recommendation).lower()
        if any(kw in desc_lower for kw in ("system prompt", "prompt says", "prompt instructs", "prompt references")):
            return True
        # If no affected skills, the issue is about the prompt
        if not issue.affectedSkills:
            return True
    return False
