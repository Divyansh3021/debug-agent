"""Autonomy rules live here, not in a prompt.

A debugging agent that can edit code needs an explicit policy for when it may
propose a change, when it must stop at a diagnosis, and when it does not yet
have enough evidence to say anything.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_DOMAINS = {"payments", "auth", "migrations"}
BEHAVIORAL_EVIDENCE = {"traces", "logs"}


def evaluate_policy(envelope: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    """Choose ``needs_data``, ``observe_only``, ``propose``, or ``auto_fix``."""
    counts = coverage.get("capabilities") or {}
    present = sorted(name for name, count in counts.items() if count)
    present_set = set(present)

    if not present_set & BEHAVIORAL_EVIDENCE:
        return {
            "autonomy": "needs_data",
            "reason": (
                "No trace or log evidence was collected. A diagnosis from "
                "metrics or deploy events alone would be ungrounded."
            ),
            "present": present,
        }

    severity = str(envelope.get("severity") or "").lower()
    if severity == "sev1":
        return {
            "autonomy": "observe_only",
            "reason": (
                "Severity 1 incidents are diagnosed and handed to a person. "
                "The agent does not propose edits while the incident is still unfolding."
            ),
            "present": present,
        }

    environment = str(envelope.get("environment") or "").lower()
    domains = {str(item).lower() for item in envelope.get("sensitive_domains") or []}
    if environment == "production" or domains & SENSITIVE_DOMAINS:
        return {
            "autonomy": "propose",
            "reason": (
                "Production or a sensitive domain: prepare a reviewable change "
                "and stop before applying it."
            ),
            "present": present,
        }

    if environment in {"dev", "staging", "test"}:
        return {
            "autonomy": "auto_fix",
            "reason": (
                "Non-production incident with behavioral evidence: a low-risk "
                "fix may be marked eligible for unattended apply."
            ),
            "present": present,
        }

    return {
        "autonomy": "propose",
        "reason": "Unknown environment defaults to a human-reviewed proposal.",
        "present": present,
    }


def approval_decision(*, autonomy: str, risk: str, validation_status: str) -> dict[str, str]:
    """Last gate before a diff is offered as something a person could merge."""
    if validation_status != "passed":
        return {
            "decision": "escalate",
            "reason": "Validation did not pass, so there is no change to approve.",
        }
    if risk == "high" or risk not in {"low", "medium"}:
        return {
            "decision": "escalate",
            "reason": "High or unclassified risk is never auto-approved.",
        }
    if autonomy == "observe_only":
        return {
            "decision": "escalate",
            "reason": "Policy forbids proposing a change for this incident.",
        }
    if autonomy == "auto_fix" and risk == "low":
        return {
            "decision": "auto_apply",
            "reason": "Policy allows unattended apply and the fix is low risk and validated.",
        }
    return {
        "decision": "draft_pr",
        "reason": "The validated change is ready for a person to review.",
    }
