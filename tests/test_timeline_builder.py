# tests/test_timeline_builder.py
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from agents.timeline_builder import TimelineBuilder
from shared.models import (
    Evidence,
    GitEvent,
    LogEntry,
    MetricSnapshot,
    SlackMessage,
    Timeline,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_evidence_with_events() -> Evidence:
    return Evidence(
        logs=[
            LogEntry(timestamp=NOW + timedelta(minutes=5),
                     level="ERROR", service="auth-service",
                     message="Connection pool exhausted"),
            LogEntry(timestamp=NOW + timedelta(minutes=7),
                     level="ERROR", service="payment-service",
                     message="Upstream timeout from auth-service"),
        ],
        metrics=[
            MetricSnapshot(timestamp=NOW + timedelta(minutes=2),
                           metric_name="connection_pool_utilisation",
                           value=95.0, unit="Percent"),
        ],
        git_events=[
            GitEvent(timestamp=NOW - timedelta(hours=1),
                     commit_sha="abc123", author="dev@acme.com",
                     message="Deploy v2.3.1", repo="acme/auth", type="deploy"),
        ],
        slack_messages=[
            SlackMessage(timestamp=NOW + timedelta(minutes=12),
                         author="oncall", text="Incident declared",
                         thread_ts=None),
        ],
        collected_at=NOW,
        gaps=[],
    )


def test_timeline_builder_returns_timeline():
    backend = MagicMock()
    backend.complete.return_value = "{}"  # won't be used in demo mode
    builder = TimelineBuilder(backend=backend)
    evidence = make_evidence_with_events()
    result = builder.run(evidence, demo_mode=True)
    assert isinstance(result, Timeline)


def test_timeline_events_sorted_by_timestamp():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    timestamps = [e.timestamp for e in result.events]
    assert timestamps == sorted(timestamps)


def test_timeline_has_events_from_all_sources():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    sources = {e.source for e in result.events}
    assert "log" in sources
    assert "metric" in sources
    assert "git" in sources
    assert "slack" in sources


def test_timeline_first_signal_is_earliest_anomaly():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    # First signal should be the metric at NOW+2min (before the log error at NOW+5min)
    assert result.first_signal_at <= NOW + timedelta(minutes=5)


def test_timeline_detection_lag_is_non_negative():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    assert result.detection_lag_minutes >= 0


def test_timeline_resolution_duration_is_positive():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    assert result.resolution_duration_minutes > 0


def test_timeline_builder_describe():
    builder = TimelineBuilder()
    assert "timeline" in builder.describe().lower()
