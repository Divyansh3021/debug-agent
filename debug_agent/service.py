"""Run one incident through the graph and write the audit artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from debug_agent.connectors.fixture import fixture_registry
from debug_agent.connectors.vendors import register_from_env
from debug_agent.graph import DEFAULT_MAX_ATTEMPTS, build_graph, initial_state
from debug_agent.models import Model, RecordingModel, model_from_env
from debug_agent.runners.basil import BasilRunner
from debug_agent.specialists.base import Specialist
from debug_agent.specialists.dependency import default_specialists


def run_debug(
    scenario_dir: Path | str,
    *,
    run_dir: Path | str | None = None,
    model: Model | None = None,
    specialists: list[Specialist] | None = None,
    extra_specialists: list[Specialist] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    use_env_connectors: bool = True,
) -> dict[str, Any]:
    scenario = Path(scenario_dir).resolve()
    if not (scenario / "incident.json").is_file():
        raise FileNotFoundError(f"{scenario} has no incident.json")
    destination = Path(run_dir) if run_dir else Path("runs") / scenario.name
    destination.mkdir(parents=True, exist_ok=True)

    recorder = RecordingModel(model or model_from_env())
    registry = fixture_registry(scenario)
    if use_env_connectors:
        register_from_env(registry)
    chosen = list(specialists) if specialists is not None else default_specialists()
    if extra_specialists:
        chosen.extend(extra_specialists)
    app = build_graph(
        registry=registry,
        specialists=chosen,
        model=recorder,
        runner=BasilRunner(),
    )
    final = app.invoke(
        initial_state(scenario_dir=scenario, run_dir=destination, max_attempts=max_attempts)
    )
    (destination / "model_transcript.json").write_text(
        json.dumps(recorder.transcript, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "state.json").write_text(
        json.dumps(_public_state(final), indent=2) + "\n",
        encoding="utf-8",
    )
    return final


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky source bodies from the saved state snapshot."""
    evidence = []
    for item in state.get("evidence") or []:
        if item.get("capability") == "source":
            files = (item.get("body") or {}).get("files") or []
            evidence.append({**item, "body": {"files": [{"path": f.get("path")} for f in files]}})
        else:
            evidence.append(item)
    saved = dict(state)
    saved["evidence"] = evidence
    return saved
