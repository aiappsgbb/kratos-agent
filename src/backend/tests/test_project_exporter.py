"""Tests for the v2 project exporter — full-clone ZIP packaging.

The v2 exporter mirrors a subset of the Kratos repo into the output tree:
the hosted-agent runtime + backend modules + chosen use-case + mocks +
trimmed infra. Tests build a synthetic Kratos-shaped layout under
``tmp_path`` (copying real source dirs from the actual checkout where
practical) and assert structural + content guarantees.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from app.services.project_exporter import ProjectExporter, _slugify

# Resolve the real Kratos checkout from the test file's location.
# ``src/backend/tests/test_project_exporter.py`` → parents[3] is the repo root.
REAL_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kratos_repo(tmp_path: Path) -> Path:
    """Build a tmp_path that LOOKS LIKE a Kratos repo root.

    Copies the real ``src/hosted-agent/``, ``src/backend/app/``, ``infra/``,
    and ``mocks/`` from the actual checkout so the exporter exercises the
    real file shapes. Then adds a synthetic ``use-cases/finance-close/``
    so we don't depend on the real use-case content.
    """
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "node_modules", "dist", "build", ".venv")
    shutil.copytree(REAL_REPO_ROOT / "src" / "hosted-agent", tmp_path / "src" / "hosted-agent", ignore=ignore)
    shutil.copytree(
        REAL_REPO_ROOT / "src" / "backend" / "app",
        tmp_path / "src" / "backend" / "app",
        ignore=ignore,
    )
    # Also copy src/backend/pyproject.toml so the exporter can bring it.
    shutil.copy2(REAL_REPO_ROOT / "src" / "backend" / "pyproject.toml", tmp_path / "src" / "backend" / "pyproject.toml")
    shutil.copytree(REAL_REPO_ROOT / "infra", tmp_path / "infra", ignore=ignore)
    shutil.copytree(REAL_REPO_ROOT / "mocks", tmp_path / "mocks", ignore=ignore)

    # Synthetic use-case at use-cases/finance-close/
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
            }
        ),
        encoding="utf-8",
    )

    # Add a second use-case so we can verify ONLY the chosen one is exported.
    other = tmp_path / "use-cases" / "marketing-launch"
    other.mkdir(parents=True)
    (other / "SYSTEM_PROMPT.md").write_text("---\nname: Other\n---\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def exporter(kratos_repo: Path) -> ProjectExporter:
    return ProjectExporter(repo_root=kratos_repo)


# ---------------------------------------------------------------------------
# Unit tests — assemble()
# ---------------------------------------------------------------------------


def test_slugify_normalises():
    assert _slugify("Finance Close") == "finance-close"
    assert _slugify("foo!@#bar") == "foo-bar"
    assert _slugify("") == "agent"


def test_assemble_copies_hosted_agent_verbatim(exporter: ProjectExporter, kratos_repo: Path, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    # main.py, pyproject.toml, Dockerfile are byte-identical to the source.
    for name in ("main.py", "pyproject.toml", "Dockerfile"):
        src = (kratos_repo / "src" / "hosted-agent" / name).read_bytes()
        dst = (out / "src" / "hosted-agent" / name).read_bytes()
        assert src == dst, f"{name} differs from src/hosted-agent/{name}"


def test_assemble_renders_agent_yaml_with_persona(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    agent_yaml = (out / "src" / "hosted-agent" / "agent.yaml").read_text()
    assert "name: finance-close" in agent_yaml
    assert "Finance Close Controller" in agent_yaml
    assert "kind: hosted" in agent_yaml
    assert "protocols:" in agent_yaml
    assert "environment_variables:" in agent_yaml
    # Cosmos DB database is per-export to avoid collisions.
    assert "kratos-agent-finance-close" in agent_yaml

    manifest = (out / "src" / "hosted-agent" / "agent.manifest.yaml").read_text()
    assert "name: finance-close" in manifest
    assert "Finance Close Controller" in manifest


def test_assemble_renders_azure_yaml_with_slug(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    azure_yaml = (out / "azure.yaml").read_text()
    assert "name: finance-close" in azure_yaml
    assert "finance-close:" in azure_yaml  # service block
    assert "project: ./src/hosted-agent" in azure_yaml
    assert "language: docker" in azure_yaml
    assert "context: ../.." in azure_yaml
    assert "azure.ai.agents:" in azure_yaml  # required extension


def test_assemble_copies_backend_app_recursively(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    # Key files exist (sanity check — real Kratos has 36+ .py files here).
    assert (out / "src" / "backend" / "app" / "__init__.py").is_file()
    assert (out / "src" / "backend" / "app" / "services" / "copilot_agent.py").is_file()
    assert (out / "src" / "backend" / "app" / "services" / "skill_registry.py").is_file()
    assert (out / "src" / "backend" / "app" / "services" / "cosmos_service.py").is_file()

    # No __pycache__ or .pyc leaked.
    backend_files = list((out / "src" / "backend").rglob("*"))
    assert not any("__pycache__" in p.parts for p in backend_files)
    assert not any(p.suffix == ".pyc" for p in backend_files)

    # The exporter must NOT ship its own templates (would be infinite recursion).
    assert not (out / "src" / "backend" / "app" / "exporter_templates").exists()


def test_assemble_includes_only_chosen_use_case(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    use_cases = sorted(p.name for p in (out / "use-cases").iterdir() if p.is_dir())
    assert use_cases == ["finance-close"]

    # System prompt + skills land where main.py expects them.
    assert (out / "use-cases" / "finance-close" / "SYSTEM_PROMPT.md").is_file()
    assert (out / "use-cases" / "finance-close" / "skills" / "sap-s4" / "SKILL.md").is_file()


def test_assemble_bundles_full_mocks_workspace(exporter: ProjectExporter, kratos_repo: Path, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    assert (out / "mocks" / "package.json").is_file()
    pkg_json = json.loads((out / "mocks" / "package.json").read_text())
    assert "workspaces" in pkg_json

    # All workspace packages from the real Kratos mocks/ are bundled.
    src_pkgs = sorted(p.name for p in (kratos_repo / "mocks" / "packages").iterdir() if p.is_dir())
    dst_pkgs = sorted(p.name for p in (out / "mocks" / "packages").iterdir() if p.is_dir())
    assert dst_pkgs == src_pkgs


def test_assemble_writes_trimmed_infra(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    assert (out / "infra" / "main.bicep").is_file()
    assert (out / "infra" / "main.parameters.json").is_file()
    assert (out / "infra" / "abbreviations.json").is_file()

    # The 10 expected modules are present.
    expected_modules = {
        "network.bicep",
        "log-analytics.bicep",
        "app-insights.bicep",
        "key-vault.bicep",
        "cosmos-db.bicep",
        "ai-search.bicep",
        "ai-services.bicep",
        "blob-storage.bicep",
        "container-registry.bicep",
        "role-assignments.bicep",
    }
    actual_modules = {p.name for p in (out / "infra" / "modules").iterdir() if p.suffix == ".bicep"}
    assert actual_modules == expected_modules

    # Trimmed main.bicep does NOT reference the 5 dropped modules.
    main_bicep = (out / "infra" / "main.bicep").read_text()
    for dropped in (
        "agent-service.bicep",
        "container-apps-env.bicep",
        "ai-gateway.bicep",
        "static-web-app.bicep",
        "bing-search.bicep",
    ):
        assert dropped not in main_bicep, f"main.bicep still references dropped module {dropped}"

    # Trimmed role-assignments.bicep uses aiServicesPrincipalId, not agentServicePrincipalId.
    role_bicep = (out / "infra" / "modules" / "role-assignments.bicep").read_text()
    assert "param agentServicePrincipalId" not in role_bicep
    assert "param aiServicesPrincipalId" in role_bicep


def test_assemble_writes_root_files(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    assert (out / "azure.yaml").is_file()
    assert (out / "README.md").is_file()
    assert (out / ".env.template").is_file()
    assert (out / ".gitignore").is_file()
    assert (out / ".dockerignore").is_file()

    readme = (out / "README.md").read_text()
    assert "Finance Close Controller" in readme
    assert "azd up" in readme


def test_assemble_writes_postdeploy_hook_with_exec_bit(exporter: ProjectExporter, tmp_path: Path):
    """The RBAC-fixup hook must be rendered, marked executable, and survive zipping."""
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    hook = out / "hooks" / "postdeploy.sh"
    assert hook.is_file(), "hooks/postdeploy.sh must be rendered"
    # Owner+group+other exec bits — Foundry / azd run via /bin/sh.
    assert hook.stat().st_mode & 0o111, f"hook must be executable: mode={oct(hook.stat().st_mode)}"
    content = hook.read_text()
    assert content.startswith("#!/usr/bin/env bash"), "expected bash shebang"
    assert "azd ai agent show" in content, "hook must call azd ai agent show"
    assert "AcrPull" in content, "hook must grant AcrPull"
    assert "Cognitive Services OpenAI User" in content
    assert "Cognitive Services User" in content
    # No leftover azd literal escape ($$ → $) — the hook is bash, not azure.yaml.
    assert "$$" not in content, "hook should be plain bash (no $$ azure.yaml escapes)"

    # azure.yaml must wire the hook so `azd deploy` runs it.
    azyaml = (out / "azure.yaml").read_text()
    assert "postdeploy" in azyaml
    assert "./hooks/postdeploy.sh" in azyaml


def test_assemble_azure_yaml_hooks_are_cross_platform(exporter: ProjectExporter, tmp_path: Path):
    """Every azd hook must ship POSIX *and* Windows variants.

    Regression test for the Windows ``azd up`` failure: the exported hooks
    used to be ``shell: sh`` only, so on Windows (no bash/sh) azd could not
    run them. Each hook now declares a ``posix:`` (sh) and ``windows:``
    (pwsh) configuration.
    """
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    doc = yaml.safe_load((out / "azure.yaml").read_text())
    hooks = doc["hooks"]
    for event in ("predeploy", "preprovision", "postprovision", "postdeploy"):
        assert event in hooks, f"missing hook: {event}"
        assert "posix" in hooks[event], f"{event} missing posix variant"
        assert "windows" in hooks[event], f"{event} missing windows variant"
        assert hooks[event]["posix"]["shell"] == "sh"
        assert hooks[event]["windows"]["shell"] == "pwsh"

    # postdeploy points at the matching script per OS.
    assert hooks["postdeploy"]["posix"]["run"] == "./hooks/postdeploy.sh"
    assert hooks["postdeploy"]["windows"]["run"] == "./hooks/postdeploy.ps1"
    # Non-schema ``name:`` key must be gone (azure.yaml schema forbids it).
    assert "name:" not in (out / "azure.yaml").read_text().split("hooks:", 1)[1]


def test_assemble_writes_windows_postdeploy_hook(exporter: ProjectExporter, tmp_path: Path):
    """A PowerShell RBAC hook must ship so ``azd up`` works on Windows."""
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    hook = out / "hooks" / "postdeploy.ps1"
    assert hook.is_file(), "hooks/postdeploy.ps1 must be rendered for Windows"
    content = hook.read_text()

    # Same RBAC behaviour as the bash hook: discover identities + grant roles.
    assert "azd ai agent show" in content
    assert "az role assignment create" in content
    # Role GUIDs are pinned identically to the bash hook.
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in content  # AcrPull
    assert "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" in content  # Cognitive Services OpenAI User
    assert "53ca6127-db72-4b80-b1b0-d745d6d5456d" in content  # Foundry User

    # Persona name substituted; no leftover azure.yaml ``$$`` escapes.
    assert "Finance Close Controller" in content
    assert "$$" not in content, "ps1 should be plain PowerShell (no $$ azure.yaml escapes)"


def test_assemble_unknown_use_case_raises(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(FileNotFoundError):
        exporter.assemble("does-not-exist", out)


def test_assemble_missing_hosted_agent_raises(tmp_path: Path):
    # tmp_path doesn't have src/hosted-agent — should fail clearly.
    (tmp_path / "use-cases" / "x").mkdir(parents=True)
    (tmp_path / "use-cases" / "x" / "SYSTEM_PROMPT.md").write_text("---\nname: X\n---\n")
    exporter = ProjectExporter(repo_root=tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(FileNotFoundError, match="Hosted-agent dir not found"):
        exporter.assemble("x", out)


# ---------------------------------------------------------------------------
# Unit tests — build_zip()
# ---------------------------------------------------------------------------


def test_build_zip_includes_all_expected_paths(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)

    blob = ProjectExporter.build_zip(out)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())

    # Roots
    assert "azure.yaml" in names
    assert "README.md" in names
    # Hosted agent
    assert "src/hosted-agent/main.py" in names
    assert "src/hosted-agent/Dockerfile" in names
    assert "src/hosted-agent/agent.yaml" in names
    # Backend app
    assert "src/backend/app/services/copilot_agent.py" in names
    # Use case + mocks + infra
    assert "use-cases/finance-close/SYSTEM_PROMPT.md" in names
    assert "mocks/package.json" in names
    assert "infra/main.bicep" in names
    assert "infra/modules/role-assignments.bicep" in names

    # Junk dirs must be entirely absent.
    assert not any("__pycache__" in n for n in names)
    assert not any("evals/" in n for n in names)
    assert not any("exporter_templates" in n for n in names)


def test_build_zip_includes_windows_hook(exporter: ProjectExporter, tmp_path: Path):
    """Both the POSIX and Windows postdeploy hooks must land in the zip."""
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)
    blob = ProjectExporter.build_zip(out)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
    assert "hooks/postdeploy.sh" in names
    assert "hooks/postdeploy.ps1" in names


def test_build_zip_skips_other_use_cases(exporter: ProjectExporter, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)
    blob = ProjectExporter.build_zip(out)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    assert not any("marketing-launch" in n for n in names)


def test_build_zip_preserves_exec_bit_on_hooks(exporter: ProjectExporter, tmp_path: Path):
    """Unix permission bits on ./hooks/postdeploy.sh must survive zipping.

    Without this, users would have to `chmod +x hooks/postdeploy.sh` after
    `unzip`, and azd's hook runner would fail with permission denied.
    """
    out = tmp_path / "out"
    out.mkdir()
    exporter.assemble("finance-close", out)
    blob = ProjectExporter.build_zip(out)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        info = zf.getinfo("hooks/postdeploy.sh")
    mode = info.external_attr >> 16
    assert mode & 0o111, f"hook exec bit lost in zip: mode={oct(mode)}"


# ---------------------------------------------------------------------------
# Integration test — the /api/use-cases/{use_case}/export endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def export_client(kratos_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """Boot the FastAPI app with stubbed-out Azure deps and one registry."""
    monkeypatch.chdir(kratos_repo)

    from app.main import app

    # Bypass lifespan — set the bits the export router actually uses.
    registry_stub = MagicMock()
    registry_stub.system_prompt = ""
    app.state.registries = {"finance-close": registry_stub}

    blob_stub = MagicMock()
    blob_stub.local_base_dir = kratos_repo / "use-cases"
    app.state.blob_skill_service = blob_stub

    return TestClient(app, raise_server_exceptions=False)


def test_export_endpoint_streams_zip(export_client: TestClient):
    response = export_client.get("/api/use-cases/finance-close/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    assert 'filename="finance-close-foundry-agent.zip"' in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
    assert "azure.yaml" in names
    assert "src/hosted-agent/main.py" in names
    assert "src/hosted-agent/Dockerfile" in names
    assert "src/backend/app/services/copilot_agent.py" in names
    assert "infra/main.bicep" in names


def test_export_endpoint_unknown_use_case(export_client: TestClient):
    response = export_client.get("/api/use-cases/does-not-exist/export")
    assert response.status_code == 404


def test_export_endpoint_rejects_bad_name(export_client: TestClient):
    response = export_client.get("/api/use-cases/..%2Fetc/export")
    # FastAPI/Starlette returns 404 for path-traversal attempts in URL path
    # segments; either way the export router never sees an unsafe name.
    assert response.status_code in (400, 404)
