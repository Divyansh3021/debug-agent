"""Stage 1. Gather evidence. No model calls.

The collector is deterministic on purpose. If this stage is fuzzy, every
later judgment is fuzzy. It loads the incident, asks the connector registry,
and redacts secrets before any specialist or model can see them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from debug_agent.connectors import CAPABILITIES, JsonFileConnector, Query, ConnectorRegistry
from debug_agent.state import DebugState, note

_SECRETS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"(?i)\b(api[_-]?key|password|token)\b\s*[:=]\s*\S+"),
)


def collect(state: DebugState) -> dict[str, Any]:
    raw = json.loads(Path(state["example_path"]).read_text(encoding="utf-8"))
    incident = _incident(raw)
    registry = ConnectorRegistry()
    for capability in CAPABILITIES:
        body = raw.get(capability) or {}
        if body:
            registry.register(JsonFileConnector(capability, body))
    query = Query(
        service=incident["service"],
        environment=incident["environment"],
        start=incident["window"]["start"],
        end=incident["window"]["end"],
        symptom=incident["symptom"],
    )
    items, errors = registry.collect(query)
    items, redactions = _redact(items)
    coverage = _coverage(items, errors, redactions)
    return {
        "incident": incident,
        "evidence": items,
        "coverage": coverage,
        **note("collect", f"{len(items)} evidence item(s), {redactions} redaction(s), {len(errors)} connector error(s)"),
    }


def _incident(raw: dict[str, Any]) -> dict[str, Any]:
    incident = raw.get("incident")
    if not isinstance(incident, dict):
        raise ValueError("example file needs an 'incident' object")
    missing = [key for key in ("id", "title", "service", "environment", "severity", "symptom", "window") if key not in incident]
    if missing:
        raise ValueError(f"incident is missing {missing}")
    return incident


def _redact(value: Any) -> tuple[Any, int]:
    """Replace secret-shaped strings. Runs before evidence is stored."""
    if isinstance(value, str):
        updated = value
        count = 0
        for pattern in _SECRETS:
            updated, found = pattern.subn("[REDACTED]", updated)
            count += found
        return updated, count
    if isinstance(value, list):
        total = 0
        items = []
        for item in value:
            cleaned, count = _redact(item)
            items.append(cleaned)
            total += count
        return items, total
    if isinstance(value, dict):
        total = 0
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            new_key, key_hits = _redact(key)
            new_item, item_hits = _redact(item)
            cleaned[new_key] = new_item
            total += key_hits + item_hits
        return cleaned, total
    return value, 0


def _coverage(items: list[dict[str, Any]], errors: list[dict[str, str]], redactions: int) -> dict[str, Any]:
    counts = {name: 0 for name in CAPABILITIES}
    for item in items:
        counts[item["capability"]] = counts.get(item["capability"], 0) + 1
    return {"capabilities": counts, "errors": errors, "redactions": redactions}
