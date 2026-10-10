"""Pluggable evidence connectors."""

from debug_agent.connectors.base import CAPABILITIES, Connector, ConnectorRegistry, Query, evidence
from debug_agent.connectors.fixture import fixture_registry

__all__ = [
    "CAPABILITIES",
    "Connector",
    "ConnectorRegistry",
    "Query",
    "evidence",
    "fixture_registry",
]
