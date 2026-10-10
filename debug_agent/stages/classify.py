"""Pick one hypothesis. This is the first place a model is appropriate.

The specialists have already read the evidence. The model only chooses an id
they produced and writes a short narrative. An id it invents is rejected.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState


def classify(state: DebugState) -> dict[str, Any]:
    hypotheses = list(state.get("hypotheses") or [])
    # Reply to prompt_for(incident, hypotheses) with this JSON, then keep the check below.
    reply = {"primary_id": None, "narrative": "", "cited_fact_ids": []}
    return {"diagnosis": accept(hypotheses, reply)}


def prompt_for(incident: dict[str, Any], hypotheses: list[dict[str, Any]]) -> str:
    """What the model is allowed to see. Raw logs are not in this string."""
    lines = [
        "Pick a hypothesis_id and cite fact_ids from the list only.",
        f"symptom: {incident.get('symptom')}",
    ]
    for item in hypotheses:
        lines.append(f"hypothesis_id: {item['id']} {item['summary']}")
        for fact in item.get("facts") or []:
            lines.append(f"fact_id: {fact['id']} {fact['statement']}")
    return "\n".join(lines)


def accept(hypotheses: list[dict[str, Any]], reply: dict[str, Any]) -> dict[str, Any]:
    """Keep the model's pick only when every id came from a specialist."""
    known = {item["id"]: item for item in hypotheses}
    known_facts = {fact["id"] for item in hypotheses for fact in item.get("facts") or []}
    chosen = known.get(reply.get("primary_id"))
    cited = set(reply.get("cited_fact_ids") or [])
    if chosen is None or not cited or not cited <= known_facts:
        return {
            "primary_id": None,
            "narrative": "Rejected. The reply cited an id no specialist produced.",
            "confidence": 0,
            "grounded": False,
            "alternatives": [_brief(item) for item in hypotheses],
        }
    return {
        "primary_id": chosen["id"],
        "narrative": str(reply.get("narrative") or chosen["summary"]),
        "confidence": chosen["confidence"],
        "grounded": True,
        "alternatives": [_brief(item) for item in hypotheses if item["id"] != chosen["id"]],
    }


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "summary": item["summary"], "confidence": item["confidence"]}
