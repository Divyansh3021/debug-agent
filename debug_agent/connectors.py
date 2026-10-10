"""Where Jaeger, logs, flags, and anything like them plug in.

The graph never names a product. A stage asks for a capability. A connector
answers for one system and returns the shape below. An MCP tool is a connector.
A REST client is a connector.
"""

from __future__ import annotations

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
    """The only thing a connector is allowed to see: the incident window."""

    service: str
    environment: str
    start: str
    end: str
    symptom: str


class Connector(Protocol):
    id: str
    capability: str

    def collect(self, query: Query) -> list[dict[str, Any]]:
        """Return normalized evidence, or raise if the system cannot be reached."""


def evidence(connector_id: str, capability: str, body: dict[str, Any]) -> dict[str, Any]:
    """The shape every specialist reads. ``body`` depends on the capability, not the vendor."""
    return {"connector_id": connector_id, "capability": capability, "body": body}


class ConnectorRegistry:
    """Ask each connector. One failure is recorded and the others still return."""

    def __init__(self) -> None:
        self._connectors: list[Connector] = []

    def register(self, connector: Connector) -> None:
        if connector.capability not in CAPABILITIES:
            raise ValueError(f"unknown capability {connector.capability!r}")
        self._connectors.append(connector)

    def collect(self, query: Query) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        found: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for connector in self._connectors:
            try:
                found.extend(connector.collect(query))
            except Exception as exc:  # noqa: BLE001 — a down backend must not drop the incident
                errors.append({"connector": connector.id, "error": str(exc)})
        return found, errors


class JaegerConnector:
    """Traces. Tempo, Honeycomb, or X-Ray is this same class with a different call."""

    id = "jaeger"
    capability = "traces"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def collect(self, query: Query) -> list[dict[str, Any]]:
        raise NotImplementedError(f"GET {self.base_url}/api/traces?service={query.service}")


class FlagConnector:
    """Feature flags. LaunchDarkly or Unleash is this same class with a different call."""

    id = "feature-flags"
    capability = "feature_flags"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def collect(self, query: Query) -> list[dict[str, Any]]:
        raise NotImplementedError(f"Read flag changes for {query.service} from {self.base_url}")
