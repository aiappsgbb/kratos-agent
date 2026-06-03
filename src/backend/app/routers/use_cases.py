"""Use-cases API — list available use-cases (agent personas)."""

import logging

from fastapi import APIRouter, Request

from app.models import UseCaseInfo, UseCaseList
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=UseCaseList)
async def list_use_cases(request: Request) -> UseCaseList:
    """List all available use-cases."""
    registries: dict[str, SkillRegistry] = request.app.state.registries
    use_cases = []
    for name, registry in sorted(registries.items()):
        # Parse display name and description from system prompt frontmatter
        display_name = name.replace("-", " ").title()
        description = ""
        sample_questions: list[str] = []
        if registry.system_prompt:
            from app.services.skill_registry import _parse_frontmatter

            fm, _ = _parse_frontmatter(registry.system_prompt)
            display_name = fm.get("name", display_name)
            description = fm.get("description", "")
            sample_questions = fm.get("sampleQuestions", [])

        use_cases.append(
            UseCaseInfo(
                name=name,
                displayName=display_name,
                description=description,
                skillCount=len(registry.skills),
                sampleQuestions=sample_questions,
            )
        )
    return UseCaseList(useCases=use_cases)
