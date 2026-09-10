from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hooks import hooklib


def completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class HookTests(unittest.TestCase):
    def test_agent_principal_ids_normalizes_windows_line_endings(self) -> None:
        with (
            patch.object(
                hooklib, "run", return_value=completed("first-id\r\nsecond-id\r\n")
            ),
            patch.object(hooklib.time, "sleep"),
        ):
            self.assertEqual(
                hooklib._agent_principal_ids("prefix-"), ["first-id", "second-id"]
            )

    def test_selected_use_cases_accepts_names_and_numbers(self) -> None:
        self.assertEqual(
            hooklib._selected_use_cases(
                "2,insurance",
                ["generic", "retail-banking", "insurance"],
            ),
            ["retail-banking", "insurance"],
        )

    def test_choose_use_cases_uses_noninteractive_environment_override(self) -> None:
        selection_path = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(selection_path) / "selection"
        with (
            patch.dict(os.environ, {"KRATOS_UPLOAD_USE_CASES": "generic"}, clear=False),
            patch.object(hooklib, "selection_file", return_value=path),
        ):
            self.assertEqual(hooklib.choose_use_cases(), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "generic\n")


if __name__ == "__main__":
    unittest.main()
