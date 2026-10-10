"""Stage 5. Propose one mitigation.

First preference is a reversible action (turn the flag off). If validation
sends back a critique, propose the durable code change. A real model would
read ``critiques`` and the source excerpt. This skeleton switches on whether
a critique exists, which is the same information.
"""

from __future__ import annotations

from typing import Any

from debug_agent.state import DebugState, note

INSTRUCTIONS = """\
Propose one mitigation as JSON:
{"rationale": "...", "risk": "low|medium|high", "actions": [{"kind": "flag|edit|rollback", "summary": "..."}]}
Prefer a reversible flag change first. After a failed validation, edit the code.
"""


def plan(state: DebugState) -> dict[str, Any]:
    critiques = list(state.get("critiques") or [])
    excerpt = _excerpt(state)
    # prompt_for(...) is what you would send the model. scripted_plan stands in for the reply.
    model_input = prompt_for(critiques, excerpt)
    proposed = scripted_plan(critiques=critiques, diagnosis=state.get("diagnosis") or {}, excerpt=excerpt)
    proposed["model_input"] = model_input
    return {
        "plan": proposed,
        "plans": [proposed],
        **note("plan", f"attempt {len(critiques) + 1}: {proposed['actions'][0]['kind']} — {proposed['rationale']}"),
    }


def prompt_for(critiques: list[str], excerpt: str) -> str:
    """The user message a live mitigation model would see."""
    lines = [INSTRUCTIONS, "critiques:"]
    lines.extend(critiques or ["(none — first attempt)"])
    lines.extend(["source:", excerpt or "(no source excerpt)"])
    return "\n".join(lines)


def scripted_plan(*, critiques: list[str], diagnosis: dict[str, Any], excerpt: str) -> dict[str, Any]:
    """Stand-in for the mitigation model. Replace this, keep the action schema."""
    primary = diagnosis.get("primary_id") or "the diagnosis"
    if not critiques:
        return {
            "rationale": f"Given {primary}, ramp the flag off. That stops new traffic taking the broken path and is easy to undo.",
            "risk": "low",
            "actions": [
                {
                    "kind": "flag",
                    "summary": "Set checkout.async_capture from 100 back to 0.",
                }
            ],
        }
    return {
        "rationale": (
            "The flag ramp does not fix the async path itself. Mint an idempotency key there too, "
            "so the ledger contract holds while the flag is on."
        ),
        "risk": "medium",
        "actions": [
            {
                "kind": "edit",
                "summary": "On the async path, mint a key when the caller did not supply one.",
                "excerpt": excerpt,
            }
        ],
    }


def _excerpt(state: DebugState) -> str:
    for item in state.get("evidence") or []:
        if item.get("capability") != "source":
            continue
        files = (item.get("body") or {}).get("files") or []
        if files:
            return str(files[0].get("excerpt") or "")
    return ""
