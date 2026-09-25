#!/usr/bin/env python3
"""Static checks for the azd hooks, run by the `hooks-lint` CI job.

Every hook exists twice (POSIX sh and Windows pwsh) and nothing else in CI
exercises either variant, so this enforces the invariants that keep them from
drifting apart:

  * every hook in azure.yaml declares both a `posix:` and a `windows:` variant,
    and the Windows one runs under pwsh;
  * every hooks/*.sh has a hooks/*.ps1 counterpart and vice versa;
  * every hooks/*.sh is committed executable (the posix hooks invoke them as
    ./hooks/x.sh, so a 100644 script fails every macOS/Linux provision).

It also writes each inline `windows:` run block to OUT_DIR so the workflow can
feed them to the PowerShell parser alongside hooks/*.ps1.
"""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".hooks-inline"


def main() -> int:
    errors: list[str] = []
    config = yaml.safe_load((ROOT / "azure.yaml").read_text())

    hooks = [(f"hooks.{name}", spec) for name, spec in (config.get("hooks") or {}).items()]
    for svc_name, svc in (config.get("services") or {}).items():
        for name, spec in (svc.get("hooks") or {}).items():
            hooks.append((f"services.{svc_name}.hooks.{name}", spec))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, spec in hooks:
        missing = [p for p in ("posix", "windows") if p not in (spec or {})]
        if missing:
            errors.append(f"azure.yaml {path}: missing {' and '.join(missing)} variant")
            continue
        windows = spec["windows"]
        if windows.get("shell") != "pwsh":
            errors.append(f"azure.yaml {path}.windows: shell must be pwsh, got {windows.get('shell')!r}")
        if windows.get("run"):
            (OUT_DIR / f"{path}.ps1").write_text(windows["run"])

    hook_dir = ROOT / "hooks"
    sh = {p.stem for p in hook_dir.glob("*.sh")}
    ps1 = {p.stem for p in hook_dir.glob("*.ps1")}
    errors += [f"hooks/{name}.sh has no hooks/{name}.ps1 counterpart" for name in sorted(sh - ps1)]
    errors += [f"hooks/{name}.ps1 has no hooks/{name}.sh counterpart" for name in sorted(ps1 - sh)]

    staged = subprocess.run(
        ["git", "ls-files", "-s", "--", "hooks/*.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for line in staged:
        mode, _, _, file = line.split(maxsplit=3)
        if mode != "100755":
            errors.append(f"{file} is committed as {mode}; run: git update-index --chmod=+x {file}")

    for error in errors:
        print(f"::error::{error}")
    print(f"Checked {len(hooks)} azure.yaml hooks and {len(sh | ps1)} hook scripts; {len(errors)} problem(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
