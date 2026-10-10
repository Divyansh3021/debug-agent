"""Correlate flag flips and deploys with the incident window.

Most production incidents are caused by a change. This specialist exists
because a trace-only RCA misses the rollout that made the bad path live.
"""

from __future__ import annotations

from typing import Any

from debug_agent.models import Model
from debug_agent.specialists.base import evidence_by_capability, hypothesis
from debug_agent.specialists.timeutil import parse_time, placement


class ChangeSpecialist:
    id = "change_correlation"
    description = "Relate flag changes and deploys to the incident window."

    def analyze(
        self,
        *,
        envelope: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: Model,
    ) -> dict[str, Any]:
        del model
        flag_facts = []
        for item in evidence_by_capability(evidence, "feature_flags"):
            for change in (item.get("body") or {}).get("changes") or []:
                where = _where(change.get("at"), envelope)
                if where is None:
                    continue
                flag_facts.append(
                    {
                        "id": f"flag:{change.get('flag')}",
                        "statement": (
                            f"Flag {change.get('flag')} moved from {change.get('from')} "
                            f"to {change.get('to')} ({where})."
                        ),
                        "where": where,
                        "flag": change.get("flag"),
                    }
                )
        deploy_facts = []
        for item in evidence_by_capability(evidence, "deploys"):
            for deploy in (item.get("body") or {}).get("deploys") or []:
                where = _where(deploy.get("at"), envelope)
                if where is None:
                    continue
                version = deploy.get("to_version")
                deploy_facts.append(
                    {
                        "id": f"deploy:{deploy.get('service')}-{version}",
                        "statement": (
                            f"{deploy.get('service')} deployed {version} ({where}). "
                            f"{deploy.get('summary') or ''}"
                        ).strip(),
                    }
                )
        hypotheses = []
        if flag_facts:
            in_window = any(fact["where"] == "in_window" for fact in flag_facts)
            primary = flag_facts[0]
            facts = [
                {"id": fact["id"], "statement": fact["statement"]} for fact in flag_facts
            ] + deploy_facts
            summary = (
                f"Flag {primary['flag']} changed {primary['where'].replace('_', ' ')} "
                "and is the rollout most likely to have opened the failing path."
            )
            hypotheses.append(
                hypothesis(
                    id=f"change:flag-{primary['flag']}",
                    specialist=self.id,
                    summary=summary,
                    confidence=0.86 if in_window else 0.62,
                    facts=facts,
                )
            )
        elif deploy_facts:
            hypotheses.append(
                hypothesis(
                    id="change:deploy-in-window",
                    specialist=self.id,
                    summary=deploy_facts[0]["statement"],
                    confidence=0.5,
                    facts=deploy_facts,
                )
            )
        summary = hypotheses[0]["summary"] if hypotheses else "No flag or deploy changes fell in the lookback window."
        return {"id": self.id, "summary": summary, "hypotheses": hypotheses}


def _where(value: Any, envelope: dict[str, Any]) -> str | None:
    if not value:
        return None
    try:
        return placement(parse_time(str(value)), envelope)
    except ValueError:
        return None
