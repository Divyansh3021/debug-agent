"""Stage 2. Decide how much the agent is allowed to do.

This is ordinary code, not a prompt. A model should not be the thing that
decides it may edit production payments.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState, note

# Traces or logs are required. Metrics and deploy events alone are not a diagnosis.
BEHAVIORAL = {"traces", "logs"}
SENSITIVE = {"payments", "auth", "migrations"}


def policy(state: DebugState) -> dict[str, Any]:
    decision = decide_autonomy(state.get("incident") or {}, state.get("coverage") or {})
    return {"policy": decision, **note("policy", f"{decision['autonomy']} — {decision['reason']}")}


def decide_autonomy(incident: dict[str, Any], coverage: dict[str, Any]) -> dict[str, str]:
    """Return ``needs_data``, ``observe_only``, ``propose``, or ``auto_fix``."""
    present = {name for name, count in (coverage.get("capabilities") or {}).items() if count}
    if not present & BEHAVIORAL:
        return {
            "autonomy": "needs_data",
            "reason": "No traces or logs. Stopping before anyone invents a cause.",
        }

    if str(incident.get("severity") or "").lower() == "sev1":
        return {
            "autonomy": "observe_only",
            "reason": "Severity 1: diagnose and hand the writeup to a person. Do not edit.",
        }

    domains = {str(item).lower() for item in incident.get("sensitive_domains") or []}
    environment = str(incident.get("environment") or "").lower()
    if environment == "production" or domains & SENSITIVE:
        return {
            "autonomy": "propose",
            "reason": "Production or a sensitive domain: prepare a reviewable change and stop.",
        }

    if environment in {"dev", "staging", "test"}:
        return {
            "autonomy": "auto_fix",
            "reason": "Non-production, with behavioral evidence: a low-risk fix may be marked for apply.",
        }

    return {
        "autonomy": "propose",
        "reason": "Unknown environment. Default to a human review.",
    }


def approve(*, autonomy: str, risk: str, validation_status: str) -> dict[str, str]:
    """Last check before a diff is offered as something a person could merge."""
    if validation_status != "passed":
        return {"decision": "escalate", "reason": "Validation did not pass."}
    if risk == "high":
        return {"decision": "escalate", "reason": "High risk is never auto-approved."}
    if autonomy == "auto_fix" and risk == "low":
        return {"decision": "auto_apply", "reason": "Policy allows apply, the risk is low, and tests passed."}
    return {"decision": "draft_pr", "reason": "The change is validated and waiting for a person."}
