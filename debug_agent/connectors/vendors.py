"""Vendor connectors that normalize into the same evidence schema.

Each factory returns a connector the registry can hold next to any other
implementation of that capability. URL builders and parsers are separate so
the parsing rules can be tested without a network call.

Supported subsets, not full vendor APIs:

- Jaeger ``GET /api/traces``
- Grafana Loki ``GET /loki/api/v1/query_range``
- Prometheus ``GET /api/v1/query_range``
- PagerDuty incidents list
- LaunchDarkly audit log items
- Unleash feature events
- GitHub deployment objects
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable

from debug_agent.connectors.base import ConnectorRegistry, Query, evidence

Parser = Callable[[dict[str, Any], Query, str], list[dict[str, Any]]]
PathBuilder = Callable[[Query], str]


def _epoch_seconds(value: str) -> str:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return str(int(moment.timestamp()))


def _epoch_micros(value: str) -> str:
    return str(int(_epoch_seconds(value)) * 1_000_000)


def _epoch_nanos(value: str) -> str:
    return str(int(_epoch_seconds(value)) * 1_000_000_000)


class HttpConnector:
    def __init__(
        self,
        *,
        id: str,
        capability: str,
        base_url: str,
        path_for: PathBuilder,
        parse: Parser,
        headers: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> None:
        self.id = id
        self.capability = capability
        self.base_url = base_url.rstrip("/")
        self.path_for = path_for
        self.parse = parse
        self.headers = headers or {}
        self.timeout = timeout

    def collect(self, query: Query) -> list[dict[str, Any]]:
        url = self.base_url + self.path_for(query)
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.id} request failed: {exc}") from exc
        if not isinstance(payload, dict) and not isinstance(payload, list):
            raise RuntimeError(f"{self.id} returned {type(payload).__name__}, expected JSON")
        if isinstance(payload, list):
            payload = {"items": payload}
        return self.parse(payload, query, self.id)


def jaeger_path(query: Query) -> str:
    params = {
        "service": query.service,
        "start": _epoch_micros(query.start),
        "end": _epoch_micros(query.end),
        "limit": "20",
    }
    return "/api/traces?" + urllib.parse.urlencode(params)


def parse_jaeger(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    traces = []
    for trace in payload.get("data") or []:
        processes = trace.get("processes") or {}
        spans = []
        for span in trace.get("spans") or []:
            process = processes.get(span.get("processID")) or {}
            parent = None
            for ref in span.get("references") or []:
                if ref.get("refType") == "CHILD_OF":
                    parent = ref.get("spanID")
            tags = {tag.get("key"): tag.get("value") for tag in span.get("tags") or []}
            status = "error" if tags.get("error") in (True, "true", "True") else "ok"
            attributes = {key: value for key, value in tags.items() if key != "error"}
            spans.append(
                {
                    "span_id": span.get("spanID"),
                    "parent_span_id": parent,
                    "service": process.get("serviceName"),
                    "operation": span.get("operationName"),
                    "status": status,
                    "attributes": attributes,
                }
            )
        traces.append({"trace_id": trace.get("traceID"), "spans": spans})
    if not traces:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="traces",
            title="Jaeger traces",
            body={"traces": traces},
        )
    ]


def loki_path(query: Query) -> str:
    selector = '{service="%s"}' % query.service.replace('"', "")
    params = {
        "query": selector,
        "start": _epoch_nanos(query.start),
        "end": _epoch_nanos(query.end),
        "limit": "100",
    }
    return "/loki/api/v1/query_range?" + urllib.parse.urlencode(params)


def parse_loki(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    entries = []
    for stream in (payload.get("data") or {}).get("result") or []:
        labels = stream.get("stream") or {}
        for timestamp, message in stream.get("values") or []:
            entries.append(
                {
                    "timestamp": str(timestamp),
                    "level": labels.get("level") or labels.get("detected_level") or "info",
                    "service": labels.get("service"),
                    "message": message,
                    "attributes": {key: value for key, value in labels.items() if key != "service"},
                }
            )
    if not entries:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="logs",
            title="Loki log streams",
            body={"entries": entries},
        )
    ]


def prometheus_path(query: Query) -> str:
    promql = 'sum(rate(errors_total{service="%s"}[5m]))' % query.service.replace('"', "")
    params = {
        "query": promql,
        "start": _epoch_seconds(query.start),
        "end": _epoch_seconds(query.end),
        "step": "60",
    }
    return "/api/v1/query_range?" + urllib.parse.urlencode(params)


def parse_prometheus(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    series = []
    for item in (payload.get("data") or {}).get("result") or []:
        metric = item.get("metric") or {}
        points = []
        for timestamp, value in item.get("values") or []:
            points.append({"timestamp": str(timestamp), "value": float(value)})
        series.append(
            {
                "name": metric.get("__name__") or "errors_total",
                "service": metric.get("service"),
                "points": points,
            }
        )
    if not series:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="metrics",
            title="Prometheus range query",
            body={"series": series},
        )
    ]


def pagerduty_path(query: Query) -> str:
    params = {"since": query.start, "until": query.end, "limit": "25"}
    return "/incidents?" + urllib.parse.urlencode(params)


def parse_pagerduty(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    incidents = []
    for item in payload.get("incidents") or []:
        incidents.append(
            {
                "id": item.get("id") or item.get("incident_number"),
                "summary": item.get("title") or item.get("summary"),
                "severity": item.get("urgency") or item.get("priority"),
                "opened_at": item.get("created_at"),
                "source": "pagerduty",
            }
        )
    if not incidents:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="incidents",
            title="PagerDuty incidents",
            body={"incidents": incidents},
        )
    ]


def launchdarkly_path(query: Query) -> str:
    params = {"limit": "20", "q": query.service}
    return "/api/v2/auditlog?" + urllib.parse.urlencode(params)


def parse_launchdarkly(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    changes = []
    for item in payload.get("items") or []:
        name = item.get("name") or item.get("flagKey")
        if not name:
            continue
        changes.append(
            {
                "flag": name,
                "from": item.get("previous"),
                "to": item.get("current"),
                "at": item.get("date") or item.get("createdAt"),
            }
        )
    if not changes:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="feature_flags",
            title="LaunchDarkly audit log",
            body={"changes": changes},
        )
    ]


def unleash_path(query: Query) -> str:
    params = {"project": query.service}
    return "/api/admin/events?" + urllib.parse.urlencode(params)


def parse_unleash(payload: dict[str, Any], query: Query, connector_id: str) -> list[dict[str, Any]]:
    del query
    changes = []
    for item in payload.get("events") or payload.get("items") or []:
        name = item.get("featureName") or item.get("feature")
        if not name:
            continue
        before = item.get("preData") or {}
        after = item.get("data") or {}
        changes.append(
            {
                "flag": name,
                "from": before.get("enabled", item.get("from")),
                "to": after.get("enabled", item.get("to")),
                "at": item.get("createdAt") or item.get("at"),
            }
        )
    if not changes:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="feature_flags",
            title="Unleash feature events",
            body={"changes": changes},
        )
    ]


def github_deployments_path(query: Query) -> str:
    params = {"environment": query.environment, "per_page": "20"}
    return "?" + urllib.parse.urlencode(params)


def parse_github_deployments(
    payload: dict[str, Any], query: Query, connector_id: str
) -> list[dict[str, Any]]:
    deploys = []
    for item in payload.get("items") or []:
        body = item.get("payload") or {}
        deploys.append(
            {
                "service": body.get("service") or query.service,
                "from_version": body.get("from_version"),
                "to_version": body.get("version") or item.get("sha"),
                "at": item.get("created_at"),
                "summary": item.get("description") or "",
            }
        )
    if not deploys:
        return []
    return [
        evidence(
            connector_id=connector_id,
            capability="deploys",
            title="GitHub deployments",
            body={"deploys": deploys},
        )
    ]


def jaeger_connector(base_url: str) -> HttpConnector:
    return HttpConnector(
        id="jaeger",
        capability="traces",
        base_url=base_url,
        path_for=jaeger_path,
        parse=parse_jaeger,
    )


def loki_connector(base_url: str) -> HttpConnector:
    return HttpConnector(
        id="loki",
        capability="logs",
        base_url=base_url,
        path_for=loki_path,
        parse=parse_loki,
    )


def prometheus_connector(base_url: str) -> HttpConnector:
    return HttpConnector(
        id="prometheus",
        capability="metrics",
        base_url=base_url,
        path_for=prometheus_path,
        parse=parse_prometheus,
    )


def pagerduty_connector(base_url: str, token: str) -> HttpConnector:
    return HttpConnector(
        id="pagerduty",
        capability="incidents",
        base_url=base_url,
        path_for=pagerduty_path,
        parse=parse_pagerduty,
        headers={"Authorization": f"Token token={token}", "Accept": "application/vnd.pagerduty+json;version=2"},
    )


def launchdarkly_connector(base_url: str, token: str) -> HttpConnector:
    return HttpConnector(
        id="launchdarkly",
        capability="feature_flags",
        base_url=base_url,
        path_for=launchdarkly_path,
        parse=parse_launchdarkly,
        headers={"Authorization": token},
    )


def unleash_connector(base_url: str, token: str) -> HttpConnector:
    return HttpConnector(
        id="unleash",
        capability="feature_flags",
        base_url=base_url,
        path_for=unleash_path,
        parse=parse_unleash,
        headers={"Authorization": token},
    )


def github_deployments_connector(base_url: str, token: str | None = None) -> HttpConnector:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return HttpConnector(
        id="github-deployments",
        capability="deploys",
        base_url=base_url,
        path_for=github_deployments_path,
        parse=parse_github_deployments,
        headers=headers,
    )


def register_from_env(registry: ConnectorRegistry) -> list[str]:
    """Attach connectors for whichever vendor URLs are configured. Return their ids."""
    registered: list[str] = []

    def add(connector: HttpConnector) -> None:
        registry.register(connector)
        registered.append(connector.id)

    if url := os.environ.get("JAEGER_URL"):
        add(jaeger_connector(url))
    if url := os.environ.get("LOKI_URL"):
        add(loki_connector(url))
    if url := os.environ.get("PROMETHEUS_URL"):
        add(prometheus_connector(url))
    if url := os.environ.get("PAGERDUTY_URL"):
        add(pagerduty_connector(url, os.environ.get("PAGERDUTY_TOKEN", "")))
    if url := os.environ.get("LAUNCHDARKLY_URL"):
        add(launchdarkly_connector(url, os.environ.get("LAUNCHDARKLY_TOKEN", "")))
    if url := os.environ.get("UNLEASH_URL"):
        add(unleash_connector(url, os.environ.get("UNLEASH_TOKEN", "")))
    if url := os.environ.get("GITHUB_DEPLOYMENTS_URL"):
        add(github_deployments_connector(url, os.environ.get("GITHUB_TOKEN")))
    return registered
