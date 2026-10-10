"""Stage 6. Basil. Check the plan before anyone is asked to merge it.

BASIL runs tests described with tmt/fmf metadata and records the result next
to the requirement. This module is that box in the diagram. It does not talk
to a BASIL server. It shows the result contract and the retry.

A real runner would copy the repo, apply the plan, and execute the test.
The stand-in encodes the lesson of the sample incident: turning the flag off
does not satisfy a test that holds the flag on and expects a key. The code
edit does.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState, note

MAX_ATTEMPTS = 2
CONTRACT = "basil-result.v1"


def validate(state: DebugState) -> dict[str, Any]:
    attempt = int(state.get("attempt") or 0) + 1
    result = basil_check(state.get("plan") or {}, attempt)
    update: dict[str, Any] = {
        "validation": result,
        "validations": [result],
        "attempt": attempt,
        **note("validate", f"Basil {result['status']} on attempt {attempt}"),
    }
    if result["status"] != "passed":
        update["critiques"] = [result["critique"]]
    return update


def basil_check(plan: dict[str, Any], attempt: int) -> dict[str, Any]:
    """Return the Basil result contract. Replace the body, keep the keys."""
    kinds = [action.get("kind") for action in plan.get("actions") or []]
    passed = "edit" in kinds
    critique = ""
    if not passed:
        critique = (
            "FAILED tests/test_capture.py::test_async_mints_key_when_missing\n"
            "The flag ramp does not change the code path the test holds open. "
            "ledger.capture timed out: idempotency_key is missing."
        )
    return {
        "contract": CONTRACT,
        "engine": "skeleton",
        "status": "passed" if passed else "failed",
        "attempt": attempt,
        # The fields a BASIL tmt plan expects when a real runner takes over.
        "tmt": {
            "basil_test_repo_url": "examples/checkout_async_capture",
            "basil_test_repo_ref": "workspace",
            "basil_test_relative_path": "tests/main.fmf",
        },
        "critique": critique,
    }
