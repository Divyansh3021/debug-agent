"""LangGraph assembly for one incident.

The topology is the product. Nodes close over the registry, the model, the
specialists, and the Basil runner so a new specialist is a list entry rather
than a rewrite of the edges.
"""

from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from debug_agent.connectors.base import ConnectorRegistry, Query
from debug_agent.jsonutil import parse_json_object
from debug_agent.models import Model
from debug_agent.policy import approval_decision, evaluate_policy
from debug_agent.prompts import CLASSIFY_SYSTEM, MITIGATE_SYSTEM, classification_prompt, mitigation_prompt
from debug_agent.redact import redact
from debug_agent.runners.basil import BasilRunner
from debug_agent.specialists.base import Specialist
from debug_agent.workspace import ApplyError, apply_actions, prepare_workspace, unified_diff

CONFIDENCE_FLOOR = 0.45
DEFAULT_MAX_ATTEMPTS = 2


class DebugState(TypedDict, total=False):
    scenario_dir: str
    run_dir: str
    max_attempts: int
    envelope: dict[str, Any]
    evidence: list[dict[str, Any]]
    coverage: dict[str, Any]
    redactions: int
    policy: dict[str, Any]
    specialist_reports: Annotated[list[dict[str, Any]], operator.add]
    diagnosis: dict[str, Any]
    plan: dict[str, Any]
    plan_history: Annotated[list[dict[str, Any]], operator.add]
    validation: dict[str, Any]
    validation_history: Annotated[list[dict[str, Any]], operator.add]
    attempt: int
    critiques: Annotated[list[str], operator.add]
    approval: dict[str, Any]
    outcome: dict[str, Any]
    events: Annotated[list[dict[str, Any]], operator.add]


