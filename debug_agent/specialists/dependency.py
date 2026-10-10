"""Look for upstream metric jumps that might be the real fault."""

from __future__ import annotations

from typing import Any

from debug_agent.models import Model
from debug_agent.specialists.base import evidence_by_capability, hypothesis


class DependencySpecialist:
    id = "dependency"
    description = "Detect upstream error-rate jumps inside the collected metrics."

    def analyze(
        self,
        *,
        envelope: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: Model,
    ) -> dict[str, Any]:
        del envelope, model
        best: dict[str, Any] | None = None
        for item in evidence_by_capability(evidence, "metrics"):
            for series in (item.get("body") or {}).get("series") or []:
                values = []
                for point in series.get("points") or []:
                    try:
                        values.append(float(point.get("value")))
                    except (TypeError, ValueError):
                        continue
                if len(values) < 2 or values[0] <= 0:
                    continue
                ratio = values[-1] / values[0]
                if best is None or ratio > best["ratio"]:
                    best = {"series": series, "ratio": ratio, "start": values[0], "end": values[-1]}
        if best is None or best["ratio"] < 5 or best["end"] < 0.05:
            return {
                "id": self.id,
                "summary": "No upstream metric jumped enough to treat it as its own hypothesis.",
                "hypotheses": [],
            }
        series = best["series"]
        name = series.get("name")
        service = series.get("service") or "unknown"
        statement = (
            f"{service} {name} moved from {best['start']:.4g} to {best['end']:.4g} "
            f"({best['ratio']:.1f}x)."
        )
        summary = (
            f"{service} shows a sharp {name} increase. Treat it as a symptom until "
            "a change or a trace explains it."
        )
        return {
            "id": self.id,
            "summary": summary,
            "hypotheses": [
                hypothesis(
                    id=f"dependency:{service}-{name}",
                    specialist=self.id,
                    summary=summary,
                    confidence=0.58,
                    facts=[{"id": f"metric:{service}:{name}", "statement": statement}],
                )
            ],
        }


def default_specialists() -> list[Any]:
    from debug_agent.specialists.breadcrumb import BreadcrumbSpecialist
    from debug_agent.specialists.change import ChangeSpecialist
    from debug_agent.specialists.crash import CrashSpecialist

    return [
        BreadcrumbSpecialist(),
        CrashSpecialist(),
        ChangeSpecialist(),
        DependencySpecialist(),
    ]
