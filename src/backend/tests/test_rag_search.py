from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.skill_tools import RAGSearchParams, _rag_search


@pytest.mark.asyncio
async def test_rag_search_uses_bundled_documents_without_azure_search() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    with patch.dict(
        "os.environ",
        {
            "APM_USE_CASES_ROOT": str(repo_root / "use-cases"),
            "AZURE_AI_SEARCH_ENDPOINT": "",
        },
        clear=False,
    ):
        result = await _rag_search(
            RAGSearchParams(
                query="What does the homeowners policy say about water damage exclusions?",
                index_name="ins-knowledge-base",
            )
        )

    assert result["source"] == "bundled-demo-knowledge-base"
    assert result["results"]
    assert result["results"][0]["source"] == "olympus-homeowners-ho-2026.pdf"
    assert "flood" in result["results"][0]["content"].lower()


@pytest.mark.asyncio
async def test_rag_search_explains_missing_external_or_bundled_index() -> None:
    with patch.dict(
        "os.environ",
        {"APM_USE_CASES_ROOT": "does-not-exist", "AZURE_AI_SEARCH_ENDPOINT": ""},
        clear=False,
    ):
        result = await _rag_search(RAGSearchParams(query="policy", index_name="unknown-knowledge-base"))

    assert "Configure AZURE_AI_SEARCH_ENDPOINT" in result["error"]
