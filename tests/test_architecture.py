"""The behaviors a reader of the diagram should be able to point at in a test."""

import json
from pathlib import Path

from debug_agent.connectors import ConnectorRegistry, Query
from debug_agent.graph import draw_mermaid, run_example
from debug_agent.stages.classify import accept_classification
from debug_agent.stages.policy import approve, decide_autonomy

EXAMPLE = Path("examples/checkout_async_capture.json")
QUERY = Query("checkout", "production", "2026-04-11T15:40:00Z", "2026-04-11T16:10:00Z", "timeouts")


def test_sample_incident_tries_a_flag_then_writes_a_draft(tmp_path):
    final = run_example(EXAMPLE, tmp_path / "run")
    assert final["outcome"]["kind"] == "draft_pr"
    assert final["policy"]["autonomy"] == "propose"
    assert final["diagnosis"]["primary_id"] == "change:flag-checkout.async_capture"
    assert final["diagnosis"]["grounded"] is True
    assert [item["status"] for item in final["validations"]] == ["failed", "passed"]
    assert [item["actions"][0]["kind"] for item in final["plans"]] == ["flag", "edit"]
    specialists = {item["specialist"] for item in final["hypotheses"]}
    assert specialists == {"breadcrumb", "crash_correlation", "change_correlation", "dependency"}

    report = Path(final["outcome"]["report_path"]).read_text(encoding="utf-8")
    saved = json.dumps(final["evidence"])
    assert "DEMOKEY" not in report
    assert "DEMOKEY" not in saved
    assert "demo.token" not in saved


def test_no_traces_or_logs_stops_before_specialists(tmp_path):
    scenario = tmp_path / "thin.json"
    scenario.write_text(
        json.dumps(
            {
                "incident": {
                    "id": "INC-0",
                    "title": "No telemetry",
                    "service": "checkout",
                    "environment": "production",
                    "severity": "sev2",
                    "symptom": "a page with no logs",
                    "window": {"start": "2026-04-11T15:40:00Z", "end": "2026-04-11T16:10:00Z"},
                },
                "metrics": {"series": [{"name": "errors", "service": "checkout", "before": 0.1, "after": 0.9}]},
            }
        ),
        encoding="utf-8",
    )
    final = run_example(scenario, tmp_path / "run")
    assert final["outcome"]["kind"] == "needs_data"
    assert final["hypotheses"] == []
    assert final["plans"] == []


def test_classifier_cannot_invent_a_cause():
    hypotheses = [
        {
            "id": "change:flag-checkout.async_capture",
            "summary": "flag flipped",
            "confidence": 0.8,
            "facts": [{"id": "flag:checkout.async_capture", "statement": "flipped"}],
        }
    ]
    rejected = accept_classification(
        hypotheses,
        {"primary_id": "made-up", "narrative": "I invented this.", "cited_fact_ids": ["flag:checkout.async_capture"]},
    )
    assert rejected["grounded"] is False
    assert rejected["primary_id"] is None


def test_policy_and_approval_are_code():
    assert decide_autonomy({"severity": "sev1", "environment": "production"}, {"capabilities": {"traces": 1}})["autonomy"] == "observe_only"
    assert decide_autonomy({"severity": "sev2", "environment": "production", "sensitive_domains": ["payments"]}, {"capabilities": {"logs": 1}})["autonomy"] == "propose"
    assert decide_autonomy({"severity": "sev3", "environment": "staging"}, {"capabilities": {"traces": 1}})["autonomy"] == "auto_fix"
    assert approve(autonomy="propose", risk="medium", validation_status="passed")["decision"] == "draft_pr"
    assert approve(autonomy="auto_fix", risk="high", validation_status="passed")["decision"] == "escalate"


def test_one_failing_connector_does_not_drop_the_others():
    registry = ConnectorRegistry()

    class Ok:
        id = "ok"
        capability = "logs"

        def collect(self, query):
            del query
            return [{"connector_id": "ok", "capability": "logs", "body": {}}]

    class Bad:
        id = "jaeger"
        capability = "traces"

        def collect(self, query):
            del query
            raise RuntimeError("jaeger down")

    registry.register(Ok())
    registry.register(Bad())
    items, errors = registry.collect(QUERY)
    assert [item["connector_id"] for item in items] == ["ok"]
    assert errors[0]["connector"] == "jaeger"


def test_the_diagram_contains_every_stage():
    diagram = draw_mermaid()
    for name in ("collect", "policy", "breadcrumb", "crash_correlation", "change_correlation", "dependency", "classify", "plan", "validate", "finalize"):
        assert name in diagram
