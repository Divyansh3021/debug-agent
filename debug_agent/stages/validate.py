"""Basil. Run the plan before anyone is asked to accept it.

BASIL runs a test described with tmt metadata and stores the result. This
file is that box. A real body copies the repo, applies the plan, and fills
in ``status``. The keys are the contract the rest of the graph reads.

Failure writes a critique. graph.py sends that critique back to plan, once.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState


def validate(state: DebugState) -> dict[str, Any]:
    attempt = int(state.get("attempt") or 0) + 1
    result = {
        "contract": "basil-result.v1",
        "status": "failed",
        "attempt": attempt,
        "tmt": {
            "basil_test_repo_url": "",
            "basil_test_repo_ref": "",
            "basil_test_relative_path": "",
        },
        "critique": "",
    }
    update: dict[str, Any] = {
        "validation": result,
        "validations": [result],
        "attempt": attempt,
    }
    if result["status"] != "passed":
        update["critiques"] = [result["critique"] or "Basil did not pass."]
    return update
