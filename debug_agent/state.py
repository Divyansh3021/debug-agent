"""What passes from one box to the next.

Read this after graph.py. A node returns only the fields it fills in.
Fields marked "appended" can be written by several specialists at once.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class DebugState(TypedDict, total=False):
    incident: dict[str, Any]

    # collect
    evidence: list[dict[str, Any]]
    coverage: dict[str, Any]

    # policy: needs_data, observe_only, propose, or auto_fix
    policy: dict[str, Any]

    # specialists, appended
    hypotheses: Annotated[list[dict[str, Any]], operator.add]

    # classify
    diagnosis: dict[str, Any]

    # plan and validate, appended across retries
    plan: dict[str, Any]
    plans: Annotated[list[dict[str, Any]], operator.add]
    validation: dict[str, Any]
    validations: Annotated[list[dict[str, Any]], operator.add]
    attempt: int
    critiques: Annotated[list[str], operator.add]

    # approve and finalize
    approval: dict[str, Any]
    outcome: dict[str, Any]


def hypothesis(
    *,
    id: str,
    specialist: str,
    summary: str,
    confidence: float,
    facts: list[tuple[str, str]],
) -> dict[str, Any]:
    """One claim from one specialist.

    ``facts`` are the only statements classify is allowed to cite.
    Confidence stays with the specialist. The model does not raise it.
    """
    return {
        "id": id,
        "specialist": specialist,
        "summary": summary,
        "confidence": confidence,
        "facts": [{"id": fact_id, "statement": text} for fact_id, text in facts],
    }
