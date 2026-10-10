"""Stage 7. Write the outcome. A pull request is only one of the endings.

Possible endings:

- ``needs_data`` — not enough evidence to speak
- ``diagnosis_only`` — we know enough to explain, not enough to edit
- ``ungrounded`` — the model left the evidence
- ``validation_exhausted`` — Basil never passed
- ``draft_pr`` — a person should review the change
- ``auto_apply`` — policy would allow apply; this skeleton still only writes a report
- ``escalate`` — a person takes over
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from debug_agent.stages.policy import approve
from debug_agent.state import DebugState, note


def approve_node(state: DebugState) -> dict[str, Any]:
    decision = approve(
        autonomy=str((state.get("policy") or {}).get("autonomy")),
        risk=str((state.get("plan") or {}).get("risk") or "high"),
        validation_status=str((state.get("validation") or {}).get("status")),
    )
    return {"approval": decision, **note("approve", f"{decision['decision']} — {decision['reason']}")}


def finalize(state: DebugState) -> dict[str, Any]:
    kind = outcome_kind(state)
    summaries = {
        "needs_data": "Stopped. There was not enough behavioral evidence to diagnose.",
        "ungrounded": "Stopped. The classifier was not grounded in specialist facts.",
        "diagnosis_only": "Wrote the diagnosis and did not plan a change.",
        "validation_exhausted": "Basil did not pass within the attempt budget.",
        "draft_pr": "A validated change is ready for review. Nothing was applied.",
        "auto_apply": "Policy would allow apply. This skeleton still only writes the report.",
        "escalate": "Handed to a person.",
    }
    outcome = {
        "kind": kind,
        "summary": summaries.get(kind, kind),
        "incident_id": (state.get("incident") or {}).get("id"),
    }
    preview = dict(state)
    preview["outcome"] = outcome
    report = render_report(preview)
    run_dir = Path(state.get("run_dir") or "runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "report.md"
    path.write_text(report, encoding="utf-8")
    outcome["report_path"] = str(path)
    return {"outcome": outcome, **note("finalize", f"{kind}. {outcome['summary']}")}


def outcome_kind(state: DebugState) -> str:
    autonomy = (state.get("policy") or {}).get("autonomy")
    if autonomy == "needs_data":
        return "needs_data"
    diagnosis = state.get("diagnosis") or {}
    if not diagnosis.get("primary_id"):
        return "ungrounded"
    if autonomy == "observe_only" or float(diagnosis.get("confidence") or 0) < 0.45:
        return "diagnosis_only"
    if (state.get("validation") or {}).get("status") != "passed":
        return "validation_exhausted"
    return (state.get("approval") or {}).get("decision") or "escalate"


def render_report(state: dict[str, Any]) -> str:
    """A single page a new reader can open after the run."""
    incident = state.get("incident") or {}
    outcome = state.get("outcome") or {}
    policy = state.get("policy") or {}
    diagnosis = state.get("diagnosis") or {}
    lines = [
        f"# {incident.get('id', 'incident')} — {incident.get('title', '')}",
        "",
        outcome.get("summary", ""),
        "",
        f"Policy `{policy.get('autonomy')}`: {policy.get('reason')}",
        "",
        "## Evidence",
        "",
    ]
    counts = (state.get("coverage") or {}).get("capabilities") or {}
    for name in sorted(counts):
        lines.append(f"- {name}: {counts[name]}")
    lines.append(f"- redactions: {(state.get('coverage') or {}).get('redactions', 0)}")
    lines.extend(["", "## Hypotheses", ""])
    for item in state.get("hypotheses") or []:
        lines.append(f"- `{item['id']}` ({item['confidence']}) — {item['summary']}")
    if not state.get("hypotheses"):
        lines.append("- none")
    lines.extend(["", "## Diagnosis", ""])
    if diagnosis.get("primary_id"):
        lines.append(f"Primary `{diagnosis['primary_id']}` at {diagnosis.get('confidence')}.")
        lines.append("")
        lines.append(diagnosis.get("narrative") or "")
    else:
        lines.append(diagnosis.get("narrative") or "No diagnosis.")
    lines.extend(["", "## Plans", ""])
    validations = state.get("validations") or []
    for index, item in enumerate(state.get("plans") or [], start=1):
        status = validations[index - 1]["status"] if index - 1 < len(validations) else "not run"
        action = (item.get("actions") or [{}])[0]
        lines.append(f"{index}. `{action.get('kind')}` ({status}, risk {item.get('risk')}). {item.get('rationale')}")
    if not state.get("plans"):
        lines.append("No plan. The run stopped before mitigation.")
    lines.extend(["", "## Audit", ""])
    for entry in state.get("log") or []:
        lines.append(f"- {entry}")
    lines.append("")
    return "\n".join(lines)