def build_graph(
    *,
    registry: ConnectorRegistry,
    specialists: list[Specialist],
    model: Model,
    runner: BasilRunner,
):
    """Compile the debugging graph. Specialists run as parallel branches."""
    graph = StateGraph(DebugState)
    graph.add_node("collect", _collect(registry))
    graph.add_node("policy", _policy)
    for specialist in specialists:
        graph.add_node(specialist.id, _specialist_node(specialist, model))
    graph.add_node("classify", _classify(model))
    graph.add_node("plan", _plan(model))
    graph.add_node("validate", _validate(runner))
    graph.add_node("approve", _approve)
    graph.add_node("finalize", _finalize)

    graph.add_edge(START, "collect")
    graph.add_edge("collect", "policy")
    graph.add_conditional_edges(
        "policy",
        _route_after_policy(specialists),
        [specialist.id for specialist in specialists] + ["finalize"],
    )
    # One edge from the whole fan-out waits until every specialist has reported.
    graph.add_edge([specialist.id for specialist in specialists], "classify")
    graph.add_conditional_edges(
        "classify",
        route_after_diagnosis,
        ["plan", "finalize"],
    )
    graph.add_edge("plan", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        ["plan", "approve", "finalize"],
    )
    graph.add_edge("approve", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def initial_state(*, scenario_dir: Path, run_dir: Path, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> DebugState:
    return {
        "scenario_dir": str(scenario_dir),
        "run_dir": str(run_dir),
        "max_attempts": max_attempts,
        "envelope": {},
        "evidence": [],
        "coverage": {},
        "redactions": 0,
        "policy": {},
        "specialist_reports": [],
        "diagnosis": {},
        "plan": {},
        "plan_history": [],
        "validation": {},
        "validation_history": [],
        "attempt": 0,
        "critiques": [],
        "approval": {},
        "outcome": {},
        "events": [],
    }


def route_after_diagnosis(state: DebugState) -> str:
    policy = state.get("policy") or {}
    diagnosis = state.get("diagnosis") or {}
    if policy.get("autonomy") in {"observe_only", "needs_data"}:
        return "finalize"
    if not diagnosis.get("primary_id") or float(diagnosis.get("confidence") or 0) < CONFIDENCE_FLOOR:
        return "finalize"
    return "plan"


def route_after_validation(state: DebugState) -> str:
    status = (state.get("validation") or {}).get("status")
    if status == "passed":
        return "approve"
    if int(state.get("attempt") or 0) >= int(state.get("max_attempts") or DEFAULT_MAX_ATTEMPTS):
        return "finalize"
    return "plan"


def outcome_kind(state: DebugState) -> str:
    policy = state.get("policy") or {}
    autonomy = policy.get("autonomy")
    if autonomy == "needs_data":
        return "needs_data"
    diagnosis = state.get("diagnosis") or {}
    if not diagnosis.get("primary_id"):
        return "ungrounded"
    if autonomy == "observe_only" or float(diagnosis.get("confidence") or 0) < CONFIDENCE_FLOOR:
        return "diagnosis_only"
    if (state.get("validation") or {}).get("status") != "passed":
        return "validation_exhausted"
    decision = (state.get("approval") or {}).get("decision")
    if decision in {"draft_pr", "auto_apply", "escalate"}:
        return decision
    return "escalate"


def _collect(registry: ConnectorRegistry):
    def collect(state: DebugState) -> dict[str, Any]:
        scenario_dir = Path(state["scenario_dir"])
        envelope = json.loads((scenario_dir / "incident.json").read_text(encoding="utf-8"))
        window = envelope["window"]
        query = Query(
            service=envelope["service"],
            environment=envelope["environment"],
            start=window["start"],
            end=window["end"],
            symptom=envelope["symptom"],
            lookback_minutes=int(envelope.get("lookback_minutes") or 60),
        )
        items, errors = registry.collect(query)
        redacted_items, redactions = redact(items)
        coverage = registry.coverage(redacted_items, errors)
        return {
            "envelope": envelope,
            "evidence": redacted_items,
            "coverage": coverage,
            "redactions": redactions,
            "events": [
                _event(
                    "collect",
                    f"Collected {len(redacted_items)} evidence item(s) with {redactions} redaction(s).",
                )
            ],
        }

    return collect


def _policy(state: DebugState) -> dict[str, Any]:
    decision = evaluate_policy(state.get("envelope") or {}, state.get("coverage") or {})
    return {
        "policy": decision,
        "events": [_event("policy", f"{decision['autonomy']}: {decision['reason']}")],
    }


def _route_after_policy(specialists: list[Specialist]):
    def route(state: DebugState) -> str | list[Send]:
        if (state.get("policy") or {}).get("autonomy") == "needs_data":
            return "finalize"
        return [
            Send(
                specialist.id,
                {
                    "envelope": state.get("envelope") or {},
                    "evidence": state.get("evidence") or [],
                },
            )
            for specialist in specialists
        ]

    return route


def _specialist_node(specialist: Specialist, model: Model):
    def run(state: DebugState) -> dict[str, Any]:
        report = specialist.analyze(
            envelope=state.get("envelope") or {},
            evidence=state.get("evidence") or [],
            model=model,
        )
        count = len(report.get("hypotheses") or [])
        return {
            "specialist_reports": [report],
            "events": [_event(specialist.id, f"{count} hypothesis(es). {report.get('summary')}")],
        }

    return run


def _classify(model: Model):
    def classify(state: DebugState) -> dict[str, Any]:
        hypotheses = []
        for report in state.get("specialist_reports") or []:
            for item in report.get("hypotheses") or []:
                hypotheses.append(item)
        hypotheses.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        diagnosis = _diagnosis_from_model(model, state.get("envelope") or {}, hypotheses)
        return {
            "diagnosis": diagnosis,
            "events": [
                _event(
                    "classify",
                    f"Primary {diagnosis.get('primary_id')} at confidence {diagnosis.get('confidence')}.",
                )
            ],
        }

    return classify


def _diagnosis_from_model(
    model: Model, envelope: dict[str, Any], hypotheses: list[dict[str, Any]]
) -> dict[str, Any]:
    if not hypotheses:
        return {
            "primary_id": None,
            "narrative": "Specialists produced no hypotheses.",
            "confidence": 0,
            "alternatives": [],
            "hypotheses": [],
            "grounded": False,
        }
    known_ids = {item["id"] for item in hypotheses}
    known_facts = {fact["id"] for item in hypotheses for fact in item.get("facts") or []}
    try:
        raw = model.complete(
            system=CLASSIFY_SYSTEM,
            user=classification_prompt(envelope=envelope, hypotheses=hypotheses),
        )
        parsed = parse_json_object(raw)
    except Exception as exc:
        return {
            "primary_id": None,
            "narrative": f"Classifier output could not be read ({exc}).",
            "confidence": 0,
            "alternatives": [_brief(item) for item in hypotheses],
            "hypotheses": hypotheses,
            "grounded": False,
        }
    primary_id = parsed.get("primary_id")
    cited = set(parsed.get("cited_fact_ids") or [])
    grounded = primary_id in known_ids and bool(cited) and cited <= known_facts
    chosen = next(item for item in hypotheses if item["id"] == primary_id) if grounded else None
    if chosen is None:
        return {
            "primary_id": None,
            "narrative": "Classifier cited a hypothesis or fact that was not in evidence.",
            "confidence": 0,
            "alternatives": [_brief(item) for item in hypotheses],
            "hypotheses": hypotheses,
            "grounded": False,
        }
    support = [item for item in hypotheses if item["id"] != chosen["id"] and item["confidence"] >= 0.6]
    confidence = min(0.95, round(float(chosen["confidence"]) + (0.05 if support else 0), 2))
    narrative = str(parsed.get("narrative") or chosen["summary"])
    return {
        "primary_id": chosen["id"],
        "narrative": narrative,
        "confidence": confidence,
        "alternatives": [_brief(item) for item in hypotheses if item["id"] != chosen["id"]],
        "hypotheses": hypotheses,
        "grounded": True,
    }


def _plan(model: Model):
    def plan(state: DebugState) -> dict[str, Any]:
        attempt = int(state.get("attempt") or 0)
        source_files = []
        for item in state.get("evidence") or []:
            if item.get("capability") != "source":
                continue
            for file in (item.get("body") or {}).get("files") or []:
                content = str(file.get("content") or "")
                source_files.append({"path": file.get("path"), "content": content[:40_000]})
        try:
            raw = model.complete(
                system=MITIGATE_SYSTEM,
                user=mitigation_prompt(
                    envelope=state.get("envelope") or {},
                    diagnosis=state.get("diagnosis") or {},
                    attempt=attempt,
                    critiques=list(state.get("critiques") or []),
                    source_files=source_files,
                ),
            )
            proposed = _normalize_plan(parse_json_object(raw), attempt)
        except Exception as exc:
            proposed = {
                "attempt": attempt,
                "rationale": f"The planner returned an unusable plan ({exc}).",
                "risk": "high",
                "actions": [],
                "invalid": True,
            }
        return {
            "plan": proposed,
            "plan_history": [proposed],
            "events": [_event("plan", f"Attempt {attempt + 1}: {proposed['rationale']}")],
        }

    return plan


def _normalize_plan(raw: dict[str, Any], attempt: int) -> dict[str, Any]:
    actions = raw.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("plan has no actions")
    cleaned = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("action was not an object")
        kind = action.get("kind")
        if kind not in {"flag", "edit", "rollback"}:
            raise ValueError(f"unknown action {kind}")
        payload = action.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("action payload was not an object")
        cleaned.append(
            {
                "kind": kind,
                "summary": str(action.get("summary") or kind),
                "payload": payload,
            }
        )
    risk = raw.get("risk")
    if risk not in {"low", "medium", "high"}:
        risk = "high"
    return {
        "attempt": attempt,
        "rationale": str(raw.get("rationale") or ""),
        "risk": risk,
        "actions": cleaned,
    }


def _validate(runner: BasilRunner):
    def validate(state: DebugState) -> dict[str, Any]:
        scenario_dir = Path(state["scenario_dir"])
        run_dir = Path(state["run_dir"])
        plan = state.get("plan") or {}
        attempt = int(state.get("attempt") or 0) + 1
        workspace = prepare_workspace(scenario_dir, run_dir)
        notes: list[str] = []
        apply_error = None
        if plan.get("invalid") or not plan.get("actions"):
            apply_error = plan.get("rationale") or "plan had no actions"
        else:
            try:
                notes = apply_actions(workspace, plan["actions"])
            except ApplyError as exc:
                apply_error = str(exc)
        if apply_error:
            result = {
                "contract": "basil-result.v1",
                "engine": "not-run",
                "status": "error",
                "assertions": [],
                "log_tail": apply_error,
                "diff": "",
                "notes": notes,
                "attempt": attempt,
            }
        else:
            result = runner.run(
                workspace=workspace,
                scenario_dir=scenario_dir,
                incident_id=str((state.get("envelope") or {}).get("id")),
            )
            result["diff"] = unified_diff(scenario_dir, workspace)
            result["notes"] = notes
            result["attempt"] = attempt
        critique = None
        critiques: list[str] = []
        if result["status"] != "passed":
            tail = str(result.get("log_tail") or "").strip()
            critique = f"Attempt {attempt} {result['status']}.\n{tail[-2000:]}"
            critiques.append(critique)
        return {
            "validation": result,
            "validation_history": [result],
            "attempt": attempt,
            "critiques": critiques,
            "events": [_event("validate", f"Basil {result['status']} on attempt {attempt}.")],
        }

    return validate


def _approve(state: DebugState) -> dict[str, Any]:
    plan = state.get("plan") or {}
    decision = approval_decision(
        autonomy=str((state.get("policy") or {}).get("autonomy")),
        risk=str(plan.get("risk") or "high"),
        validation_status=str((state.get("validation") or {}).get("status")),
    )
    return {
        "approval": decision,
        "events": [_event("approve", f"{decision['decision']}: {decision['reason']}")],
    }


def _finalize(state: DebugState) -> dict[str, Any]:
    from debug_agent.report import render_pull_request, render_report

    kind = outcome_kind(state)
    summaries = {
        "needs_data": "Stopped before diagnosis because behavioral evidence was missing.",
        "ungrounded": "Stopped because the classifier was not grounded in specialist facts.",
        "diagnosis_only": "Diagnosis is recorded. Policy or confidence did not allow a change.",
        "validation_exhausted": "Mitigations did not pass Basil within the attempt budget.",
        "draft_pr": "A validated diff is ready for review. It was not applied outside the scratch workspace.",
        "auto_apply": "Policy would allow unattended apply. This prototype still only writes artifacts.",
        "escalate": "The run is escalated for a person to take over.",
    }
    outcome = {
        "kind": kind,
        "summary": summaries.get(kind, kind),
        "incident_id": (state.get("envelope") or {}).get("id"),
    }
    # Render with the outcome included. The returned state update merges it in
    # after this node, so the files see a copy that already has the outcome.
    preview = dict(state)
    preview["outcome"] = outcome
    run_dir = Path(state["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.md"
    report_path.write_text(render_report(preview), encoding="utf-8")
    artifacts = {"report": str(report_path)}
    diff = (state.get("validation") or {}).get("diff") or ""
    if kind in {"draft_pr", "auto_apply"} and diff.strip():
        diff_path = run_dir / "diff.patch"
        pr_path = run_dir / "pull_request.md"
        diff_path.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        pr_path.write_text(render_pull_request(preview), encoding="utf-8")
        artifacts["diff"] = str(diff_path)
        artifacts["pull_request"] = str(pr_path)
    outcome["artifacts"] = artifacts
    return {
        "outcome": outcome,
        "events": [_event("finalize", f"{kind}. {outcome['summary']}")],
    }


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "summary": item.get("summary"),
        "confidence": item.get("confidence"),
        "specialist": item.get("specialist"),
    }


def _event(node: str, message: str) -> dict[str, str]:
    return {"node": node, "message": message}
