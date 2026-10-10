import json
from pathlib import Path

from debug_agent.connectors.base import ConnectorRegistry, Query
from debug_agent.connectors.fixture import fixture_registry
from debug_agent.connectors.vendors import (
    jaeger_path,
    parse_github_deployments,
    parse_jaeger,
    parse_launchdarkly,
    parse_loki,
    parse_pagerduty,
    parse_prometheus,
    parse_unleash,
)
from debug_agent.specialists.breadcrumb import BreadcrumbSpecialist


QUERY = Query(
    service="checkout",
    environment="production",
    start="2026-04-11T15:40:00Z",
    end="2026-04-11T16:10:00Z",
    symptom="timeouts",
)


def test_fixture_registry_covers_every_shipped_scenario_file():
    registry = fixture_registry(Path("scenarios/checkout_async_capture"))
    items, errors = registry.collect(QUERY)
    assert errors == []
    coverage = registry.coverage(items, errors)
    for capability in ("traces", "logs", "metrics", "incidents", "feature_flags", "deploys", "source"):
        assert coverage["capabilities"][capability] == 1


def test_failing_connector_does_not_drop_the_others():
    registry = ConnectorRegistry()

    class Ok:
        id = "ok"
        capability = "logs"

        def collect(self, query):
            del query
            return [{"id": "ok:logs", "connector_id": "ok", "capability": "logs", "title": "logs", "body": {}}]

    class Bad:
        id = "bad"
        capability = "traces"

        def collect(self, query):
            del query
            raise RuntimeError("jaeger down")

    registry.register(Ok())
    registry.register(Bad())
    items, errors = registry.collect(QUERY)
    assert [item["connector_id"] for item in items] == ["ok"]
    assert errors[0]["connector"] == "bad"


def test_jaeger_parser_feeds_the_breadcrumb_specialist():
    payload = {
        "data": [
            {
                "traceID": "abc",
                "processes": {"p1": {"serviceName": "checkout"}, "p2": {"serviceName": "ledger"}},
                "spans": [
                    {
                        "spanID": "1",
                        "operationName": "POST /charge",
                        "processID": "p1",
                        "tags": [{"key": "error", "value": True}],
                        "references": [],
                    },
                    {
                        "spanID": "2",
                        "operationName": "ledger.capture",
                        "processID": "p2",
                        "tags": [
                            {"key": "error", "value": True},
                            {"key": "idempotency_key", "value": None},
                        ],
                        "references": [{"refType": "CHILD_OF", "spanID": "1"}],
                    },
                ],
            }
        ]
    }
    items = parse_jaeger(payload, QUERY, "jaeger")
    report = BreadcrumbSpecialist().analyze(envelope={}, evidence=items, model=None)
    assert report["hypotheses"]
    assert "ledger.capture" in report["hypotheses"][0]["facts"][0]["statement"]
    assert "jaeger" in items[0]["connector_id"]


def test_vendor_paths_and_parsers_share_the_normalized_schema():
    path = jaeger_path(QUERY)
    assert path.startswith("/api/traces?")
    assert "service=checkout" in path

    logs = parse_loki(
        {"data": {"result": [{"stream": {"service": "checkout", "level": "error"}, "values": [["1", "boom"]]}]}},
        QUERY,
        "loki",
    )
    assert logs[0]["capability"] == "logs"
    assert logs[0]["body"]["entries"][0]["message"] == "boom"

    metrics = parse_prometheus(
        {"data": {"result": [{"metric": {"__name__": "errors_total", "service": "ledger"}, "values": [[1, "0.2"]]}]}},
        QUERY,
        "prometheus",
    )
    assert metrics[0]["body"]["series"][0]["points"][0]["value"] == 0.2

    incidents = parse_pagerduty(
        {"incidents": [{"id": "P1", "title": "checkout down", "created_at": "t", "urgency": "high"}]},
        QUERY,
        "pagerduty",
    )
    assert incidents[0]["body"]["incidents"][0]["source"] == "pagerduty"

    flags = parse_launchdarkly(
        {"items": [{"name": "checkout.async_capture", "previous": 0, "current": 100, "date": "t"}]},
        QUERY,
        "launchdarkly",
    )
    unleash = parse_unleash(
        {"events": [{"featureName": "checkout.async_capture", "preData": {"enabled": False}, "data": {"enabled": True}}]},
        QUERY,
        "unleash",
    )
    assert flags[0]["capability"] == unleash[0]["capability"] == "feature_flags"
    assert flags[0]["body"]["changes"][0]["flag"] == unleash[0]["body"]["changes"][0]["flag"]

    deploys = parse_github_deployments(
        {"items": [{"sha": "abc", "created_at": "t", "description": "ship", "payload": {"version": "1.42.0"}}]},
        QUERY,
        "github-deployments",
    )
    assert deploys[0]["body"]["deploys"][0]["to_version"] == "1.42.0"
    json.dumps(deploys)
