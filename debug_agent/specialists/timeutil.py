"""Incident-window comparisons shared by the change specialist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def window_bounds(envelope: dict[str, Any]) -> tuple[datetime, datetime, datetime]:
    window = envelope.get("window") or {}
    start = parse_time(window["start"])
    end = parse_time(window["end"])
    lookback = int(envelope.get("lookback_minutes") or 60)
    return start - timedelta(minutes=lookback), start, end


def placement(moment: datetime, envelope: dict[str, Any]) -> str | None:
    """Return ``in_window``, ``in_lookback``, or None when the event is too old."""
    lookback_start, start, end = window_bounds(envelope)
    if start <= moment <= end:
        return "in_window"
    if lookback_start <= moment < start:
        return "in_lookback"
    return None
