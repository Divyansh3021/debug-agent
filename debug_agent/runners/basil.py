"""Basil validation node.

BASIL (the FuSa Spice test manager) runs tests described with tmt/fmf
metadata. The graph depends on a small result contract, not on a particular
BASIL deployment:

    {
      "contract": "basil-result.v1",
      "engine": "pytest-reference" | "tmt",
      "status": "passed" | "failed" | "error",
      "tmt": {
        "basil_test_repo_url": "...",
        "basil_test_repo_ref": "...",
        "basil_test_relative_path": "..."
      },
      "assertions": [{"name": "...", "passed": true}],
      "log_tail": "..."
    }

The default engine is a local pytest run inside the scratch workspace, with
pytest isolated from this repository's own configuration. Set
``DEBUG_AGENT_BASIL_ENGINE=tmt`` to shell out to a ``tmt`` binary instead.
The relative path defaults to the scenario's ``tests/main.fmf``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


CONTRACT = "basil-result.v1"
_FAILURE_LINE = re.compile(r"^FAILED\s+(\S+)")


class BasilRunner:
    def __init__(self, engine: str | None = None, timeout_s: int = 60) -> None:
        self.engine = engine or os.environ.get("DEBUG_AGENT_BASIL_ENGINE", "pytest")
        self.timeout_s = timeout_s

    def run(self, *, workspace: Path, scenario_dir: Path, incident_id: str) -> dict[str, Any]:
        tmt = {
            "basil_test_repo_url": str(scenario_dir),
            "basil_test_repo_ref": "workspace",
            "basil_test_relative_path": "tests/main.fmf",
        }
        try:
            if self.engine == "tmt":
                return self._run_tmt(workspace, tmt, incident_id)
            if self.engine != "pytest":
                raise RuntimeError(f"unknown Basil engine {self.engine!r}")
            return self._run_pytest(workspace, tmt, incident_id)
        except Exception as exc:  # noqa: BLE001 — the graph has to see a result, not a crash
            return {
                "contract": CONTRACT,
                "engine": self.engine,
                "status": "error",
                "incident_id": incident_id,
                "tmt": tmt,
                "assertions": [],
                "log_tail": str(exc),
            }

    def _run_pytest(self, workspace: Path, tmt: dict[str, str], incident_id: str) -> dict[str, Any]:
        config = workspace / "basil.pytest.ini"
        config.write_text("[pytest]\naddopts =\n", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "-c",
                str(config),
                "--rootdir",
                str(workspace),
                "--noconftest",
                str(workspace / "tests"),
            ],
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
            check=False,
        )
        return _result(
            engine="pytest-reference",
            incident_id=incident_id,
            tmt=tmt,
            returncode=completed.returncode,
            output=(completed.stdout or "") + (completed.stderr or ""),
        )

    def _run_tmt(self, workspace: Path, tmt: dict[str, str], incident_id: str) -> dict[str, Any]:
        env = os.environ.copy()
        env.update(tmt)
        completed = subprocess.run(
            ["tmt", "run", "--remove", "-a", "tests"],
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
            check=False,
        )
        return _result(
            engine="tmt",
            incident_id=incident_id,
            tmt=tmt,
            returncode=completed.returncode,
            output=(completed.stdout or "") + (completed.stderr or ""),
        )


def _result(
    *,
    engine: str,
    incident_id: str,
    tmt: dict[str, str],
    returncode: int,
    output: str,
) -> dict[str, Any]:
    assertions = []
    for line in output.splitlines():
        match = _FAILURE_LINE.match(line.strip())
        if match:
            assertions.append({"name": match.group(1), "passed": False, "detail": line.strip()})
    status = "passed" if returncode == 0 else "failed"
    if status == "passed":
        assertions.append({"name": "basil-suite", "passed": True, "detail": "exit 0"})
    return {
        "contract": CONTRACT,
        "engine": engine,
        "status": status,
        "exit_code": returncode,
        "incident_id": incident_id,
        "tmt": tmt,
        "assertions": assertions,
        "log_tail": output[-4000:],
    }
