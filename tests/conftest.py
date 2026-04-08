"""Shared fixtures for retro-pilot test suite."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.models import (
    ActionItem,
    Evidence,
    Incident,
    PostMortem,
    RootCause,
    Timeline,
    TimelineEvent,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
RESOLVED = datetime(2026, 1, 15, 14, 47, 0, tzinfo=UTC)


@pytest.fixture
def sample_incident() -> Incident:
    data = json.loads((FIXTURES_DIR / "sample_incident.json").read_text())
    return Incident(**data)


@pytest.fixture
def sample_evidence() -> Evidence:
    data = json.loads((FIXTURES_DIR / "sample_evidence.json").read_text())
    return Evidence(**data)


@pytest.fixture
def sample_root_cause() -> RootCause:
    return RootCause(
        primary="Connection pool exhausted in auth-service caused cascading timeouts",
        contributing_factors=[
            "Pool size (50) not reviewed after 3x traffic growth over 6 months",
            "No pool saturation alert existed to warn before exhaustion",
        ],
        trigger="Marketing campaign launched at 14:00 increased login rate 4x",
        blast_radius="payment-service and session-service — all auth-service dependents",
        confidence="HIGH",
        evidence_refs=["log:auth-service:14:05", "metric:connection_pool_utilisation:14:05"],
    )


@pytest.fixture
def sample_action_items() -> list[ActionItem]:
    return [
        ActionItem(
            title="Increase Redis connection pool size from 50 to 200",
            owner_role="Platform team",
            deadline_days=7,
            priority="P1",
            type="prevention",
            acceptance_criteria=(
                "Pool size set to 200, load test at 5x current peak traffic passes "
                "with <5% error rate in staging before prod deployment"
            ),
        ),
        ActionItem(
            title="Add connection pool saturation PagerDuty alert",
            owner_role="Platform team",
            deadline_days=14,
            priority="P1",
            type="detection",
            acceptance_criteria=(
                "Alert fires when pool utilisation exceeds 80% for 5 consecutive minutes. "
                "Tested by manually raising utilisation in staging."
            ),
        ),
        ActionItem(
            title="Add connection pool load test to release checklist",
            owner_role="Engineering team",
            deadline_days=30,
            priority="P2",
            type="prevention",
            acceptance_criteria=(
                "Release checklist includes load test step. "
                "Verified present in next release review."
            ),
        ),
    ]


@pytest.fixture
def sample_timeline() -> Timeline:
    return Timeline(
        events=[
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 1, tzinfo=UTC),
                description="Metric connection_pool_utilisation = 82%",
                source="metric", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 2, tzinfo=UTC),
                description="[auth-service] Connection pool utilisation at 85%",
                source="log", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 5, tzinfo=UTC),
                description="[auth-service] Connection pool exhausted",
                source="log", significance="critical",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 7, tzinfo=UTC),
                description="[payment-service] Upstream timeout from auth-service",
                source="log", significance="critical",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 12, tzinfo=UTC),
                description="[Slack] oncall: Incident declared",
                source="slack", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 47, tzinfo=UTC),
                description="[Slack] oncall: Incident resolved",
                source="slack", significance="critical",
            ),
        ],
        first_signal_at=datetime(2026, 1, 15, 14, 1, tzinfo=UTC),
        detection_lag_minutes=11,
        resolution_duration_minutes=47,
    )


@pytest.fixture
def sample_postmortem(
    sample_incident, sample_timeline, sample_root_cause, sample_action_items
) -> PostMortem:
    return PostMortem(
        incident=sample_incident,
        executive_summary=(
            "Auth service experienced a 47-minute outage affecting payment and session services. "
            "The outage was caused by a capacity limit that had not been reviewed since user traffic tripled. "
            "Capacity has been increased and monitoring added to prevent recurrence."
        ),
        timeline=sample_timeline,
        root_cause=sample_root_cause,
        action_items=sample_action_items,
        lessons_learned=[
            "Connection pool capacity should be reviewed whenever traffic grows by more than 50%.",
            "Detection lag often exceeds 10 minutes when monitoring measures availability, not leading indicators.",
        ],
        similar_incidents=["INC-2026-0089"],
        generated_at=NOW,
    )


@pytest.fixture
def mock_backend():
    """Mock LLM backend. Returns configurable responses."""
    backend = MagicMock()
    backend.complete.return_value = "Mock LLM response"
    backend.complete_with_tools.return_value = MagicMock(
        content=[MagicMock(type="text", text="done")],
        stop_reason="end_turn",
    )
    return backend


@pytest.fixture
def mock_embedder():
    """Mock embedder returning a fixed 384-dim vector."""
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 384
    embedder.embed_many.return_value = [[0.1] * 384]
    return embedder


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB client + collection."""
    collection = MagicMock()
    collection.count.return_value = 0
    collection.query.return_value = {
        "ids": [[]], "distances": [[]], "metadatas": [[]]
    }
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client, collection
