"""The architecture, as a LangGraph.

Read this file first. The functions it calls live in ``stages/`` and
``specialists.py``. This file is only the boxes and the arrows.

    collect → policy → specialists (parallel) → classify → plan → validate
                 │                                  │                  │
                 └─ needs data ──────────────► finalize ◄── low confidence
                                                                    │
                                              validate failed ◄─────┘
                                              (back to plan, twice at most)
                                                                    │
                                              passed → approve → finalize
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from debug_agent.specialists import breadcrumb, change_correlation, crash_correlation, dependency
from debug_agent.stages.classify import CONFIDENCE_FLOOR, classify
from debug_agent.stages.collect import collect
from debug_agent.stages.finalize import approve_node, finalize
from debug_agent.stages.plan import plan
from debug_agent.stages.policy import policy
from debug_agent.stages.validate import MAX_ATTEMPTS, validate
from debug_agent.state import DebugState

# Adding a specialist means adding one line here and a function in specialists.py.
SPECIALISTS: list[tuple[str, Any]] = [
    ("breadcrumb", breadcrumb),
    ("crash_correlation", crash_correlation),
    ("change_correlation", change_correlation),
    ("dependency", dependency),
]


def build_graph():
    """Wire the diagram. Nothing in this function fetches data or calls a model."""
    graph = StateGraph(DebugState)
    graph.add_node("collect", collect)
    graph.add_node("policy", policy)
    for name, fn in SPECIALISTS:
        graph.add_node(name, fn)
    graph.add_node("classify", classify)
    graph.add_node("plan", plan)
    graph.add_node("validate", validate)
    graph.add_node("approve", approve_node)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "collect")
    graph.add_edge("collect", "policy")
    graph.add_conditional_edges("policy", route_after_policy, [name for name, _ in SPECIALISTS] + ["finalize"])
    # One edge from the whole fan-out: classify waits for every specialist.
    graph.add_edge([name for name, _ in SPECIALISTS], "classify")
    graph.add_conditional_edges("classify", route_after_diagnosis, ["plan", "finalize"])
    graph.add_edge("plan", "validate")
    graph.add_conditional_edges("validate", route_after_validation, ["plan", "approve", "finalize"])
    graph.add_edge("approve", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def route_after_policy(state: DebugState) -> str | list[Send]:
    """Skip diagnosis when we already know the evidence is too thin."""
    if (state.get("policy") or {}).get("autonomy") == "needs_data":
        return "finalize"
    return [
        Send(name, {"incident": state.get("incident") or {}, "evidence": state.get("evidence") or []})
        for name, _ in SPECIALISTS
    ]


def route_after_diagnosis(state: DebugState) -> str:
    """Do not plan a change from a weak or forbidden diagnosis."""
    autonomy = (state.get("policy") or {}).get("autonomy")
    diagnosis = state.get("diagnosis") or {}
    if autonomy in {"observe_only", "needs_data"}:
        return "finalize"
    if not diagnosis.get("primary_id") or float(diagnosis.get("confidence") or 0) < CONFIDENCE_FLOOR:
        return "finalize"
    return "plan"


def route_after_validation(state: DebugState) -> str:
    """Pass goes to approval. Failure goes back to the planner, then stops."""
    if (state.get("validation") or {}).get("status") == "passed":
        return "approve"
    if int(state.get("attempt") or 0) >= MAX_ATTEMPTS:
        return "finalize"
    return "plan"


def run_example(example_path: Path | str, run_dir: Path | str | None = None) -> dict[str, Any]:
    """Run one example file through the graph and write ``report.md``."""
    path = Path(example_path)
    destination = Path(run_dir) if run_dir else Path("runs") / path.stem
    app = build_graph()
    return app.invoke(
        {
            "example_path": str(path),
            "run_dir": str(destination),
            "hypotheses": [],
            "plans": [],
            "validations": [],
            "critiques": [],
            "log": [],
            "attempt": 0,
        }
    )


def draw_mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()
