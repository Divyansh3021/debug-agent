"""Specialist contract.

A specialist reads normalized evidence and returns hypotheses. It does not
call other specialists and it does not decide the incident's root cause.
The classification node does that after every specialist has reported.
"""

from __future__ import annotations

from typing import Any, Protocol

from debug_agent.models import Model


class Specialist(Protocol):
    id: str
    description: str

    def analyze(
        self,
        *,
        envelope: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: Model,
    ) -> dict[str, Any]:
        """Return ``{id, summary, hypotheses}``."""


def hypothesis(
    *,
    id: str,
    specialist: str,
    summary: str,
    confidence: float,
    facts: list[dict[str, str]],
) -> dict[str, Any]:
    bounded = max(0.0, min(0.99, round(confidence, 2)))
    return {
        "id": id,
        "specialist": specialist,
        "summary": summary,
        "confidence": bounded,
        "fact_ids": [fact["id"] for fact in facts],
        "facts": facts,
    }


def evidence_by_capability(
    items: list[dict[str, Any]], capability: str
) -> list[dict[str, Any]]:
    return [item for item in items if item.get("capability") == capability]
