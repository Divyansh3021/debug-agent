"""Prompt templates for the two model judgments in the graph.

Specialists extract facts in code. The model only classifies among those
facts and, later, proposes a mitigation. Keeping the prompts in one module
makes that boundary easy to review.
"""

from __future__ import annotations

import json
from typing import Any


CLASSIFY_SYSTEM = """You are the classification step of a debugging agent.
You receive hypotheses already extracted from evidence. Choose the hypothesis
that best explains the incident. You may not invent a hypothesis id or a fact id.
Respond with one JSON object and no other text:
{"primary_id": "<id from the list>", "narrative": "<two or three sentences tying trigger to mechanism>", "cited_fact_ids": ["<fact id>", "..."]}
"""

NARRATE_SYSTEM = """You write one sentence for a debugging specialist.
Cite only fact ids that appear in the prompt. Respond with one JSON object:
{"narrative": "<one sentence>", "cited_fact_ids": ["<fact id>"]}
"""

MITIGATE_SYSTEM = """You are the mitigation step of a debugging agent.
Prefer a reversible action first. After a validation failure, propose a durable
code edit that addresses the critique. Edit only source that appears in the prompt.
Respond with one JSON object and no other text:
{"rationale": "<why this action>", "risk": "low|medium|high", "actions": [
  {"kind": "flag", "summary": "<what changes>", "payload": {"flag": "<name>", "from": 0, "to": 0}},
  {"kind": "edit", "summary": "<what changes>", "payload": {"path": "<repo-relative path>", "old": "<exact existing text>", "new": "<replacement text>"}},
  {"kind": "rollback", "summary": "<what changes>", "payload": {"service": "<name>", "to_version": "<version>"}}
]}
Use one action. An edit's old text must occur exactly once in the named file.
"""


def classification_prompt(*, envelope: dict[str, Any], hypotheses: list[dict[str, Any]]) -> str:
    lines = [
        "task: classify",
        f"incident: {envelope.get('id')} {envelope.get('title')}",
        f"service: {envelope.get('service')}",
        f"symptom: {envelope.get('symptom')}",
        "hypotheses:",
    ]
    for hypothesis in hypotheses:
        lines.append(f"hypothesis_id: {hypothesis['id']}")
        lines.append(f"specialist: {hypothesis['specialist']}")
        lines.append(f"confidence: {hypothesis['confidence']}")
        lines.append(f"summary: {hypothesis['summary']}")
        for fact in hypothesis.get("facts") or []:
            lines.append(f"fact_id: {fact['id']}")
            lines.append(f"fact: {fact['statement']}")
        lines.append("")
    return "\n".join(lines)


def narration_prompt(*, specialist: str, facts: list[dict[str, str]]) -> str:
    lines = [f"task: narrate-{specialist}", "facts:"]
    for fact in facts:
        lines.append(f"fact_id: {fact['id']}")
        lines.append(f"fact: {fact['statement']}")
    return "\n".join(lines)


def mitigation_prompt(
    *,
    envelope: dict[str, Any],
    diagnosis: dict[str, Any],
    attempt: int,
    critiques: list[str],
    source_files: list[dict[str, str]],
) -> str:
    lines = [
        "task: mitigate",
        f"attempt: {attempt}",
        f"incident: {envelope.get('id')} {envelope.get('title')}",
        f"symptom: {envelope.get('symptom')}",
        f"primary_hypothesis: {diagnosis.get('primary_id')}",
        f"narrative: {diagnosis.get('narrative')}",
        "prior_critiques:",
    ]
    if critiques:
        lines.extend(critiques)
    else:
        lines.append("(none — this is the first plan)")
    lines.append("source_files:")
    for item in source_files:
        lines.append(f"path: {item['path']}")
        lines.append(item["content"])
        lines.append("")
    lines.append(f"diagnosis_json: {json.dumps(_public_diagnosis(diagnosis))}")
    return "\n".join(lines)


def _public_diagnosis(diagnosis: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_id": diagnosis.get("primary_id"),
        "narrative": diagnosis.get("narrative"),
        "confidence": diagnosis.get("confidence"),
        "alternatives": [
            {"id": item.get("id"), "summary": item.get("summary")}
            for item in diagnosis.get("alternatives") or []
        ],
    }
