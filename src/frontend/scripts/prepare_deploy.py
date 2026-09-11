from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "out"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base_path = os.environ.get("NEXT_PUBLIC_BASE_PATH", "").rstrip("/")
    agent_service_url = os.environ.get("AGENT_SERVICE_URL", "")
    config_path = OUT / "config.json"
    config: dict[str, object] = {}

    if base_path:
        config["apiUrl"] = base_path
        print(
            f"Injected same-origin config.json with apiUrl={base_path} (behind Front Door)"
        )
    elif agent_service_url:
        config["apiUrl"] = agent_service_url
        print(f"Injected config.json with apiUrl={agent_service_url}")

    client_id = os.environ.get("OBO_CLIENT_APP_CLIENT_ID", "")
    tenant_id = os.environ.get("OBO_TENANT_ID", "")
    identifier_uri = os.environ.get("OBO_SERVER_APP_IDENTIFIER_URI", "")
    if client_id and tenant_id and identifier_uri:
        scope = f"{identifier_uri}/{os.environ.get('OBO_SERVER_APP_SCOPE_VALUE', 'access_as_user')}"
        config["auth"] = {
            "clientId": client_id,
            "tenantId": tenant_id,
            "mcpScope": scope,
            "mcpServerName": os.environ.get("OBO_MCP_SERVER_NAME", "graph-obo"),
        }
        print(f"Merged OBO auth config into config.json (scope={scope})")

    if config:
        config_path.write_text(
            json.dumps(config, separators=(",", ":")), encoding="utf-8"
        )

    source = ROOT / "staticwebapp.config.json"
    destination = OUT / "staticwebapp.config.json"
    if source.is_file():
        if base_path:
            content = source.read_text(encoding="utf-8")
            content = content.replace(
                "/.auth/login/aad", f"{base_path}/.auth/login/aad"
            )
            content = content.replace('"/api/*"', f'"{base_path}/api/*"')
            destination.write_text(content, encoding="utf-8")
            print(
                f"Wrote basePath-aware staticwebapp.config.json (basePath={base_path})"
            )
        else:
            shutil.copyfile(source, destination)
    return 0


raise SystemExit(main())
