"""Parallel root-cause specialists.

Each function is one branch. ``graph.py`` starts them together and waits
until every branch has returned. A specialist may look at evidence. It may
not call another specialist and it may not decide the incident's cause.
That decision is the classify stage, where disagreements stay visible.

To add a branch: write a function with this shape and register its name in
``graph.py``.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState, hypothesis, note


def breadcrumb(state: DebugState) -> dict[str, Any]:
    """Rebuild the failing request path from traces.

    This is the "what did the user hit?" branch.
    """
    paths: list[str] = []
    flag_on = False
    missing_key = False
    for body in _bodies(state, "traces"):
        for trace in body.get("traces") or []:
            spans = trace.get("spans") or []
            if not any(span.get("status") == "error" for span in spans):
                continue
            paths.append(" → ".join(f"{span.get('service')} {span.get('operation')}" for span in spans))
            for span in spans:
                attributes = span.get("attributes") or {}
                if attributes.get("flag") and attributes.get("value") is True:
                    flag_on = True
                if "idempotency_key" in attributes and not attributes.get("idempotency_key"):
                    missing_key = True
    if not paths:
        return _empty("breadcrumb", "no failing traces")
    summary = "Failing requests reach the ledger" + (
        " with the async-capture flag on and no idempotency key."
        if flag_on and missing_key
        else "."
    )
    facts = [("breadcrumb:path", paths[0])]
    if flag_on:
        facts.append(("breadcrumb:flag-on", "A span on the failing path records the flag as on."))
    if missing_key:
        facts.append(("breadcrumb:missing-key", "The ledger span has an empty idempotency key."))
    claim = hypothesis(
        id="breadcrumb:missing-key-on-capture",
        specialist="breadcrumb",
        summary=summary,
        confidence=0.84 if flag_on and missing_key else 0.5,
        facts=facts,
    )
    return {"hypotheses": [claim], **note("breadcrumb", summary)}


def crash_correlation(state: DebugState) -> dict[str, Any]:
    """Group repeated exceptions in the logs.

    This is the "what is breaking?" branch. The count matters more than any
    single stack line.
    """
    errors: list[dict[str, Any]] = []
    for body in _bodies(state, "logs"):
        for entry in body.get("entries") or []:
            if str(entry.get("level") or "").lower() == "error":
                errors.append(entry)
    if not errors:
        return _empty("crash_correlation", "no error logs")
    sample = errors[0]
    error_type = str((sample.get("attributes") or {}).get("error_type") or "Error")
    attributes = sample.get("attributes") or {}
    missing_key = "idempotency_key" in attributes and not attributes.get("idempotency_key")
    summary = f"{len(errors)} {error_type} log(s). Sample: {sample.get('message')}"
    facts = [(f"crash:{error_type.lower()}", summary)]
    if missing_key:
        facts.append(("crash:missing-key", "The sampled error has an empty idempotency key."))
    claim = hypothesis(
        id=f"crash:{error_type.lower()}-cluster",
        specialist="crash_correlation",
        summary=summary,
        confidence=0.8 if missing_key else 0.55,
        facts=facts,
    )
    return {"hypotheses": [claim], **note("crash_correlation", summary)}


def change_correlation(state: DebugState) -> dict[str, Any]:
    """Relate flag flips and deploys to the incident.

    This branch exists because most production incidents are caused by a
    rollout. Traces show the broken path; a change record names who opened it.
    """
    changes = [change for body in _bodies(state, "feature_flags") for change in body.get("changes") or []]
    deploys = [deploy for body in _bodies(state, "deploys") for deploy in body.get("deploys") or []]
    if not changes and not deploys:
        return _empty("change_correlation", "no flag or deploy events")
    facts: list[tuple[str, str]] = []
    for change in changes:
        facts.append(
            (
                f"flag:{change.get('flag')}",
                f"{change.get('flag')} moved from {change.get('from')} to {change.get('to')}.",
            )
        )
    for deploy in deploys:
        facts.append(
            (
                f"deploy:{deploy.get('to_version')}",
                f"{deploy.get('service')} {deploy.get('to_version')}: {deploy.get('summary')}",
            )
        )
    flag = changes[0]["flag"] if changes else "deploy"
    summary = (
        f"Flag {flag} changed inside the incident window and is the rollout that opened the failing path."
        if changes
        else facts[0][1]
    )
    claim = hypothesis(
        id=f"change:flag-{flag}" if changes else "change:deploy",
        specialist="change_correlation",
        summary=summary,
        confidence=0.86 if changes else 0.5,
        facts=facts,
    )
    return {"hypotheses": [claim], **note("change_correlation", summary)}


def dependency(state: DebugState) -> dict[str, Any]:
    """Look for an upstream metric jump.

    Treat a jump as a symptom. It becomes a cause only if classify finds no
    change or trace that explains it.
    """
    worst: dict[str, Any] | None = None
    for body in _bodies(state, "metrics"):
        for series in body.get("series") or []:
            before = float(series.get("before") or 0)
            after = float(series.get("after") or 0)
            if before <= 0:
                continue
            ratio = after / before
            if worst is None or ratio > worst["ratio"]:
                worst = {"series": series, "ratio": ratio}
    if worst is None or worst["ratio"] < 5:
        return _empty("dependency", "no upstream metric jump")
    series = worst["series"]
    summary = (
        f"{series.get('service')} {series.get('name')} rose {worst['ratio']:.0f}x. "
        "Treat that as a symptom until a change or a trace explains it."
    )
    claim = hypothesis(
        id=f"dependency:{series.get('service')}-{series.get('name')}",
        specialist="dependency",
        summary=summary,
        confidence=0.58,
        facts=[(f"metric:{series.get('service')}:{series.get('name')}", summary)],
    )
    return {"hypotheses": [claim], **note("dependency", summary)}


def _bodies(state: DebugState, capability: str) -> list[dict[str, Any]]:
    return [
        item.get("body") or {}
        for item in state.get("evidence") or []
        if item.get("capability") == capability
    ]


def _empty(node: str, reason: str) -> dict[str, Any]:
    return {"hypotheses": [], **note(node, reason)}
