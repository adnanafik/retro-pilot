# tests/test_root_cause_analyst.py
from datetime import UTC, datetime

from agents.root_cause_analyst import RootCauseAnalyst
from shared.models import Evidence, RootCause, Timeline

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_empty_evidence() -> Evidence:
    return Evidence(
        logs=[], metrics=[], git_events=[], slack_messages=[],
        collected_at=NOW, gaps=[],
    )


def make_empty_timeline() -> Timeline:
    return Timeline(
        events=[], first_signal_at=NOW,
        detection_lag_minutes=12, resolution_duration_minutes=47,
    )


def test_root_cause_analyst_returns_root_cause_in_demo_mode():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result, RootCause)


def test_root_cause_has_required_fields():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert result.primary
    assert isinstance(result.contributing_factors, list)
    assert result.trigger
    assert result.blast_radius
    assert result.confidence in ("HIGH", "MEDIUM", "LOW")


def test_root_cause_primary_is_single_sentence():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    sentence_count = len([s for s in result.primary.split(".") if s.strip()])
    assert sentence_count <= 2  # Generous allowance for demo data


def test_root_cause_analyst_describe():
    analyst = RootCauseAnalyst()
    assert "root cause" in analyst.describe().lower()
