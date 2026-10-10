"""Rebuild the failing request path from normalized traces."""

from __future__ import annotations

from typing import Any

from debug_agent.models import Model
from debug_agent.specialists.base import evidence_by_capability, hypothesis


class BreadcrumbSpecialist:
    id = "breadcrumb"
    description = "Reconstruct the request path that ended in an error span."

    def analyze(
        self,
        *,
        envelope: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: Model,
    ) -> dict[str, Any]:
        del envelope, model
        paths: list[str] = []
        null_key = False
        flag_on = False
        flag_name = None
        for item in evidence_by_capability(evidence, "traces"):
            for trace in (item.get("body") or {}).get("traces") or []:
                spans = trace.get("spans") or []
                if not any(span.get("status") == "error" for span in spans):
                    continue
                paths.append(_format_path(spans))
                for span in spans:
                    attributes = span.get("attributes") or {}
                    if "idempotency_key" in attributes and not attributes.get("idempotency_key"):
                        null_key = True
                    value = attributes.get("value")
                    if attributes.get("flag") and value in (True, "true", "True", 1, "1"):
                        flag_on = True
                        flag_name = attributes.get("flag")
        if not paths:
            return {
                "id": self.id,
                "summary": "No error traces were available to reconstruct a path.",
                "hypotheses": [],
            }
        facts = [
            {
                "id": "breadcrumb:error-path",
                "statement": f"{len(paths)} failing trace(s). Example path: {paths[0]}",
            }
        ]
        if flag_on:
            facts.append(
                {
                    "id": "breadcrumb:flag-enabled",
                    "statement": f"A span records flag {flag_name} as enabled on the failing path.",
                }
            )
        if null_key:
            facts.append(
                {
                    "id": "breadcrumb:null-idempotency-key",
                    "statement": "The failing ledger span has an empty idempotency key.",
                }
            )
        confidence = 0.45 + (0.2 if flag_on else 0) + (0.2 if null_key else 0)
        summary = (
            "Failing requests reach ledger capture"
            + (" with the async-capture flag on" if flag_on else "")
            + (" and no idempotency key." if null_key else ".")
        )
        return {
            "id": self.id,
            "summary": summary,
            "hypotheses": [
                hypothesis(
                    id="breadcrumb:async-capture-missing-key",
                    specialist=self.id,
                    summary=summary,
                    confidence=confidence,
                    facts=facts,
                )
            ],
        }


def _format_path(spans: list[dict[str, Any]]) -> str:
    by_parent: dict[Any, list[dict[str, Any]]] = {}
    ids = {span.get("span_id") for span in spans}
    for span in spans:
        parent = span.get("parent_span_id")
        if parent not in ids:
            parent = None
        by_parent.setdefault(parent, []).append(span)
    ordered: list[dict[str, Any]] = []

    def walk(parent: Any) -> None:
        for span in by_parent.get(parent, []):
            ordered.append(span)
            walk(span.get("span_id"))

    walk(None)
    return " -> ".join(
        f"{span.get('service')} {span.get('operation')} [{span.get('status')}]" for span in ordered
    )
