#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
USE_CASES_DIR = REPO_ROOT / "use-cases"
TOPOLOGY_PATH = REPO_ROOT / "infra" / "health-model" / "topology.json"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,258}[A-Za-z0-9]$")

FUNCTIONAL_SKILLS = {
    "web-search",
    "rag-search",
    "code-interpreter",
    "data-analysis",
    "crm",
    "claims-mgmt",
    "email-draft",
    "document-summary",
    "file-sharing",
    "docx-editor",
    "pptx-editor",
    "oee-analysis",
    "variance-analysis",
}


def sanitize_key(value: str) -> str:
    sanitized = re.sub(r"[:/._\s]+", "-", value.strip().lower())
    sanitized = re.sub(r"[^a-z0-9-]+", "-", sanitized)
    sanitized = sanitized.replace("microsoft", "msft").replace("azure", "az").replace("windows", "win")
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    if not sanitized:
        sanitized = "x-name"
    if not sanitized[0].isalnum():
        sanitized = f"a{sanitized}"
    if not sanitized[-1].isalnum():
        sanitized = f"{sanitized}a"
    if len(sanitized) < 3:
        sanitized = f"{sanitized}-x"
    if len(sanitized) > 260:
        sanitized = sanitized[:260]
        sanitized = sanitized.rstrip("-")
        if len(sanitized) < 3:
            sanitized = f"{sanitized}x"
        if not sanitized[-1].isalnum():
            sanitized = f"{sanitized}a"
    return sanitized


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    block = match.group(1)
    if yaml is not None:
        loaded = yaml.safe_load(block) or {}
        return loaded if isinstance(loaded, dict) else {}
    result: dict[str, Any] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value.lower() == "true":
            result[key.strip()] = True
        elif value.lower() == "false":
            result[key.strip()] = False
        else:
            result[key.strip()] = value
    return result


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _load_apm_lock(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
        return loaded if isinstance(loaded, dict) else {}

    result: dict[str, Any] = {}
    servers: list[str] = []
    in_mcp_servers = False
    for line in text.splitlines():
        if re.match(r"^\s*mcp_servers\s*:\s*$", line):
            in_mcp_servers = True
            continue
        if in_mcp_servers:
            if re.match(r"^\s*-\s*", line):
                servers.append(line.split("-", 1)[1].strip())
                continue
            if line.strip() and not line.startswith(" "):
                in_mcp_servers = False
    if servers:
        result["mcp_servers"] = servers
    return result


def _azure_downstream(key: str, display_name: str, resource_key: str) -> dict[str, str]:
    return {
        "key": key,
        "displayName": display_name,
        "kind": "AzureResource",
        "resourceKey": resource_key,
    }


def _external_downstream(key: str, display_name: str) -> dict[str, str]:
    return {
        "key": key,
        "displayName": display_name,
        "kind": "External",
    }


DOWNSTREAM_FOUNDRY = _azure_downstream("foundry", "LLM inference", "foundry")
DOWNSTREAM_SEARCH = _azure_downstream("search", "Knowledge base search", "search")
DOWNSTREAM_STORAGE = _azure_downstream("storage", "File storage", "storage")
DOWNSTREAM_AGENT_RUNTIME = _azure_downstream("agent-runtime", "Agent runtime", "agentApp")
DOWNSTREAM_COSMOS = _azure_downstream("cosmos", "Conversation store", "cosmos")
DOWNSTREAM_LOCAL = _external_downstream("local-data-compute", "Local data/compute")
DOWNSTREAM_M365_GRAPH = _external_downstream("microsoft-graph", "Microsoft Graph API")

MCP_DOWNSTREAMS: dict[str, dict[str, str]] = {
    "m365-graph": DOWNSTREAM_M365_GRAPH,
    "salesforce": _external_downstream("salesforce-api", "Salesforce API"),
    "workday": _external_downstream("workday-api", "Workday API"),
    "servicenow": _external_downstream("servicenow-api", "ServiceNow API"),
    "sap-s4": _external_downstream("sap-s4-api", "SAP S/4 API"),
    "epic-fhir": _external_downstream("epic-fhir-api", "Epic FHIR API"),
    "epic": _external_downstream("epic-fhir-api", "Epic FHIR API"),
    "azure-iot": _external_downstream("azure-iot-api", "Azure IoT API"),
    "faker": _external_downstream("core-banking-api", "Core Banking API"),
    "core-banking": _external_downstream("core-banking-api", "Core Banking API"),
    "microsoft-learn": _external_downstream("microsoft-learn-api", "Microsoft Learn API"),
}


def map_skill_to_downstreams(skill_name: str) -> list[dict[str, str]]:
    skill = skill_name.strip().lower()
    if skill == "web-search":
        return [DOWNSTREAM_FOUNDRY]
    if skill == "rag-search":
        return [DOWNSTREAM_SEARCH]
    if skill == "file-sharing":
        return [DOWNSTREAM_STORAGE]
    if skill == "code-interpreter":
        return [DOWNSTREAM_AGENT_RUNTIME]
    if skill in {"data-analysis", "email-draft", "document-summary", "foundry-agent"}:
        return [DOWNSTREAM_FOUNDRY]
    if skill.endswith("-pdf") or skill.endswith("-report"):
        return [DOWNSTREAM_FOUNDRY]
    if skill in MCP_DOWNSTREAMS:
        return [MCP_DOWNSTREAMS[skill]]
    return [DOWNSTREAM_LOCAL]


def map_mcp_to_downstreams(server_name: str) -> list[dict[str, str]]:
    normalized = server_name.strip().lower()
    downstream = MCP_DOWNSTREAMS.get(normalized)
    if downstream:
        return [downstream]
    display = f"{server_name} API"
    key = f"{sanitize_key(server_name)}-api"
    return [_external_downstream(key, display)]


def _enabled_skills(use_case_dir: Path) -> list[str]:
    skills: list[str] = []
    for skill_file in sorted(use_case_dir.glob("skills/*/SKILL.md")):
        meta = _frontmatter(skill_file)
        if _bool_value(meta.get("enabled", False)):
            skills.append(skill_file.parent.name)
    return skills


def _configured_mcp_servers(use_case_dir: Path) -> list[str]:
    servers: set[str] = set()
    mcp_file = use_case_dir / ".mcp.json"
    if mcp_file.exists():
        text = mcp_file.read_text(encoding="utf-8").strip()
        if text:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                servers.update(str(key) for key in loaded.keys())

    apm_lock = _load_apm_lock(use_case_dir / "apm.lock.yaml")
    for server in apm_lock.get("mcp_servers") or []:
        if isinstance(server, str):
            servers.add(server)
    return sorted(servers)


def _sorted_unique_downstreams(downstreams: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key: dict[str, dict[str, str]] = {}
    for downstream in downstreams:
        by_key[downstream["key"]] = dict(downstream)
    return [by_key[key] for key in sorted(by_key.keys())]


def _is_functional_tool(tool_key: str) -> bool:
    if tool_key.startswith("mcp:"):
        return True
    if tool_key.startswith("platform:"):
        return True
    if tool_key.startswith("skill:"):
        return tool_key.split(":", 1)[1] in FUNCTIONAL_SKILLS
    return False


def _mean(values: list[int]) -> float:
    return sum(values) / len(values)


def _build_layout_order(advisors: list[dict[str, Any]]) -> dict[str, list[str]]:
    advisor_order = [advisor["key"] for advisor in advisors]
    advisor_index = {key: idx for idx, key in enumerate(advisor_order)}

    tool_to_advisor_indices: dict[str, list[int]] = {}
    tool_to_service_keys: dict[str, set[str]] = {}
    service_to_tool_indices: dict[str, list[int]] = {}
    service_to_resource_keys: dict[str, set[str]] = {}

    for advisor in advisors:
        a_idx = advisor_index[advisor["key"]]
        for tool in advisor["tools"]:
            tool_key = tool["key"]
            tool_to_advisor_indices.setdefault(tool_key, []).append(a_idx)
            service_keys = tool_to_service_keys.setdefault(tool_key, set())
            for downstream in tool["downstreams"]:
                service_key = downstream["key"]
                service_keys.add(service_key)

    tool_order = sorted(
        tool_to_advisor_indices.keys(),
        key=lambda key: (_mean(tool_to_advisor_indices[key]), key),
    )
    tool_index = {key: idx for idx, key in enumerate(tool_order)}

    for tool_key in tool_order:
        t_idx = tool_index[tool_key]
        for service_key in sorted(tool_to_service_keys.get(tool_key, set())):
            service_to_tool_indices.setdefault(service_key, []).append(t_idx)

    service_order = sorted(
        service_to_tool_indices.keys(),
        key=lambda key: (_mean(service_to_tool_indices[key]), key),
    )
    service_index = {key: idx for idx, key in enumerate(service_order)}

    resource_to_service_indices: dict[str, list[int]] = {}
    for service_key in service_order:
        s_idx = service_index[service_key]
        for advisor in advisors:
            for tool in advisor["tools"]:
                for downstream in tool["downstreams"]:
                    if downstream["key"] != service_key:
                        continue
                    if downstream.get("kind") == "AzureResource" and downstream.get("resourceKey"):
                        resource_key = str(downstream["resourceKey"])
                        service_to_resource_keys.setdefault(service_key, set()).add(resource_key)
                        resource_to_service_indices.setdefault(resource_key, []).append(s_idx)

    resource_order = sorted(
        resource_to_service_indices.keys(),
        key=lambda key: (_mean(resource_to_service_indices[key]), key),
    )

    return {
        "advisor": advisor_order,
        "tool": tool_order,
        "service": service_order,
        "resource": resource_order,
    }


def _validate_scope_uniqueness(
    keys: list[str],
    scope: str,
    *,
    require_raw_name_valid: bool = False,
) -> None:
    by_sanitized: dict[str, str] = {}
    for key in keys:
        if require_raw_name_valid and not NAME_RE.fullmatch(key):
            raise ValueError(f"Key {key!r} is not a valid emitted entity name in {scope}")
        sanitized = sanitize_key(key)
        if not NAME_RE.fullmatch(sanitized):
            raise ValueError(f"Key {key!r} sanitizes to invalid entity name {sanitized!r}")
        existing = by_sanitized.get(sanitized)
        if existing is not None and existing != key:
            raise ValueError(
                f"Sanitized name collision in {scope}: {existing!r} and {key!r} -> {sanitized!r}"
            )
        by_sanitized[sanitized] = key


def _validate_topology(topology: dict[str, Any]) -> None:
    advisors = topology["advisors"]
    layout = topology["layoutOrder"]

    advisor_keys = [advisor["key"] for advisor in advisors]
    _validate_scope_uniqueness(advisor_keys, "advisors", require_raw_name_valid=True)
    if layout["advisor"] != advisor_keys:
        raise ValueError("layoutOrder.advisor does not match advisor keys")

    for advisor in advisors:
        tool_keys = [tool["key"] for tool in advisor["tools"]]
        _validate_scope_uniqueness(tool_keys, f"tools for advisor {advisor['key']}")
        for tool in advisor["tools"]:
            downstream_keys = [downstream["key"] for downstream in tool["downstreams"]]
            _validate_scope_uniqueness(
                downstream_keys,
                f"downstreams for tool {tool['key']} in advisor {advisor['key']}",
            )

    for tier in ("advisor", "tool", "service", "resource"):
        values = layout[tier]
        if len(values) != len(set(values)):
            raise ValueError(f"layoutOrder.{tier} contains duplicates")
        _validate_scope_uniqueness(list(values), f"layoutOrder.{tier}")

    used_tool_keys = {
        tool["key"]
        for advisor in advisors
        for tool in advisor["tools"]
    }
    if used_tool_keys != set(layout["tool"]):
        raise ValueError("layoutOrder.tool does not match used tool keys")

    used_service_keys = {
        downstream["key"]
        for advisor in advisors
        for tool in advisor["tools"]
        for downstream in tool["downstreams"]
    }
    if used_service_keys != set(layout["service"]):
        raise ValueError("layoutOrder.service does not match used service keys")

    used_resource_keys = {
        str(downstream["resourceKey"])
        for advisor in advisors
        for tool in advisor["tools"]
        for downstream in tool["downstreams"]
        if downstream.get("kind") == "AzureResource" and downstream.get("resourceKey")
    }
    if used_resource_keys != set(layout["resource"]):
        raise ValueError("layoutOrder.resource does not match used resource keys")

    _validate_scope_uniqueness(
        [f"adv-{key}" for key in advisor_keys],
        "emitted advisor entity names",
        require_raw_name_valid=True,
    )
    _validate_scope_uniqueness(
        [f"tool-{sanitize_key(key)}" for key in layout["tool"]],
        "emitted tool entity names",
        require_raw_name_valid=True,
    )
    _validate_scope_uniqueness(
        [f"svc-{sanitize_key(key)}" for key in layout["service"]],
        "emitted service entity names",
        require_raw_name_valid=True,
    )
    _validate_scope_uniqueness(
        [f"res-{key}" for key in layout["resource"]],
        "emitted resource entity names",
        require_raw_name_valid=True,
    )


def build_topology(use_cases_dir: Path = USE_CASES_DIR) -> dict[str, Any]:
    advisors: list[dict[str, Any]] = []
    for use_case_dir in sorted(p for p in use_cases_dir.iterdir() if p.is_dir()):
        system_prompt = use_case_dir / "SYSTEM_PROMPT.md"
        if not system_prompt.exists():
            continue

        meta = _frontmatter(system_prompt)
        advisor_key = sanitize_key(use_case_dir.name)
        display_name = str(meta.get("name", advisor_key))
        curated = _bool_value(meta.get("curated", False))

        tools_by_key: dict[str, dict[str, Any]] = {}
        for skill_name in _enabled_skills(use_case_dir):
            tool_key = f"skill:{skill_name}"
            if not _is_functional_tool(tool_key):
                continue
            tools_by_key[tool_key] = {
                "key": tool_key,
                "displayName": skill_name,
                "kind": "skill",
                "downstreams": _sorted_unique_downstreams(map_skill_to_downstreams(skill_name)),
            }

        for server_name in _configured_mcp_servers(use_case_dir):
            tool_key = f"mcp:{server_name}"
            tools_by_key[tool_key] = {
                "key": tool_key,
                "displayName": server_name,
                "kind": "mcp",
                "downstreams": _sorted_unique_downstreams(map_mcp_to_downstreams(server_name)),
            }

        tools_by_key["platform:llm"] = {
            "key": "platform:llm",
            "displayName": "Platform LLM",
            "kind": "skill",
            "downstreams": [dict(DOWNSTREAM_FOUNDRY)],
        }
        tools_by_key["platform:state"] = {
            "key": "platform:state",
            "displayName": "Platform state",
            "kind": "skill",
            "downstreams": [dict(DOWNSTREAM_COSMOS)],
        }

        tools = [tools_by_key[key] for key in sorted(tools_by_key.keys())]
        for tool in tools:
            tool["downstreams"] = _sorted_unique_downstreams(tool["downstreams"])

        advisors.append(
            {
                "key": advisor_key,
                "displayName": display_name,
                "curated": curated,
                "tools": tools,
            }
        )

    advisors = sorted(advisors, key=lambda advisor: advisor["key"])
    layout_order = _build_layout_order(advisors)
    topology = {
        "advisors": advisors,
        "layoutOrder": layout_order,
    }
    _validate_topology(topology)
    return topology


def render_topology_json(topology: dict[str, Any]) -> str:
    return json.dumps(topology, indent=2) + "\n"


def _counts(topology: dict[str, Any]) -> tuple[int, int]:
    advisor_count = len(topology.get("advisors", []))
    tool_count = len(topology.get("layoutOrder", {}).get("tool", []))
    return advisor_count, tool_count


def write_topology_file(output_path: Path = TOPOLOGY_PATH, use_cases_dir: Path = USE_CASES_DIR) -> dict[str, Any]:
    topology = build_topology(use_cases_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_topology_json(topology), encoding="utf-8")
    return topology


def check_topology_file(output_path: Path = TOPOLOGY_PATH, use_cases_dir: Path = USE_CASES_DIR) -> bool:
    expected = render_topology_json(build_topology(use_cases_dir))
    if not output_path.exists():
        return False
    actual = output_path.read_text(encoding="utf-8")
    return actual == expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate health model topology from use-case config.")
    parser.add_argument("--check", action="store_true", help="Fail if topology.json is stale")
    args = parser.parse_args()

    if args.check:
        if check_topology_file():
            topology = build_topology(USE_CASES_DIR)
            advisor_count, tool_count = _counts(topology)
            print(
                f"topology.json is up to date (advisors={advisor_count}, distinctTools={tool_count})."
            )
            return 0
        print("topology.json is stale. Run: python3 scripts/gen_health_topology.py")
        return 1

    topology = write_topology_file()
    advisor_count, tool_count = _counts(topology)
    relative = TOPOLOGY_PATH.relative_to(REPO_ROOT)
    print(f"Wrote {relative} (advisors={advisor_count}, distinctTools={tool_count}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
