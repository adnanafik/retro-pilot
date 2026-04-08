"""Tests for EvidenceCollector agent."""
from datetime import UTC, datetime

from agents.evidence_collector import EvidenceCollector
from shared.models import Evidence, Incident

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_incident() -> Incident:
    return Incident(
        id="INC-2026-0001",
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=UTC),
        affected_services=["auth-service"],
        involved_repos=["acme/auth-service"],
        slack_channel="#incidents",
        reported_by="oncall",
    )


def test_evidence_collector_returns_evidence_model():
    """EvidenceCollector.run() returns a typed Evidence in DEMO_MODE."""
    collector = EvidenceCollector()
    inc = make_incident()
    result = collector.run(inc, demo_mode=True)
    assert isinstance(result, Evidence)


def test_evidence_has_logs_in_demo_mode():
    collector = EvidenceCollector()
    result = collector.run(make_incident(), demo_mode=True)
    assert isinstance(result.logs, list)
    assert isinstance(result.metrics, list)
    assert isinstance(result.git_events, list)
    assert isinstance(result.slack_messages, list)


def test_evidence_collector_describe():
    collector = EvidenceCollector()
    assert "evidence" in collector.describe().lower()


def test_evidence_collector_gaps_list_is_present():
    collector = EvidenceCollector()
    result = collector.run(make_incident(), demo_mode=True)
    assert isinstance(result.gaps, list)


def test_evidence_collector_handles_worker_exception_gracefully():
    """If one worker raises, the gap is recorded and other workers still return data."""
    from unittest.mock import AsyncMock, patch
    collector = EvidenceCollector()
    with patch.object(collector, "_run_slack_worker", new_callable=AsyncMock, side_effect=RuntimeError("Slack down")):
        result = collector.run(make_incident(), demo_mode=True)
    assert isinstance(result, Evidence)
    assert any("slack" in g.lower() for g in result.gaps)
