"""Decide how far the agent may go.

This is ordinary code on purpose. A model should not decide that it may
edit production.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState

_BEHAVIORAL = {"traces", "logs"}
_SENSITIVE = {"payments", "auth", "migrations"}


def policy(state: DebugState) -> dict[str, Any]:
    return {"policy": decide(state.get("incident") or {}, state.get("coverage") or {})}


def decide(incident: dict[str, Any], coverage: dict[str, Any]) -> dict[str, str]:
    """``needs_data``, ``observe_only``, ``propose``, or ``auto_fix``."""
    present = {name for name, count in (coverage.get("capabilities") or {}).items() if count}
    if not present & _BEHAVIORAL:
        return {"autonomy": "needs_data", "reason": "No traces or logs, so there is nothing to diagnose."}
    if str(incident.get("severity") or "").lower() == "sev1":
        return {"autonomy": "observe_only", "reason": "Severity 1 is explained and handed to a person."}

    domains = {str(item).lower() for item in incident.get("sensitive_domains") or []}
    environment = str(incident.get("environment") or "").lower()
    if environment == "production" or domains & _SENSITIVE:
        return {"autonomy": "propose", "reason": "Production or a sensitive domain is review-only."}
    if environment in {"dev", "staging", "test"}:
        return {"autonomy": "auto_fix", "reason": "Non-production may apply a low-risk fix."}
    return {"autonomy": "propose", "reason": "Unknown environment stays review-only."}


def approve(state: DebugState) -> dict[str, Any]:
    """The last check before a passing change is offered to a person."""
    autonomy = str((state.get("policy") or {}).get("autonomy"))
    risk = str((state.get("plan") or {}).get("risk") or "high")
    status = str((state.get("validation") or {}).get("status"))
    if status != "passed" or risk == "high":
        decision = {"decision": "escalate", "reason": "Untested or high-risk changes stop here."}
    elif autonomy == "auto_fix" and risk == "low":
        decision = {"decision": "auto_apply", "reason": "Policy allows apply, and the risk is low."}
    else:
        decision = {"decision": "draft_pr", "reason": "Validated, and waiting for review."}
    return {"approval": decision}
