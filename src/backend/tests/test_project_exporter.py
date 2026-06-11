"""Tests for the project exporter — ZIP packaging of Kratos use-cases."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.project_exporter import ProjectExporter, _slugify

# ---------------------------------------------------------------------------
# Unit-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def use_case_tree(tmp_path: Path) -> Path:
    """Build a minimal but realistic use-case tree under tmp_path/use-cases/foo."""
    uc = tmp_path / "use-cases" / "finance-close"
    (uc / "skills" / "sap-s4").mkdir(parents=True)
    (uc / "skills" / "policy-ref" / "references").mkdir(parents=True)

    (uc / "SYSTEM_PROMPT.md").write_text(
        "---\n"
        "name: Finance Close Controller\n"
        "description: AI co-pilot for the controller team running month-end close.\n"
        "sampleQuestions:\n  - What is variance vs forecast?\n"
        "---\n\n"
        "You orchestrate the close process.\n",
        encoding="utf-8",
    )

    (uc / "skills" / "sap-s4" / "SKILL.md").write_text(
        "---\nname: sap-s4\ndescription: Query the SAP S/4HANA ledger\nenabled: true\n---\n\n# SAP S/4\n",
        encoding="utf-8",
    )

    (uc / "skills" / "policy-ref" / "SKILL.md").write_text(
        "---\nname: policy-ref\ndescription: Internal close policy\nenabled: true\n---\n",
        encoding="utf-8",
    )
    (uc / "skills" / "policy-ref" / "references" / "policy.md").write_text("# Close policy\n", encoding="utf-8")

    # Junk that MUST NOT be exported.
    (uc / "skills" / "sap-s4" / "__pycache__").mkdir()
    (uc / "skills" / "sap-s4" / "__pycache__" / "blob.pyc").write_text("noise")
    (uc / "evals").mkdir()
    (uc / "evals" / "scenario.yaml").write_text("name: blah")

    (uc / ".mcp.json").write_text(
        json.dumps(
            {
                "sap-s4": {
                    "type": "local",
                    "command": "sap-s4-mcp-server",
                    "args": [],
                    "tools": ["*"],
                },
                "external-kb": {
                    "type": "http",
                    "url": "https://kb.example/mcp",
                    "tools": ["*"],
                },
            }
        ),
        encoding="utf-8",
    )

    # apm.yml with empty deps — must be omitted.
    (uc / "apm.yml").write_text("dependencies:\n  apm: []\n  mcp: []\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def mocks_tree(tmp_path: Path) -> Path:
    """Build a minimal mocks/packages tree with one matching package."""
    mocks_root = tmp_path / "mocks"
    pkg = mocks_root / "packages" / "sap-s4-mcp-server"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name": "sap-s4-mcp-server", "version": "0.0.1"}', encoding="utf-8")
    (pkg / "index.js").write_text("// stub\n", encoding="utf-8")
    return mocks_root


@pytest.fixture
def exporter(use_case_tree: Path, mocks_tree: Path) -> ProjectExporter:
    return ProjectExporter(use_cases_root=use_case_tree / "use-cases", mocks_root=mocks_tree)


# ---------------------------------------------------------------------------
# Unit tests — assemble()
# ---------------------------------------------------------------------------


def test_slugify_normalises():
    assert _slugify("Finance Close") == "finance-close"
    assert _slugify("foo!@#bar") == "foo-bar"
    assert _slugify("") == "agent"


def test_assemble_writes_core_files(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    assert (out / "copilot-instructions.md").is_file()
    # System prompt is copied verbatim (frontmatter retained — main.py strips it at load time).
    assert "Finance Close Controller" in (out / "copilot-instructions.md").read_text()
    assert (out / "skills" / "sap-s4" / "SKILL.md").is_file()
    assert (out / "skills" / "policy-ref" / "references" / "policy.md").is_file()


def test_assemble_renders_templates_with_frontmatter(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    pyproject = (out / "pyproject.toml").read_text()
    assert 'name = "finance-close"' in pyproject

    azure_yaml = (out / "azure.yaml").read_text()
    assert "finance-close:" in azure_yaml

    readme = (out / "README.md").read_text()
    assert "Finance Close Controller" in readme
    assert "AI co-pilot for the controller team" in readme

    agent_yaml = (out / "agent.yaml").read_text()
    assert "Finance Close Controller" in agent_yaml


def test_assemble_translates_mcp_config(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    cfg = json.loads((out / "mcp-config.json").read_text())
    assert "sap-s4" in cfg
    assert cfg["sap-s4"]["type"] == "local"
    assert cfg["external-kb"]["type"] == "http"


def test_assemble_bundles_referenced_mock_only(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    bundled = out / "mocks" / "packages" / "sap-s4-mcp-server" / "package.json"
    assert bundled.is_file()

    # HTTP-type server is not bundled.
    assert not (out / "mocks" / "packages" / "external-kb").exists()


def test_assemble_omits_empty_apm(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)
    assert not (out / "apm.yml").exists()


def test_assemble_copies_infra(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    assert (out / "infra" / "main.bicep").is_file()
    assert (out / "infra" / "main.parameters.json").is_file()
    assert (out / "infra" / "core" / "ai" / "ai-project.bicep").is_file()


def test_assemble_unknown_use_case_raises(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(FileNotFoundError):
        exporter.assemble("does-not-exist", out)


# ---------------------------------------------------------------------------
# Unit tests — build_zip()
# ---------------------------------------------------------------------------


def test_build_zip_excludes_skip_dirs(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    blob = ProjectExporter.build_zip(out)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())

    assert "copilot-instructions.md" in names
    assert "skills/sap-s4/SKILL.md" in names
    assert "mocks/packages/sap-s4-mcp-server/package.json" in names
    assert "Dockerfile" in names
    assert "main.py" in names
    assert "infra/main.bicep" in names

    # Junk dirs must be entirely absent.
    assert not any("__pycache__" in n for n in names)
    assert not any("evals/" in n for n in names)


def test_assemble_handles_missing_mocks_root(use_case_tree: Path, tmp_path: Path):
    # No mocks_root provided — assemble must still succeed; mocks/ is just empty.
    exporter = ProjectExporter(use_cases_root=use_case_tree / "use-cases", mocks_root=tmp_path / "nope")
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)
    assert (out / "main.py").is_file()
    assert not (out / "mocks").exists()


# ---------------------------------------------------------------------------
# Integration test — the /api/use-cases/{use_case}/export endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def export_client(use_case_tree: Path, mocks_tree: Path, monkeypatch: pytest.MonkeyPatch):
    """Boot the FastAPI app with stubbed-out Azure deps and one registry."""
    monkeypatch.chdir(use_case_tree)

    from app.main import app

    # Bypass lifespan — set the bits the export router actually uses.
    registry_stub = MagicMock()
    registry_stub.system_prompt = ""
    app.state.registries = {"finance-close": registry_stub}

    blob_stub = MagicMock()
    blob_stub.local_base_dir = use_case_tree / "use-cases"
    app.state.blob_skill_service = blob_stub

    # mocks_tree is fixture-built next to use_case_tree but ProjectExporter
    # defaults to ``mocks/`` relative to cwd, which is now use_case_tree —
    # which already contains it (same tmp_path). So no extra wiring needed.
    assert (use_case_tree / "mocks").exists() or mocks_tree.exists()

    return TestClient(app, raise_server_exceptions=False)


def test_export_endpoint_streams_zip(export_client: TestClient):
    response = export_client.get("/api/use-cases/finance-close/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    assert 'filename="finance-close-foundry-agent.zip"' in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
    assert "copilot-instructions.md" in names
    assert "main.py" in names
    assert "Dockerfile" in names
    assert "azure.yaml" in names


def test_export_endpoint_unknown_use_case(export_client: TestClient):
    response = export_client.get("/api/use-cases/does-not-exist/export")
    assert response.status_code == 404


def test_export_endpoint_rejects_bad_name(export_client: TestClient):
    response = export_client.get("/api/use-cases/..%2Fetc/export")
    # FastAPI/Starlette returns 404 for path-traversal attempts in URL path
    # segments; either way the export router never sees an unsafe name.
    assert response.status_code in (400, 404)
