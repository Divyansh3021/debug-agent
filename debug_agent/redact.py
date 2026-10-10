"""Deterministic redaction applied before any model sees evidence."""

from __future__ import annotations

import re
from typing import Any

_SUBSTITUTIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{6,}", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_-]?key|password|secret|token)\b\s*[:=]\s*\S+"
    ),
)


def redact(value: Any) -> tuple[Any, int]:
    """Return a copy of ``value`` with secrets replaced, plus a replacement count."""
    if isinstance(value, str):
        count = 0
        updated = value
        for pattern in _SUBSTITUTIONS:
            updated, found = pattern.subn("[REDACTED]", updated)
            count += found
        return updated, count
    if isinstance(value, list):
        total = 0
        items = []
        for item in value:
            cleaned, found = redact(item)
            items.append(cleaned)
            total += found
        return items, total
    if isinstance(value, dict):
        total = 0
        cleaned_dict: dict[Any, Any] = {}
        for key, item in value.items():
            cleaned_key, key_hits = redact(key)
            cleaned_item, item_hits = redact(item)
            cleaned_dict[cleaned_key] = cleaned_item
            total += key_hits + item_hits
        return cleaned_dict, total
    return value, 0
