"""Cluster exceptions from logs, then ask the model to narrate cited facts.

The narration is discarded when it cites a fact the cluster step did not
produce. That is the grounding rule for specialist-level model use.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from debug_agent.jsonutil import parse_json_object
from debug_agent.models import Model
from debug_agent.prompts import NARRATE_SYSTEM, narration_prompt
from debug_agent.specialists.base import evidence_by_capability, hypothesis


class CrashSpecialist:
    id = "crash_correlation"
    description = "Group repeated exceptions and keep only a grounded narration."

    def analyze(
        self,
        *,
        envelope: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: Model,
    ) -> dict[str, Any]:
        del envelope
        counter: Counter[str] = Counter()
        samples: dict[str, dict[str, Any]] = {}
        for item in evidence_by_capability(evidence, "logs"):
            for entry in (item.get("body") or {}).get("entries") or []:
                level = str(entry.get("level") or "").lower()
                if level not in {"error", "fatal", "critical"}:
                    continue
                attributes = entry.get("attributes") or {}
                error_type = str(attributes.get("error_type") or "Error")
                key = error_type
                counter[key] += 1
                samples.setdefault(key, entry)
        if not counter:
            return {
                "id": self.id,
                "summary": "No error logs were available to cluster.",
                "hypotheses": [],
            }
        error_type, count = counter.most_common(1)[0]
        sample = samples[error_type]
        attributes = sample.get("attributes") or {}
        missing_key = "idempotency_key" in attributes and not attributes.get("idempotency_key")
        fact_id = f"crash:{error_type.lower()}-x{count}"
        statement = (
            f"{count} {error_type} log(s). Sample: {sample.get('message')}"
        )
        facts = [{"id": fact_id, "statement": statement}]
        if missing_key:
            facts.append(
                {
                    "id": "crash:missing-idempotency-key",
                    "statement": "The sampled exception attributes include an empty idempotency key.",
                }
            )
        narrative, grounded = _narrate(model, facts)
        summary = narrative if grounded and narrative else statement
        confidence = 0.55 + min(0.2, count * 0.04) + (0.15 if missing_key else 0)
        return {
            "id": self.id,
            "summary": summary,
            "narrative_grounded": grounded,
            "hypotheses": [
                hypothesis(
                    id=f"crash:{error_type.lower()}-cluster",
                    specialist=self.id,
                    summary=summary,
                    confidence=confidence,
                    facts=facts,
                )
            ],
        }


def _narrate(model: Model, facts: list[dict[str, str]]) -> tuple[str | None, bool]:
    try:
        raw = model.complete(
            system=NARRATE_SYSTEM,
            user=narration_prompt(specialist="crash", facts=facts),
        )
        parsed = parse_json_object(raw)
    except Exception:
        return None, False
    known = {fact["id"] for fact in facts}
    cited = set(parsed.get("cited_fact_ids") or [])
    narrative = parsed.get("narrative")
    if not cited or not cited <= known or not isinstance(narrative, str) or not narrative.strip():
        return None, False
    return narrative.strip(), True
