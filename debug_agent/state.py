"""The object that moves along the graph.

Read this after ``graph.py``. Every node reads some of these fields and
returns a partial update. Fields marked "appended" use a reducer so parallel
specialists can write them at the same time without overwriting each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class DebugState(TypedDict, total=False):
    # Input. Set by the caller before the graph starts.
    example_path: str
    run_dir: str

    # collect
    incident: dict[str, Any]
    evidence: list[dict[str, Any]]
    coverage: dict[str, Any]

    # policy. One of: needs_data, observe_only, propose, auto_fix.
    policy: dict[str, Any]

    # specialists. Appended, one hypothesis list per branch.
    hypotheses: Annotated[list[dict[str, Any]], operator.add]

    # classify
    diagnosis: dict[str, Any]

    # plan → validate, possibly more than once.
    plan: dict[str, Any]
    plans: Annotated[list[dict[str, Any]], operator.add]
    validation: dict[str, Any]
    validations: Annotated[list[dict[str, Any]], operator.add]
    attempt: int
    critiques: Annotated[list[str], operator.add]

    # approve + finalize
    approval: dict[str, Any]
    outcome: dict[str, Any]

    # One human-readable line per node, in the order nodes finished.
    log: Annotated[list[str], operator.add]


def hypothesis(
    *,
    id: str,
    specialist: str,
    summary: str,
    confidence: float,
    facts: list[tuple[str, str]],
) -> dict[str, Any]:
    """A claim a specialist is willing to defend.

    ``facts`` are the only statements a later model is allowed to cite.
    Confidence belongs to the specialist. The classifier does not raise it.
    """
    return {
        "id": id,
        "specialist": specialist,
        "summary": summary,
        "confidence": round(confidence, 2),
        "facts": [{"id": fact_id, "statement": text} for fact_id, text in facts],
    }


def note(node: str, message: str) -> dict[str, list[str]]:
    """A one-line audit entry. Every node returns one."""
    return {"log": [f"{node}: {message}"]}
