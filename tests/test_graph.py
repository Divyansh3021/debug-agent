import json
from pathlib import Path

from debug_agent.graph import build_graph
from debug_agent.models import ScriptedModel
from debug_agent.runners.basil import BasilRunner
from debug_agent.service import run_debug
from debug_agent.specialists.dependency import default_specialists


SCENARIO = Path("scenarios/checkout_async_capture")


class _BrokenModel:
    def complete(self, *, system: str, user: str) -> str:
        del system, user
        return "not json"


class _NoteSpecialist:
    id = "note"
    description = "Proves a new specialist is just another parallel branch."

    def analyze(self, *, envelope, evidence, model):
        del envelope, evidence, model
        return {
            "id": self.id,
            "summary": "plugin ran",
            "hypotheses": [
                {
                    "id": "note:plugin",
                    "specialist": self.id,
                    "summary": "plugin ran",
                    "confidence": 0.1,
                    "fact_ids": ["note:ran"],
                    "facts": [{"id": "note:ran", "statement": "The plugin specialist executed."}],
                }
            ],
        }


def test_checkout_scenario_loops_then_writes_a_draft_pr(tmp_path):
    final = run_debug(
        SCENARIO,
        run_dir=tmp_path / "run",
        model=ScriptedModel(),
        use_env_connectors=False,
    )
    outcome = final["outcome"]
    assert outcome["kind"] == "draft_pr"
    assert final["attempt"] == 2
    assert [item["status"] for item in final["validation_history"]] == ["failed", "passed"]
    assert final["plan_history"][0]["actions"][0]["kind"] == "flag"
    assert final["plan_history"][1]["actions"][0]["kind"] == "edit"
    assert final["diagnosis"]["primary_id"] == "change:flag-checkout.async_capture"
    assert final["diagnosis"]["grounded"] is True
    specialist_ids = {report["id"] for report in final["specialist_reports"]}
    assert specialist_ids == {"breadcrumb", "crash_correlation", "change_correlation", "dependency"}
    crash = next(report for report in final["specialist_reports"] if report["id"] == "crash_correlation")
    assert crash["narrative_grounded"] is True

    report = Path(outcome["artifacts"]["report"]).read_text(encoding="utf-8")
    diff = Path(outcome["artifacts"]["diff"]).read_text(encoding="utf-8")
    pull_request = Path(outcome["artifacts"]["pull_request"]).read_text(encoding="utf-8")
    saved = (tmp_path / "run" / "state.json").read_text(encoding="utf-8")
    assert "DEMOKEY" not in report
    assert "DEMOKEY" not in saved
    assert "demo.token" not in saved
    assert "mint_idempotency_key" in diff
    assert "idempotent" in diff
    assert "test_async_mints_key_when_missing" in final["critiques"][0]
    assert "Basil" in pull_request or "basil" in pull_request
    fixed = (tmp_path / "run" / "workspace" / "src" / "checkout" / "capture.py").read_text(encoding="utf-8")
    assert "if async_capture:" not in fixed


def test_thin_evidence_stops_before_specialists(tmp_path):
    scenario = tmp_path / "empty"
    scenario.mkdir()
    (scenario / "incident.json").write_text(
        json.dumps(
            {
                "id": "INC-0",
                "title": "Nothing to see",
                "service": "checkout",
                "environment": "production",
                "severity": "sev2",
                "symptom": "pages with no telemetry",
                "window": {"start": "2026-04-11T15:40:00Z", "end": "2026-04-11T16:10:00Z"},
            }
        ),
        encoding="utf-8",
    )
    final = run_debug(scenario, run_dir=tmp_path / "run", model=ScriptedModel(), use_env_connectors=False)
    assert final["outcome"]["kind"] == "needs_data"
    assert final["specialist_reports"] == []
    assert final["plan_history"] == []


def test_sev1_diagnoses_without_planning(tmp_path):
    scenario = tmp_path / "sev1"
    scenario.mkdir()
    # Reuse the fixture files, but the policy must refuse to plan.
    for path in SCENARIO.iterdir():
        target = scenario / path.name
        if path.is_dir():
            __import__("shutil").copytree(path, target)
        else:
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    incident = json.loads((scenario / "incident.json").read_text(encoding="utf-8"))
    incident["severity"] = "sev1"
    (scenario / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    final = run_debug(scenario, run_dir=tmp_path / "run", model=ScriptedModel(), use_env_connectors=False)
    assert final["policy"]["autonomy"] == "observe_only"
    assert final["outcome"]["kind"] == "diagnosis_only"
    assert final["diagnosis"]["primary_id"]
    assert final["plan_history"] == []


def test_ungrounded_classifier_does_not_plan(tmp_path):
    final = run_debug(
        SCENARIO,
        run_dir=tmp_path / "run",
        model=_BrokenModel(),
        use_env_connectors=False,
    )
    assert final["outcome"]["kind"] == "ungrounded"
    assert final["plan_history"] == []


def test_extra_specialist_joins_the_fanout(tmp_path):
    final = run_debug(
        SCENARIO,
        run_dir=tmp_path / "run",
        model=ScriptedModel(),
        extra_specialists=[_NoteSpecialist()],
        use_env_connectors=False,
    )
    assert any(report["id"] == "note" for report in final["specialist_reports"])
    assert final["outcome"]["kind"] == "draft_pr"


def test_mermaid_lists_the_parallel_specialists():
    app = build_graph(
        registry=__import__("debug_agent.connectors.fixture", fromlist=["fixture_registry"]).fixture_registry(SCENARIO),
        specialists=default_specialists(),
        model=ScriptedModel(),
        runner=BasilRunner(),
    )
    diagram = app.get_graph().draw_mermaid()
    for name in ("breadcrumb", "crash_correlation", "change_correlation", "dependency", "classify", "validate"):
        assert name in diagram
