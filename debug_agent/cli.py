"""Run the sample incident, or print the graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from debug_agent.graph import draw_mermaid, run_example

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLE = ROOT / "examples" / "checkout_async_capture.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="debug-agent",
        description="Walk one incident through the debugging graph. Read README.md for the map.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run an example file (the default)")
    run.add_argument("example", nargs="?", type=Path, default=DEFAULT_EXAMPLE)
    run.add_argument("--run-dir", type=Path, default=None)

    sub.add_parser("graph", help="Print the LangGraph as Mermaid")
    args = parser.parse_args(argv)

    command = args.command or "run"
    if command == "graph":
        print(draw_mermaid())
        return 0

    example = getattr(args, "example", None) or DEFAULT_EXAMPLE
    run_dir = getattr(args, "run_dir", None)
    try:
        final = run_example(example, run_dir)
    except Exception as exc:  # noqa: BLE001 — command-line boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1

    outcome = final.get("outcome") or {}
    print(f"{outcome.get('incident_id')}: {outcome.get('kind')}")
    print(outcome.get("summary"))
    diagnosis = final.get("diagnosis") or {}
    if diagnosis.get("primary_id"):
        print(f"diagnosis: {diagnosis['primary_id']} ({diagnosis.get('confidence')})")
    print()
    for line in final.get("log") or []:
        print(f"  {line}")
    print()
    print(f"report: {outcome.get('report_path')}")
    return 0
