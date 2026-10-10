"""The arrows.

Read this file first. Each name is a function in stages/ or specialists.py.
This file only says what runs, and what runs next.

    collect → policy → specialists, together → classify → plan → validate
                 │                                    │              │
                 └── not enough evidence ──► finalize ◄── not allowed to act
                                                              │
                                            validate failed ──┘ back to plan, once
                                                              │
                                            passed → approve → finalize
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from debug_agent.specialists import breadcrumb, change_correlation, crash_correlation, dependency
from debug_agent.stages.classify import classify
from debug_agent.stages.collect import collect
from debug_agent.stages.finalize import finalize
from debug_agent.stages.plan import plan
from debug_agent.stages.policy import approve, policy
from debug_agent.stages.validate import validate
from debug_agent.state import DebugState

# A new specialist is one function in specialists.py and one line here.
SPECIALISTS: list[tuple[str, Any]] = [
    ("breadcrumb", breadcrumb),
    ("crash_correlation", crash_correlation),
    ("change_correlation", change_correlation),
    ("dependency", dependency),
]


def build_graph():
    graph = StateGraph(DebugState)
    graph.add_node("collect", collect)
    graph.add_node("policy", policy)
    for name, fn in SPECIALISTS:
        graph.add_node(name, fn)
    graph.add_node("classify", classify)
    graph.add_node("plan", plan)
    graph.add_node("validate", validate)
    graph.add_node("approve", approve)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "collect")
    graph.add_edge("collect", "policy")
    graph.add_conditional_edges("policy", route_after_policy, [name for name, _ in SPECIALISTS] + ["finalize"])
    # One edge from every specialist: classify waits until all of them finish.
    graph.add_edge([name for name, _ in SPECIALISTS], "classify")
    graph.add_conditional_edges("classify", route_after_diagnosis, ["plan", "finalize"])
    graph.add_edge("plan", "validate")
    graph.add_conditional_edges("validate", route_after_validation, ["plan", "approve", "finalize"])
    graph.add_edge("approve", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def route_after_policy(state: DebugState) -> str | list[Send]:
    if (state.get("policy") or {}).get("autonomy") == "needs_data":
        return "finalize"
    return [
        Send(name, {"incident": state.get("incident") or {}, "evidence": state.get("evidence") or []})
        for name, _ in SPECIALISTS
    ]


def route_after_diagnosis(state: DebugState) -> str:
    autonomy = (state.get("policy") or {}).get("autonomy")
    diagnosis = state.get("diagnosis") or {}
    confident = bool(diagnosis.get("primary_id")) and float(diagnosis.get("confidence") or 0) >= 0.45
    if autonomy in {"observe_only", "needs_data"} or not confident:
        return "finalize"
    return "plan"


def route_after_validation(state: DebugState) -> str:
    if (state.get("validation") or {}).get("status") == "passed":
        return "approve"
    if int(state.get("attempt") or 0) >= 2:
        return "finalize"
    return "plan"


def draw_mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()
