"""Scenario files as connectors.

The demo runs offline because every capability has a fixture connector.
A production deployment registers vendor connectors beside these, or instead
of them. Specialists cannot tell the difference: both emit the same schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from debug_agent.connectors.base import ConnectorRegistry, Query, evidence


class FixtureConnector:
    def __init__(self, *, capability: str, filename: str, scenario_dir: Path) -> None:
        self.capability = capability
        self.filename = filename
        self.scenario_dir = scenario_dir
        self.id = f"fixture-{capability}"

    def collect(self, query: Query) -> list[dict[str, Any]]:
        del query
        path = self.scenario_dir / self.filename
        if not path.exists():
            return []
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        return [
            evidence(
                connector_id=self.id,
                capability=self.capability,
                title=f"{self.capability} from {path.name}",
                body=body,
            )
        ]


class SourceTreeConnector:
    """Reads the scenario's ``src`` tree. This is the code the fixer may edit."""

    def __init__(self, scenario_dir: Path) -> None:
        self.scenario_dir = scenario_dir
        self.capability = "source"
        self.id = "fixture-source"

    def collect(self, query: Query) -> list[dict[str, Any]]:
        del query
        root = self.scenario_dir / "src"
        if not root.exists():
            return []
        files = []
        for path in sorted(root.rglob("*.py")):
            files.append(
                {
                    "path": path.relative_to(self.scenario_dir).as_posix(),
                    "content": path.read_text(encoding="utf-8"),
                }
            )
        if not files:
            return []
        return [
            evidence(
                connector_id=self.id,
                capability="source",
                title="scenario source tree",
                body={"files": files},
            )
        ]


def fixture_registry(scenario_dir: Path) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    mapping = {
        "traces": "traces.json",
        "logs": "logs.json",
        "metrics": "metrics.json",
        "incidents": "incidents.json",
        "feature_flags": "flags.json",
        "deploys": "deploys.json",
    }
    for capability, filename in mapping.items():
        registry.register(
            FixtureConnector(capability=capability, filename=filename, scenario_dir=scenario_dir)
        )
    registry.register(SourceTreeConnector(scenario_dir))
    return registry
