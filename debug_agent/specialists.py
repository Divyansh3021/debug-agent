"""The parallel readers.

Each function answers one question about the evidence. graph.py starts them
together and waits until all of them have returned. A specialist does not
call another specialist and does not decide the cause. Classify does that,
which is why disagreements stay visible as separate claims.

To add a reader, write a function like these and add its name in graph.py.

A claim you return looks like this:

    hypothesis(
        id="change:flag-checkout.async_capture",
        specialist="change_correlation",
        summary="The async-capture flag moved to 100 during the incident.",
        confidence=0.86,
        facts=[("flag:checkout.async_capture", "from 0 to 100")],
    )
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState


def breadcrumb(state: DebugState) -> dict[str, Any]:
    """Which request path failed?"""
    _traces(state)
    return {"hypotheses": []}


def crash_correlation(state: DebugState) -> dict[str, Any]:
    """Which exception keeps repeating?"""
    _of(state, "logs")
    return {"hypotheses": []}


def change_correlation(state: DebugState) -> dict[str, Any]:
    """Which rollout landed in the window? Flags and deploys live here."""
    _of(state, "feature_flags")
    _of(state, "deploys")
    return {"hypotheses": []}


def dependency(state: DebugState) -> dict[str, Any]:
    """Did an upstream metric jump? Treat a jump as a symptom, not a cause."""
    _of(state, "metrics")
    return {"hypotheses": []}


def _traces(state: DebugState) -> list[dict[str, Any]]:
    return _of(state, "traces")


def _of(state: DebugState, capability: str) -> list[dict[str, Any]]:
    return [
        item.get("body") or {}
        for item in state.get("evidence") or []
        if item.get("capability") == capability
    ]
