"""Stage 4. Choose one hypothesis. This is the first real model judgment.

Specialists have already done the reading. The model only picks among their
ids and writes a short narrative. If it cites an id nobody produced, the run
stops. That check matters more than the quality of the prose.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState, note

# What you would send a model. The skeleton uses scripted_choice instead of an API call.
INSTRUCTIONS = """\
Choose the hypothesis that best explains the incident.
Reply with JSON: {"primary_id": "...", "narrative": "...", "cited_fact_ids": ["..."]}.
Use only ids from the list. Do not invent a cause.
"""

CONFIDENCE_FLOOR = 0.45


def classify(state: DebugState) -> dict[str, Any]:
    hypotheses = list(state.get("hypotheses") or [])
    hypotheses.sort(key=lambda item: item.get("confidence") or 0, reverse=True)
    # prompt_for(...) is what you would send the model. scripted_choice stands in for the reply.
    model_input = prompt_for(state.get("incident") or {}, hypotheses)
    raw = scripted_choice(hypotheses)
    diagnosis = accept_classification(hypotheses, raw)
    diagnosis["model_input"] = model_input
    label = diagnosis.get("primary_id") or "none"
    return {"diagnosis": diagnosis, **note("classify", f"primary {label}, grounded={diagnosis['grounded']}")}


def prompt_for(incident: dict[str, Any], hypotheses: list[dict[str, Any]]) -> str:
    """The user message a live model would see. Raw logs are not in here."""
    lines = [
        INSTRUCTIONS,
        f"incident: {incident.get('id')} {incident.get('title')}",
        f"symptom: {incident.get('symptom')}",
    ]
    for item in hypotheses:
        lines.append(f"hypothesis_id: {item['id']} ({item['confidence']}) {item['summary']}")
        for fact in item.get("facts") or []:
            lines.append(f"fact_id: {fact['id']} {fact['statement']}")
    return "\n".join(lines)


def scripted_choice(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    """Stand-in for the model, so the sample runs without an API key.

    It prefers the change hypothesis when one exists, because a rollout that
    lines up with the failing path is a better primary than the symptom alone.
    Swap this function for a real completion. Keep ``accept_classification``.
    """
    if not hypotheses:
        return {"primary_id": None, "narrative": "", "cited_fact_ids": []}
    chosen = next(
        (item for item in hypotheses if str(item["id"]).startswith("change:")),
        hypotheses[0],
    )
    return {
        "primary_id": chosen["id"],
        "narrative": (
            "The flag rollout opened an async path that reaches the ledger without an idempotency key. "
            + chosen["summary"]
        ),
        "cited_fact_ids": [fact["id"] for fact in chosen.get("facts") or []],
    }


def accept_classification(hypotheses: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    """Accept the model's pick only when every id is one a specialist produced."""
    known = {item["id"]: item for item in hypotheses}
    known_facts = {fact["id"] for item in hypotheses for fact in item.get("facts") or []}
    primary_id = raw.get("primary_id")
    cited = set(raw.get("cited_fact_ids") or [])
    chosen = known.get(primary_id)
    grounded = chosen is not None and bool(cited) and cited <= known_facts
    if not grounded or chosen is None:
        return {
            "primary_id": None,
            "narrative": "Rejected. The classifier cited an id that no specialist produced.",
            "confidence": 0,
            "grounded": False,
            "alternatives": [_brief(item) for item in hypotheses],
        }
    return {
        "primary_id": chosen["id"],
        "narrative": str(raw.get("narrative") or chosen["summary"]),
        "confidence": chosen["confidence"],
        "grounded": True,
        "alternatives": [_brief(item) for item in hypotheses if item["id"] != chosen["id"]],
    }


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "summary": item["summary"], "confidence": item["confidence"]}
