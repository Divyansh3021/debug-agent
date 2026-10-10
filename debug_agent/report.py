"""Human-readable artifacts for the end of a run."""

from __future__ import annotations

from typing import Any


def render_report(state: dict[str, Any]) -> str:
    envelope = state.get("envelope") or {}
    outcome = state.get("outcome") or {}
    policy = state.get("policy") or {}
    diagnosis = state.get("diagnosis") or {}
    lines = [
        f"# {envelope.get('id', 'incident')} — {envelope.get('title', 'debugging run')}",
        "",
        f"Service `{envelope.get('service')}` in `{envelope.get('environment')}`. "
        f"Symptom: {envelope.get('symptom')}",
        "",
        "## Outcome",
        "",
        f"**{outcome.get('kind', 'unknown')}.** {outcome.get('summary', '')}",
        "",
        "## Policy",
        "",
        f"`{policy.get('autonomy')}` — {policy.get('reason')}",
        "",
        "## Evidence",
        "",
        _coverage_table(state.get("coverage") or {}),
        "",
        f"Redactions applied before any model call: {state.get('redactions', 0)}.",
        "",
        "## Specialists",
        "",
    ]
    reports = state.get("specialist_reports") or []
    if not reports:
        lines.append("Specialists did not run.")
    for report in reports:
        lines.append(f"### {report.get('id')}")
        lines.append("")
        lines.append(str(report.get("summary") or ""))
        lines.append("")
    lines.extend(["## Diagnosis", ""])
    if diagnosis.get("primary_id"):
        lines.append(f"Primary hypothesis `{diagnosis['primary_id']}` "
                     f"(confidence {diagnosis.get('confidence')}).")
        lines.append("")
        lines.append(str(diagnosis.get("narrative") or ""))
        lines.append("")
        lines.append("Alternatives:")
        lines.append("")
        for item in diagnosis.get("alternatives") or []:
            lines.append(f"- `{item.get('id')}` ({item.get('confidence')}): {item.get('summary')}")
    else:
        lines.append("No grounded diagnosis was produced.")
    lines.extend(["", "## Mitigation attempts", ""])
    history = state.get("validation_history") or []
    plans = state.get("plan_history") or []
    if not plans:
        lines.append("No mitigation was planned.")
    for index, plan in enumerate(plans, start=1):
        validation = history[index - 1] if index - 1 < len(history) else {}
        lines.append(f"### Attempt {index}: {validation.get('status', 'not run')}")
        lines.append("")
        lines.append(str(plan.get("rationale") or ""))
        lines.append("")
        for action in plan.get("actions") or []:
            lines.append(f"- `{action.get('kind')}` — {action.get('summary')} (risk `{plan.get('risk')}`)")
        if validation.get("log_tail") and validation.get("status") != "passed":
            lines.append("")
            lines.append("```text")
            lines.append(str(validation.get("log_tail")).strip()[-1500:])
            lines.append("```")
        lines.append("")
    approval = state.get("approval") or {}
    if approval:
        lines.extend(["## Approval", "", f"`{approval.get('decision')}` — {approval.get('reason')}", ""])
    lines.extend(["## Audit", ""])
    for event in state.get("events") or []:
        lines.append(f"- `{event.get('node')}`: {event.get('message')}")
    lines.append("")
    return "\n".join(lines)


def render_pull_request(state: dict[str, Any]) -> str:
    envelope = state.get("envelope") or {}
    diagnosis = state.get("diagnosis") or {}
    validation = state.get("validation") or {}
    approval = state.get("approval") or {}
    plans = state.get("plan_history") or []
    title = f"{envelope.get('service')}: {envelope.get('title')}"
    lines = [
        f"# {title}",
        "",
        "## Summary",
        "",
        str(diagnosis.get("narrative") or envelope.get("symptom") or ""),
        "",
        f"Policy `{state.get('policy', {}).get('autonomy')}` produced "
        f"`{approval.get('decision')}` after Basil `{validation.get('engine')}` "
        f"returned `{validation.get('status')}`.",
        "",
        "## Attempts",
        "",
    ]
    for index, plan in enumerate(plans, start=1):
        kinds = ", ".join(action["kind"] for action in plan.get("actions") or [])
        lines.append(f"{index}. {kinds} — {plan.get('rationale')}")
    lines.extend(
        [
            "",
            "## Validation",
            "",
            f"Contract `{validation.get('contract')}`, engine `{validation.get('engine')}`, "
            f"status `{validation.get('status')}`.",
            "",
            "tmt context recorded for a BASIL test run:",
            "",
        ]
    )
    for key, value in (validation.get("tmt") or {}).items():
        lines.append(f"- `{key}` = `{value}`")
    lines.extend(["", "## Rollback", "", _rollback_text(plans), "", "## Diff", "", "```diff"])
    lines.append((validation.get("diff") or "").rstrip())
    lines.extend(["```", ""])
    return "\n".join(lines)


def _rollback_text(plans: list[dict[str, Any]]) -> str:
    flags = []
    for plan in plans:
        for action in plan.get("actions") or []:
            if action.get("kind") == "flag":
                payload = action.get("payload") or {}
                flags.append(f"`{payload.get('flag')}` to `{payload.get('from')}`")
    if flags:
        listed = ", ".join(flags)
        return (
            f"Reverse the operational ramp ({listed}) to stop traffic taking the broken path. "
            "Revert the code edit on its own if the durable fix misbehaves."
        )
    return "Revert the diff as a unit. No separate operational ramp was proposed."


def _coverage_table(coverage: dict[str, Any]) -> str:
    counts = coverage.get("capabilities") or {}
    connectors = coverage.get("connectors") or {}
    lines = ["| Capability | Items | Connectors |", "| --- | --- | --- |"]
    for name in sorted(counts):
        used = ", ".join(connectors.get(name) or []) or "—"
        lines.append(f"| {name} | {counts[name]} | {used} |")
    errors = coverage.get("errors") or []
    if errors:
        lines.append("")
        lines.append("Connector errors:")
        for error in errors:
            lines.append(f"- `{error.get('connector')}`: {error.get('error')}")
    return "\n".join(lines)
