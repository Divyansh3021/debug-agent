"""Command line entry for a single incident and for printing the graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from debug_agent.connectors.fixture import fixture_registry
from debug_agent.graph import build_graph
from debug_agent.models import ScriptedModel
from debug_agent.runners.basil import BasilRunner
from debug_agent.service import run_debug
from debug_agent.specialists.dependency import default_specialists


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="debug-agent",
        description="Run the agentic debugging graph against a scenario directory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Collect, diagnose, mitigate, validate, and write artifacts")
    run.add_argument("scenario", type=Path, help="Directory containing incident.json")
    run.add_argument("--run-dir", type=Path, default=None, help="Where to write the audit trail")
    run.add_argument("--max-attempts", type=int, default=2, help="Validation attempts before escalation")

    sub.add_parser("graph", help="Print the compiled LangGraph as Mermaid")

    args = parser.parse_args(argv)
    if args.command == "graph":
        app = build_graph(
            registry=fixture_registry(Path(".")),
            specialists=default_specialists(),
            model=ScriptedModel(),
            runner=BasilRunner(),
        )
        print(app.get_graph().draw_mermaid())
        return 0

    try:
        final = run_debug(args.scenario, run_dir=args.run_dir, max_attempts=args.max_attempts)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    outcome = final.get("outcome") or {}
    print(f"{outcome.get('incident_id')}: {outcome.get('kind')}")
    print(outcome.get("summary"))
    diagnosis = final.get("diagnosis") or {}
    if diagnosis.get("primary_id"):
        print(f"diagnosis: {diagnosis['primary_id']} ({diagnosis.get('confidence')})")
    print(f"validation attempts: {final.get('attempt', 0)}")
    for name, path in (outcome.get("artifacts") or {}).items():
        print(f"{name}: {path}")
    return 0
