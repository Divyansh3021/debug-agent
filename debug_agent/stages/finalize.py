"""Write the ending. A pull request is only one of them.

- needs_data: not enough evidence to speak
- diagnosis_only: explain, do not edit
- ungrounded: the model left the evidence
- validation_exhausted: Basil never passed
- draft_pr: a person should review the change
- auto_apply: policy would allow the change
- escalate: a person takes over
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState


def finalize(state: DebugState) -> dict[str, Any]:
    return {
        "outcome": {
            "kind": outcome_kind(state),
            "incident_id": (state.get("incident") or {}).get("id"),
        }
    }


def outcome_kind(state: DebugState) -> str:
    autonomy = (state.get("policy") or {}).get("autonomy")
    if autonomy == "needs_data":
        return "needs_data"
    diagnosis = state.get("diagnosis") or {}
    if not diagnosis.get("primary_id"):
        return "ungrounded"
    if autonomy == "observe_only" or float(diagnosis.get("confidence") or 0) < 0.45:
        return "diagnosis_only"
    if (state.get("validation") or {}).get("status") != "passed":
        return "validation_exhausted"
    return (state.get("approval") or {}).get("decision") or "escalate"
