"""Where outside systems plug in.

The graph never mentions Jaeger, Loki, or LaunchDarkly. A node asks the
registry for a capability (traces, logs, flags, ...). A connector is the
piece that satisfies that request for one product.

An MCP tool is a connector. A REST client is a connector. The JSON fixture
that ships with this repo is a connector. They all return the same shape.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Protocol


# The only vocabulary the rest of the pipeline knows.
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
    """The incident window. Connectors may read this and nothing else."""

    service: str
    environment: str
    start: str
    end: str
    symptom: str


class Connector(Protocol):
    id: str
    capability: str

    def collect(self, query: Query) -> list[dict[str, Any]]:
        """Return normalized evidence. Raise if the backend cannot be reached."""


def evidence(connector_id: str, capability: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "connector_id": connector_id,
        "capability": capability,
        "body": body,
    }


class ConnectorRegistry:
    """Ask every connector. Keep going when one of them fails."""

    def __init__(self) -> None:
        self._connectors: list[Connector] = []

    def register(self, connector: Connector) -> None:
        if connector.capability not in CAPABILITIES:
            raise ValueError(
                f"{connector.id} uses unknown capability {connector.capability!r}. "
                f"Expected one of {CAPABILITIES}."
            )
        self._connectors.append(connector)

    def collect(self, query: Query) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        found: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if not self._connectors:
            return found, errors
        with ThreadPoolExecutor(max_workers=len(self._connectors)) as pool:
            futures = {pool.submit(connector.collect, query): connector for connector in self._connectors}
            for future in as_completed(futures):
                connector = futures[future]
                try:
                    found.extend(future.result())
                except Exception as exc:  # noqa: BLE001 — one down backend must not sink the incident
                    errors.append({"connector": connector.id, "error": str(exc)})
        found.sort(key=lambda item: item["capability"])
        return found, errors


class JsonFileConnector:
    """One capability, already normalized, loaded from the example file.

    Production connectors look like this class: same method, a network call
    where ``body`` is assigned.
    """

    def __init__(self, capability: str, body: dict[str, Any]) -> None:
        self.capability = capability
        self.body = body
        self.id = f"fixture-{capability}"

    def collect(self, query: Query) -> list[dict[str, Any]]:
        del query  # The example file is already limited to the incident window.
        if not self.body:
            return []
        return [evidence(self.id, self.capability, self.body)]


class JaegerConnector:
    """Traces, via Jaeger ``GET /api/traces``.

    Not implemented on purpose. Copy this class for Tempo, Honeycomb, or
    X-Ray, and return the same body shape ``specialists.breadcrumb`` reads:
    ``{"traces": [{"trace_id": "...", "spans": [{"service", "operation", "status", "attributes"}]}]}``.
    """

    id = "jaeger"
    capability = "traces"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def collect(self, query: Query) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"Query {self.base_url}/api/traces for service={query.service} "
            f"between {query.start} and {query.end}, then normalize the spans."
        )


class FlagConnector:
    """Feature flags, via LaunchDarkly, Unleash, or an internal flag service.

    Same idea as ``JaegerConnector``: one capability, many products. The body
    shape the change specialist reads is ``{"changes": [{"flag", "from", "to", "at"}]}``.
    """

    id = "feature-flags"
    capability = "feature_flags"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def collect(self, query: Query) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"Read flag changes for {query.service} from {self.base_url} "
            f"between {query.start} and {query.end}."
        )
