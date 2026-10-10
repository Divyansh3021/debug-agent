"""Connector protocol and registry.

Graph nodes ask for capabilities (traces, logs, flags). They do not name
Jaeger, Loki, or LaunchDarkly. A connector is how a particular system
satisfies a capability.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Protocol


CAPABILITIES = (
    "traces",
    "logs",
    "metrics",
    "incidents",
    "feature_flags",
    "deploys",
    "source",
)


@dataclass(frozen=True)
class Query:
    """The incident window a connector is allowed to read."""

    service: str
    environment: str
    start: str
    end: str
    symptom: str
    lookback_minutes: int = 60


class Connector(Protocol):
    id: str
    capability: str

    def collect(self, query: Query) -> list[dict[str, Any]]:
        """Return normalized evidence items. Raise on transport failure."""


def evidence(
    *,
    connector_id: str,
    capability: str,
    title: str,
    body: dict[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{connector_id}:{capability}",
        "connector_id": connector_id,
        "capability": capability,
        "title": title,
        "observed_at": observed_at,
        "body": body,
    }


class ConnectorRegistry:
    """Fan-out collection. One failing connector does not drop the others."""

    def __init__(self) -> None:
        self._connectors: list[Connector] = []

    def register(self, connector: Connector) -> None:
        if connector.capability not in CAPABILITIES:
            raise ValueError(
                f"connector {connector.id} has unknown capability {connector.capability}"
            )
        self._connectors.append(connector)

    def __iter__(self):
        return iter(self._connectors)

    def collect(self, query: Query) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if not self._connectors:
            return items, errors
        with ThreadPoolExecutor(max_workers=len(self._connectors)) as pool:
            futures = {pool.submit(connector.collect, query): connector for connector in self._connectors}
            for future in as_completed(futures):
                connector = futures[future]
                try:
                    items.extend(future.result())
                except Exception as exc:  # noqa: BLE001 — isolation is the point
                    errors.append({"connector": connector.id, "error": str(exc)})
        items.sort(key=lambda item: (item["capability"], item["connector_id"]))
        return items, errors

    def coverage(
        self, items: list[dict[str, Any]], errors: list[dict[str, str]]
    ) -> dict[str, Any]:
        counts = {name: 0 for name in CAPABILITIES}
        connectors: dict[str, list[str]] = {name: [] for name in CAPABILITIES}
        for item in items:
            capability = item["capability"]
            counts[capability] = counts.get(capability, 0) + 1
            connectors.setdefault(capability, [])
            if item["connector_id"] not in connectors[capability]:
                connectors[capability].append(item["connector_id"])
        return {
            "capabilities": counts,
            "connectors": connectors,
            "errors": errors,
        }
