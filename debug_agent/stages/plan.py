"""Propose one mitigation. This is the second place a model is appropriate.

Prefer a reversible action first, usually a flag change. If ``critiques`` is
non-empty, Basil already rejected that action, so propose the code change.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState


def plan(state: DebugState) -> dict[str, Any]:
    critiques = list(state.get("critiques") or [])
    proposed = {
        "rationale": "",
        "risk": "high",
        # One of: {"kind": "flag"|"edit"|"rollback", "summary": "..."}
        # An unknown risk stays "high", so approval will not apply it.
        "actions": [],
        "attempt": len(critiques) + 1,
    }
    return {"plan": proposed, "plans": [proposed]}
