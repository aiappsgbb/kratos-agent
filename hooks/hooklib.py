from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
USE_CASES_DIR = ROOT / "use-cases"
ROLE_MODULE = ROOT / "infra" / "modules" / "agent-role-assignments.bicep"
CONTAINER_NAME = "skills"
MS_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
GRAPH_SCOPE = "User.Read"


def run(
    args: list[str],
    *,
    check: bool = False,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def output(args: list[str]) -> str:
    result = run(args)
    return result.stdout.strip() if result.returncode == 0 else ""


def available_use_cases() -> list[str]:
    if not USE_CASES_DIR.is_dir():
        return []
    return sorted(path.name for path in USE_CASES_DIR.iterdir() if path.is_dir())


def selection_file() -> Path:
    env_name = os.environ.get("AZURE_ENV_NAME", "default")
    return ROOT / ".azure" / env_name / "kratos-upload-selection"


def write_selection(value: str) -> None:
    path = selection_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n", encoding="utf-8")


def read_selection() -> str:
    path = selection_file()
    if not path.is_file():
        return ""
    value = path.read_text(encoding="utf-8").strip()
    path.unlink(missing_ok=True)
    return value


def choose_use_cases() -> int:
    path = selection_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    use_cases = available_use_cases()
    if not use_cases:
        write_selection("none")
        return 0

    requested = os.environ.get("KRATOS_UPLOAD_USE_CASES", "").strip()
    if requested:
        write_selection(requested)
        print(f"Skills upload: '{requested}' (from KRATOS_UPLOAD_USE_CASES).")
        return 0

    if os.environ.get("KRATOS_AUTO_UPLOAD_USE_CASES", "0") == "1":
        write_selection("all")
        print("Skills upload: all (from KRATOS_AUTO_UPLOAD_USE_CASES=1).")
        return 0

    if not sys.stdin.isatty():
        write_selection("none")
        print(
            "Skills upload: skipped (no terminal). Set KRATOS_UPLOAD_USE_CASES=all to upload."
        )
        return 0

    print()
    print("+----------------------------------------------------------+")
    print("|  Which skills should be uploaded after the deploy?       |")
    print("+----------------------------------------------------------+")
    print()
    for index, use_case in enumerate(use_cases, start=1):
        print(f"   {index:2}. {use_case}")
    print()
    print("    A. All of them")
    print("    N. None - skip the upload (default)")
    print()
    print("  Numbers may be combined, e.g. 1,3,8")
    print()

    selection = "none"
    for attempt in range(3):
        try:
            reply = input("  Your choice [A/N/numbers]: ").strip().replace(" ", "")
        except EOFError:
            reply = ""
        if not reply or reply.lower() in {"n", "s"}:
            break
        if reply.lower() == "a":
            selection = "all"
            break

        resolved: list[str] = []
        invalid: list[str] = []
        for part in reply.split(","):
            if part.isdigit() and 1 <= int(part) <= len(use_cases):
                resolved.append(use_cases[int(part) - 1])
            else:
                invalid.append(part)
        if resolved and not invalid:
            selection = ",".join(resolved)
            break
        if attempt < 2:
            detail = " ".join(invalid) if invalid else "(nothing selected)"
            print(f"  Not a valid choice: {detail}. Try again.")
        else:
            print("  Still not a valid choice - skipping the upload.")

    write_selection(selection)
    if selection == "none":
        print("  Skills upload: skipped.")
    else:
        print(f"  Skills upload: {selection} (runs after the deploy).")
    return 0


def set_build_timestamp() -> int:
    build_timestamp = str(int(time.time()))
    result = run(
        ["azd", "env", "set", "KRATOS_BUILD_TS", build_timestamp], capture=False
    )
    if result.returncode == 0:
        print(f"KRATOS_BUILD_TS={build_timestamp} (forces new hosted-agent version)")
    return result.returncode


def set_tenant_id() -> None:
    if os.environ.get("AZURE_TENANT_ID"):
        return
    tenant_id = output(["az", "account", "show", "--query", "tenantId", "-o", "tsv"])
    if tenant_id:
        result = run(["azd", "env", "set", "AZURE_TENANT_ID", tenant_id], capture=False)
        if result.returncode == 0:
            print(f"Set AZURE_TENANT_ID={tenant_id}")


def grant_obo_consent() -> None:
    if os.environ.get("DEPLOY_OBO", "true").lower() not in {"1", "true", "yes"}:
        return
    app_id = os.environ.get("OBO_SERVER_APP_CLIENT_ID", "").strip()
    if not app_id:
        return

    print(f"Granting admin consent for the OBO server app's Graph {GRAPH_SCOPE} ...")
    client_sp_id = output(
        ["az", "ad", "sp", "show", "--id", app_id, "--query", "id", "-o", "tsv"]
    )
    graph_sp_id = output(
        [
            "az",
            "ad",
            "sp",
            "show",
            "--id",
            MS_GRAPH_APP_ID,
            "--query",
            "id",
            "-o",
            "tsv",
        ]
    )
    if client_sp_id and graph_sp_id:
        existing = output(
            [
                "az",
                "rest",
                "--method",
                "GET",
                "--url",
                (
                    "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?"
                    f"$filter=clientId eq '{client_sp_id}' and resourceId eq '{graph_sp_id}'"
                ),
                "--query",
                "value[].scope",
                "-o",
                "tsv",
            ]
        )
        if GRAPH_SCOPE in existing.split():
            print("   Admin consent already in place (nothing to do).")
            return

        body = json.dumps(
            {
                "clientId": client_sp_id,
                "consentType": "AllPrincipals",
                "resourceId": graph_sp_id,
                "scope": GRAPH_SCOPE,
            }
        )
        result = run(
            [
                "az",
                "rest",
                "--method",
                "POST",
                "--url",
                "https://graph.microsoft.com/v1.0/oauth2PermissionGrants",
                "--headers",
                "Content-Type=application/json",
                "--body",
                body,
            ]
        )
        if result.returncode == 0:
            print("   Admin consent granted.")
            return
        error = result.stderr
        if re.search(
            r"Authorization_RequestDenied|Insufficient privileges|Forbidden",
            error,
            re.IGNORECASE,
        ):
            print(
                "   Your account cannot grant tenant-wide admin consent; deployment can continue."
            )
            print(
                "   This requires an Entra directory administrator role, not Azure subscription Owner."
            )
        else:
            print("   The consent request failed for an unexpected reason:")
            print("\n".join(f"      {line}" for line in error.splitlines()[:10]))
    else:
        print("   Could not resolve the service principals needed for the grant.")

    print(
        f"   OBO still works, but the first user will be asked to consent to Graph {GRAPH_SCOPE}."
    )
    print("   An administrator can grant consent later with:")
    print(f"     az ad app permission admin-consent --id {app_id}")


def postprovision() -> int:
    set_tenant_id()
    print("Post-provisioning: configuring services...")
    grant_obo_consent()
    print("Deployment complete.")
    return 0


def _resource_name(endpoint: str) -> str:
    return (
        urlparse(endpoint).hostname.split(".", maxsplit=1)[0]
        if urlparse(endpoint).hostname
        else ""
    )


def _agent_principal_ids(prefix: str) -> list[str]:
    for attempt in range(1, 13):
        result = run(
            [
                "az",
                "ad",
                "sp",
                "list",
                "--display-name",
                prefix,
                "--query",
                "[?ends_with(displayName, '-AgentIdentity')].id",
                "-o",
                "tsv",
            ]
        )
        principal_ids = [
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        if principal_ids:
            return principal_ids
        if attempt < 12:
            print(
                f"   Hosted-agent identity not visible yet; retrying ({attempt}/12)..."
            )
            time.sleep(10)
    return []


def assign_agent_roles() -> bool:
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "").strip()
    project_id = os.environ.get("AZURE_AI_PROJECT_ID", "").strip()
    cosmos_name = _resource_name(os.environ.get("AZURE_COSMOS_DB_ENDPOINT", ""))
    storage_account = os.environ.get("AZURE_BLOB_STORAGE_ACCOUNT_NAME", "").strip()
    key_vault_name = _resource_name(os.environ.get("AZURE_KEY_VAULT_URI", ""))
    project_match = re.search(r"/accounts/([^/]+)/projects/([^/]+)", project_id)

    if not subscription_id or not resource_group or not project_match:
        print(
            "ERROR: AZURE_AI_PROJECT_ID, AZURE_SUBSCRIPTION_ID, or AZURE_RESOURCE_GROUP is missing."
        )
        return False
    if not ROLE_MODULE.is_file():
        print(f"ERROR: {ROLE_MODULE.relative_to(ROOT)} was not found.")
        return False

    foundry_account, foundry_project = project_match.groups()
    if not all((cosmos_name, storage_account, key_vault_name)):
        print("ERROR: Could not derive all resource names from the azd environment.")
        return False

    print()
    print("Assigning least-privilege roles to hosted agent(s)")
    print(f"  Foundry account : {foundry_account}")
    print(f"  Foundry project : {foundry_project}")

    prefix = f"{foundry_account}-{foundry_project}-"
    principal_ids = _agent_principal_ids(prefix)
    if not principal_ids:
        print(
            f"ERROR: No '*-AgentIdentity' service principal found for prefix '{prefix}'."
        )
        return False
    for principal_id in principal_ids:
        print(f"  Discovered agent identity: {principal_id}")

    result = run(
        [
            "az",
            "deployment",
            "group",
            "create",
            "--name",
            "kratos-agent-role-assignments",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--template-file",
            str(ROLE_MODULE),
            "--parameters",
            f"agentPrincipalIds={json.dumps(principal_ids)}",
            f"cosmosDbAccountName={cosmos_name}",
            f"aiServicesName={foundry_account}",
            f"keyVaultName={key_vault_name}",
            f"storageAccountName={storage_account}",
            "--only-show-errors",
        ]
    )
    if result.returncode == 0:
        print("   Hosted-agent role assignments applied.")
        print("   Data-plane propagation can take a few minutes.")
        return True

    error = result.stderr
    fatal_codes = (
        "AuthorizationFailed",
        "InvalidTemplate",
        "InvalidTemplateDeployment",
        "PrincipalNotFound",
        "LinkedAuthorizationFailed",
    )
    if "RoleAssignmentExists" in error and not any(
        code in error for code in fatal_codes
    ):
        print("   Hosted-agent role assignments already exist (nothing to do).")
        return True

    print("ERROR: Hosted-agent role-assignment deployment failed.")
    print(
        "       Verify the deploying principal has Owner or User Access Administrator."
    )
    print("\n".join(f"       {line}" for line in error.splitlines()[:20]))
    return False


def _selected_use_cases(selection: str, use_cases: list[str]) -> list[str]:
    if selection == "all":
        return use_cases
    selected: list[str] = []
    for part in selection.split(","):
        value = part.strip()
        if not value:
            continue
        if value.isdigit() and 1 <= int(value) <= len(use_cases):
            selected.append(use_cases[int(value) - 1])
        elif value in use_cases:
            selected.append(value)
        else:
            print(f"WARNING: Unknown use-case: {value}")
    return selected


def upload_skills() -> None:
    storage_account = os.environ.get("AZURE_BLOB_STORAGE_ACCOUNT_NAME", "").strip()
    if not storage_account:
        print(
            "WARNING: AZURE_BLOB_STORAGE_ACCOUNT_NAME is not set. Skipping skills upload."
        )
        return
    use_cases = available_use_cases()
    if not use_cases:
        print("WARNING: No use-cases found. Skipping skills upload.")
        return

    selection = (
        os.environ.get("KRATOS_UPLOAD_USE_CASES", "").strip() or read_selection()
    )
    if not selection and os.environ.get("KRATOS_AUTO_UPLOAD_USE_CASES", "0") == "1":
        selection = "all"
    if not selection:
        print("No skills selection was recorded, so nothing was uploaded.")
        print(
            "Run 'azd hooks run preprovision --interactive' before retrying the postdeploy hook."
        )
        return
    if selection == "none":
        print("Skipping skills upload.")
        return

    selected = _selected_use_cases(selection, use_cases)
    if not selected:
        print("No valid use-cases selected. Skipping.")
        return

    probe = run(
        [
            "az",
            "storage",
            "blob",
            "list",
            "--account-name",
            storage_account,
            "--container-name",
            CONTAINER_NAME,
            "--num-results",
            "1",
            "--auth-mode",
            "login",
            "--only-show-errors",
        ]
    )
    if probe.returncode != 0:
        print(
            f"WARNING: Storage account '{storage_account}' is not reachable; skills upload was skipped."
        )
        if re.search(
            r"AuthorizationFailure|network rule|not authorized|public access",
            probe.stderr,
            re.IGNORECASE,
        ):
            print(
                "         The account denies traffic from this network; use a host inside the virtual network."
            )
        else:
            first_line = next(
                iter(probe.stderr.splitlines()), "unknown Azure CLI error"
            )
            print(f"         Cause: {first_line}")
        print(
            "         This is non-fatal because the backend image contains the same use-cases."
        )
        return

    failed: list[str] = []
    for use_case in selected:
        print(f"Uploading '{use_case}' to blob://{CONTAINER_NAME}/{use_case}/ ...")
        existing = output(
            [
                "az",
                "storage",
                "blob",
                "list",
                "--account-name",
                storage_account,
                "--container-name",
                CONTAINER_NAME,
                "--prefix",
                f"use-cases/{use_case}/",
                "--auth-mode",
                "login",
                "--query",
                "[?!contains(name, '/evals/runs/')].name",
                "--output",
                "tsv",
            ]
        )
        for blob_name in existing.splitlines():
            run(
                [
                    "az",
                    "storage",
                    "blob",
                    "delete",
                    "--account-name",
                    storage_account,
                    "--container-name",
                    CONTAINER_NAME,
                    "--name",
                    blob_name.strip(),
                    "--auth-mode",
                    "login",
                    "--only-show-errors",
                ]
            )

        upload = run(
            [
                "az",
                "storage",
                "blob",
                "upload-batch",
                "--account-name",
                storage_account,
                "--destination",
                CONTAINER_NAME,
                "--source",
                str(USE_CASES_DIR / use_case),
                "--destination-path",
                f"use-cases/{use_case}",
                "--auth-mode",
                "login",
                "--overwrite",
                "--only-show-errors",
            ],
            capture=False,
        )
        if upload.returncode == 0:
            print(f"   '{use_case}' uploaded successfully.")
        else:
            failed.append(use_case)

    if failed:
        print(f"WARNING: Skills upload failed for: {', '.join(failed)}")
        print(
            "         The deployed app still serves the copy baked into its container image."
        )
    else:
        print("Skills upload complete.")


def postdeploy() -> int:
    if not assign_agent_roles():
        return 1
    upload_skills()
    return 0
