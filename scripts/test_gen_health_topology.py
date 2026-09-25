from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
USE_CASES_DIR = REPO_ROOT / "use-cases"
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_health_topology.py"

DROPPED_SKILLS = {
    "skill:account-brief-pdf",
    "skill:loan-calculator",
    "skill:it-policy-reference",
    "skill:ticket-actions",
    "skill:portfolio-review",
}


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("gen_health_topology", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator module from {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}
    _, yaml_block, _ = text.split("---\n", 2)
    loaded = yaml.safe_load(yaml_block) or {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _expected_use_case_dirs() -> list[Path]:
    return sorted(
        p for p in USE_CASES_DIR.iterdir() if p.is_dir() and (p / "SYSTEM_PROMPT.md").exists()
    )


def _configured_mcp_servers(use_case_dir: Path) -> set[str]:
    servers: set[str] = set()
    mcp_path = use_case_dir / ".mcp.json"
    if mcp_path.exists():
        text = mcp_path.read_text(encoding="utf-8").strip()
        if text:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                servers.update(str(key) for key in loaded.keys())

    apm_lock_path = use_case_dir / "apm.lock.yaml"
    if apm_lock_path.exists():
        lock_text = apm_lock_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        loaded = yaml.safe_load(lock_text) or {}
        if isinstance(loaded, dict):
            for server in loaded.get("mcp_servers") or []:
                if isinstance(server, str):
                    servers.add(server)
    return servers


def _all_tool_keys(topology: dict[str, Any]) -> set[str]:
    return {
        tool["key"]
        for advisor in topology["advisors"]
        for tool in advisor["tools"]
    }


def test_advisors_match_use_cases_and_persona_names():
    generator = _load_generator_module()
    topology = generator.build_topology(USE_CASES_DIR)

    expected_dirs = _expected_use_case_dirs()
    advisors = topology["advisors"]
    assert len(advisors) == len(expected_dirs)

    advisors_by_key = {advisor["key"]: advisor for advisor in advisors}
    expected_keys = [generator.sanitize_key(path.name) for path in expected_dirs]
    assert topology["layoutOrder"]["advisor"] == sorted(expected_keys)

    for use_case_dir in expected_dirs:
        key = generator.sanitize_key(use_case_dir.name)
        persona = str(_frontmatter(use_case_dir / "SYSTEM_PROMPT.md").get("name", key))
        assert advisors_by_key[key]["displayName"] == persona


def test_dropped_skills_are_absent_and_functional_insurance_tools_present():
    generator = _load_generator_module()
    topology = generator.build_topology(USE_CASES_DIR)
    all_tool_keys = _all_tool_keys(topology)

    assert DROPPED_SKILLS.isdisjoint(all_tool_keys)

    advisors_by_key = {advisor["key"]: advisor for advisor in topology["advisors"]}
    insurance_tools = {tool["key"] for tool in advisors_by_key["insurance"]["tools"]}
    assert {"skill:rag-search", "skill:web-search", "skill:crm", "platform:llm"}.issubset(
        insurance_tools
    )


def test_layout_order_tool_is_deduped_and_covers_all_used_tools():
    generator = _load_generator_module()
    topology = generator.build_topology(USE_CASES_DIR)

    layout_tools = topology["layoutOrder"]["tool"]
    used_tools = _all_tool_keys(topology)

    assert len(layout_tools) == len(set(layout_tools))
    assert set(layout_tools) == used_tools


def test_disabled_skill_is_not_emitted_from_synthetic_tree(tmp_path: Path):
    generator = _load_generator_module()

    uc_dir = tmp_path / "use-cases" / "azure_iot"
    (uc_dir / "skills" / "web-search").mkdir(parents=True)
    (uc_dir / "skills" / "code-interpreter").mkdir(parents=True)

    (uc_dir / "SYSTEM_PROMPT.md").write_text(
        "---\nname: Demo Case\ncurated: false\n---\nDemo\n",
        encoding="utf-8",
    )
    (uc_dir / ".mcp.json").write_text("{\n}\n", encoding="utf-8")
    (uc_dir / "skills" / "web-search" / "SKILL.md").write_text(
        "---\nname: web-search\nenabled: true\n---\n",
        encoding="utf-8",
    )
    (uc_dir / "skills" / "code-interpreter" / "SKILL.md").write_text(
        "---\nname: code-interpreter\nenabled: false\n---\n",
        encoding="utf-8",
    )

    topology = generator.build_topology(tmp_path / "use-cases")
    advisor = topology["advisors"][0]
    tools = {tool["key"] for tool in advisor["tools"]}
    assert advisor["key"] == "az-iot"
    assert "skill:web-search" in tools
    assert "skill:code-interpreter" not in tools


def test_mcp_tool_with_underscore_emits_valid_entity_name(tmp_path: Path):
    generator = _load_generator_module()

    uc_dir = tmp_path / "use-cases" / "generic"
    uc_dir.mkdir(parents=True)
    (uc_dir / "SYSTEM_PROMPT.md").write_text(
        "---\nname: Generic\ncurated: false\n---\nDemo\n",
        encoding="utf-8",
    )
    (uc_dir / ".mcp.json").write_text('{"sap_s4": {}}\n', encoding="utf-8")

    topology = generator.build_topology(tmp_path / "use-cases")
    advisor = topology["advisors"][0]
    tool_keys = {tool["key"] for tool in advisor["tools"]}
    assert "mcp:sap_s4" in tool_keys

    emitted_tool_name = f"tool-{generator.sanitize_key('mcp:sap_s4')}"
    assert generator.NAME_RE.fullmatch(emitted_tool_name)
    assert "_" not in emitted_tool_name
    assert generator.sanitize_key("mcp:Microsoft-Learn") == "mcp-msft-learn"


def test_empty_mcp_config_yields_no_mcp_tools():
    generator = _load_generator_module()
    topology = generator.build_topology(USE_CASES_DIR)
    advisors_by_key = {advisor["key"]: advisor for advisor in topology["advisors"]}

    wealth_tools = {tool["key"] for tool in advisors_by_key["wealth-management"]["tools"]}
    assert _configured_mcp_servers(USE_CASES_DIR / "wealth-management") == set()
    assert not any(tool.startswith("mcp:") for tool in wealth_tools)


def test_check_topology_file_is_stable_for_generated_content(tmp_path: Path):
    generator = _load_generator_module()
    output_path = tmp_path / "topology.json"

    generator.write_topology_file(output_path=output_path, use_cases_dir=USE_CASES_DIR)
    assert generator.check_topology_file(output_path=output_path, use_cases_dir=USE_CASES_DIR)

    output_path.write_text("{}\n", encoding="utf-8")
    assert not generator.check_topology_file(output_path=output_path, use_cases_dir=USE_CASES_DIR)


def test_repo_topology_file_is_in_sync():
    generator = _load_generator_module()
    assert generator.check_topology_file()
