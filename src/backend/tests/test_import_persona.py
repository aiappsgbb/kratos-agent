"""Tests for the persona import API (``POST /api/use-cases/import``)."""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path):
    """TestClient with a local-only BlobSkillService and an empty registry map."""
    from app.config import Settings
    from app.main import app
    from app.services.blob_skill_service import BlobSkillService

    blob_service = BlobSkillService(Settings(), local_base_dir=str(tmp_path / "use-cases"))
    app.state.blob_skill_service = blob_service
    app.state.registries = {}
    app.state.apm_service = None

    yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.clear()


def _manifest(**overrides) -> dict:
    base = {
        "name": "Claims Triage Bot",
        "description": "Triages insurance claims and flags fraud signals.",
        "instructions": "You are a claims triage assistant. Be precise and cite policy rules.",
        "sampleQuestions": ["Triage claim 12345", "What is the fraud score for claim 999?"],
        "skills": [
            {"name": "fraud-check", "description": "Score fraud risk", "package": "acme/skills/skills/fraud-check"},
            {"name": "no-package-skill", "description": "metadata only"},
        ],
        "mcpServers": [{"name": "microsoft-learn", "transport": "http", "url": "https://learn.microsoft.com/api/mcp"}],
        "traits": ["analysis", "validation"],
        "workflow_model": "agent",
    }
    base.update(overrides)
    return base


def test_import_manifest_creates_persona(client, tmp_path):
    resp = client.post("/api/use-cases/import", json={"manifest": _manifest()})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "claims-triage-bot"
    assert data["displayName"] == "Claims Triage Bot"
    assert data["created"] is True
    assert data["files"]

    # Persona registered live
    from app.main import app

    assert "claims-triage-bot" in app.state.registries

    # Files written to the local mirror
    uc_dir = tmp_path / "use-cases" / "claims-triage-bot"
    assert (uc_dir / "SYSTEM_PROMPT.md").exists()
    assert (uc_dir / ".mcp.json").exists()
    assert (uc_dir / "apm.yml").exists()


def test_system_prompt_frontmatter_mapping(client, tmp_path):
    client.post("/api/use-cases/import", json={"manifest": _manifest()})
    text = (tmp_path / "use-cases" / "claims-triage-bot" / "SYSTEM_PROMPT.md").read_text()
    assert text.startswith("---\n")
    fm_block = text.split("---\n", 2)[1]
    fm = yaml.safe_load(fm_block)
    assert fm["name"] == "Claims Triage Bot"
    assert fm["description"].startswith("Triages insurance claims")
    assert fm["curated"] is True
    assert "Triage claim 12345" in fm["sampleQuestions"]
    # Instructions become the body
    assert "claims triage assistant" in text.split("---\n", 2)[2]


def test_apm_and_mcp_mapping(client, tmp_path):
    client.post("/api/use-cases/import", json={"manifest": _manifest()})
    uc_dir = tmp_path / "use-cases" / "claims-triage-bot"

    apm = yaml.safe_load((uc_dir / "apm.yml").read_text())
    assert apm["name"] == "kratos-claims-triage-bot"
    assert apm["dependencies"]["apm"] == ["acme/skills/skills/fraud-check"]
    assert apm["dependencies"]["mcp"][0]["name"] == "microsoft-learn"
    assert apm["metadata"]["kratos"]["traits"] == ["analysis", "validation"]
    assert apm["metadata"]["kratos"]["workflow_model"] == "agent"

    mcp = json.loads((uc_dir / ".mcp.json").read_text())
    assert mcp["microsoft-learn"]["url"] == "https://learn.microsoft.com/api/mcp"
    assert mcp["microsoft-learn"]["type"] == "http"


def test_url_less_mcp_server_skipped_in_mcp_json(client, tmp_path):
    # A registry reference with no url cannot be a runnable Copilot MCP entry, so
    # it must be skipped in .mcp.json (kept only in apm.yml) — never written as a
    # non-startable {"type": "http"} entry. This is exactly what the host site
    # emits for its `mcp-tools` / `m365-graph` requirements.
    manifest = _manifest(
        mcpServers=[
            {"name": "tools", "transport": "http", "registry": True},
            {"name": "microsoft-learn", "transport": "http", "url": "https://learn.microsoft.com/api/mcp"},
        ]
    )
    resp = client.post("/api/use-cases/import", json={"manifest": manifest})
    assert resp.status_code == 201, resp.text
    uc_dir = tmp_path / "use-cases" / "claims-triage-bot"

    mcp = json.loads((uc_dir / ".mcp.json").read_text())
    assert "tools" not in mcp  # url-less → skipped, no broken entry
    assert mcp["microsoft-learn"]["url"] == "https://learn.microsoft.com/api/mcp"

    # The dependency is still recorded in apm.yml for later resolution.
    apm = yaml.safe_load((uc_dir / "apm.yml").read_text())
    mcp_dep_names = {d["name"] for d in apm["dependencies"]["mcp"]}
    assert {"tools", "microsoft-learn"} <= mcp_dep_names


def test_import_dedupes_slug(client):
    first = client.post("/api/use-cases/import", json={"manifest": _manifest()})
    second = client.post("/api/use-cases/import", json={"manifest": _manifest()})
    assert first.json()["name"] == "claims-triage-bot"
    assert second.status_code == 201
    assert second.json()["name"] == "claims-triage-bot-2"


def test_import_overwrite_replaces(client):
    client.post("/api/use-cases/import", json={"manifest": _manifest()})
    resp = client.post(
        "/api/use-cases/import",
        json={"manifest": _manifest(description="updated"), "overwrite": True},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "claims-triage-bot"
    assert resp.json()["created"] is False


def test_conflict_when_no_dedupe_no_overwrite(client):
    client.post("/api/use-cases/import", json={"manifest": _manifest()})
    resp = client.post(
        "/api/use-cases/import",
        json={"manifest": _manifest(), "dedupe": False},
    )
    assert resp.status_code == 409


def test_requires_exactly_one_source(client):
    both = client.post(
        "/api/use-cases/import",
        json={"manifest": _manifest(), "prompt": "make a bot"},
    )
    assert both.status_code == 422
    neither = client.post("/api/use-cases/import", json={})
    assert neither.status_code == 422


def test_auth_enforced_when_enabled(client):
    from app.config import Settings, get_settings
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(admin_auth_enabled="true")
    resp = client.post("/api/use-cases/import", json={"manifest": _manifest()})
    assert resp.status_code == 401
