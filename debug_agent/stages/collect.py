"""Gather evidence. This stage does not call a model.

If collection is fuzzy, every later judgment is fuzzy. Register connectors,
ask them for the incident window, and strip secrets before the evidence is
stored. Specialists see only what you return.
"""

from __future__ import annotations

from typing import Any

from debug_agent.connectors import ConnectorRegistry, Query
from debug_agent.state import DebugState


def collect(state: DebugState) -> dict[str, Any]:
    incident = state.get("incident") or {}
    window = incident.get("window") or {}
    query = Query(
        service=str(incident.get("service") or ""),
        environment=str(incident.get("environment") or ""),
        start=str(window.get("start") or ""),
        end=str(window.get("end") or ""),
        symptom=str(incident.get("symptom") or ""),
    )
    registry = ConnectorRegistry()
    # registry.register(JaegerConnector(url))
    # registry.register(FlagConnector(url))
    items, errors = registry.collect(query)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["capability"]] = counts.get(item["capability"], 0) + 1
    return {
        "incident": incident,
        "evidence": items,
        "coverage": {"capabilities": counts, "errors": errors},
    }
