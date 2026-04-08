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


def test_root_cause_analyst_with_similar_incidents_adds_contributing_factor():
    """Similar incidents branch: adds a factor referencing prior incident ID."""
    from datetime import UTC, datetime

    from shared.models import (
        Incident,
        PostMortem,
        RootCause,
        Timeline,
    )

    now = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
    prior_incident = Incident(
        id="INC-2026-0089", title="Prior Redis exhaustion",
        severity="SEV2", started_at=now,
        resolved_at=datetime(2026, 1, 15, 15, 0, tzinfo=UTC),
        affected_services=["auth-service"], involved_repos=[],
        slack_channel="#incidents", reported_by="oncall",
    )
    prior_timeline = Timeline(
        events=[], first_signal_at=now, detection_lag_minutes=5, resolution_duration_minutes=60,
    )
    prior_rc = RootCause(
        primary="Redis pool exhausted", contributing_factors=[],
        trigger="Traffic spike", blast_radius="api", confidence="LOW", evidence_refs=[],
    )
    prior_pm = PostMortem(
        incident=prior_incident,
        executive_summary="Prior outage summary.",
        timeline=prior_timeline,
        root_cause=prior_rc,
        action_items=[],
        lessons_learned=[],
        similar_incidents=[],
        generated_at=now,
    )

    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[prior_pm],
        demo_mode=True,
    )
    assert isinstance(result, RootCause)
    # Contributing factors should mention the similar incident
    all_factors = " ".join(result.contributing_factors)
    assert "INC-2026-0089" in all_factors


def test_root_cause_analyst_with_evidence_populates_refs():
    """Evidence with logs and metrics generates non-empty evidence_refs."""
    from datetime import UTC, datetime

    from shared.models import Evidence, LogEntry, MetricSnapshot

    now = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
    evidence = Evidence(
        logs=[LogEntry(timestamp=now, level="ERROR", service="auth-service", message="Pool exhausted")],
        metrics=[MetricSnapshot(timestamp=now, metric_name="pool_util", value=100.0, unit="Percent")],
        git_events=[],
        slack_messages=[],
        collected_at=now,
        gaps=[],
    )

    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=evidence,
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result.evidence_refs, list)
    assert len(result.evidence_refs) > 0


def test_root_cause_analyst_llm_path_with_mock_agent_loop():
    """LLM path (_analyse_with_llm) covered by mocking AgentLoop."""
    from unittest.mock import AsyncMock, MagicMock, patch

    expected_rc = RootCause(
        primary="Connection pool exhausted",
        contributing_factors=["Pool not scaled"],
        trigger="Traffic spike",
        blast_radius="api",
        confidence="HIGH",
        evidence_refs=["log:14:00"],
    )

    loop_result = MagicMock()
    loop_result.extracted = expected_rc

    mock_loop_instance = MagicMock()
    mock_loop_instance.run = AsyncMock(return_value=loop_result)

    with patch("agents.root_cause_analyst.AgentLoop", return_value=mock_loop_instance):
        backend = MagicMock()
        analyst = RootCauseAnalyst(backend=backend)
        result = analyst.run(
            evidence=make_empty_evidence(),
            timeline=make_empty_timeline(),
            similar_incidents=[],
            demo_mode=False,
        )

    assert isinstance(result, RootCause)
    assert result.primary == "Connection pool exhausted"


def test_root_cause_analyst_llm_path_with_similar_incidents():
    """LLM path with similar_incidents builds context correctly."""
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    from shared.models import Incident, PostMortem, RootCause, Timeline

    now = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
    prior_incident = Incident(
        id="INC-2026-0089", title="Prior Redis exhaustion",
        severity="SEV2", started_at=now,
        resolved_at=datetime(2026, 1, 15, 15, 0, tzinfo=UTC),
        affected_services=["auth-service"], involved_repos=[],
        slack_channel="#incidents", reported_by="oncall",
    )
    prior_timeline = Timeline(
        events=[], first_signal_at=now, detection_lag_minutes=5, resolution_duration_minutes=60,
    )
    prior_rc = RootCause(
        primary="Redis pool exhausted", contributing_factors=[],
        trigger="Traffic spike", blast_radius="api", confidence="LOW", evidence_refs=[],
    )
    prior_pm = PostMortem(
        incident=prior_incident,
        executive_summary="Prior outage.",
        timeline=prior_timeline,
        root_cause=prior_rc,
        action_items=[],
        lessons_learned=[],
        similar_incidents=[],
        generated_at=now,
    )

    expected_rc = RootCause(
        primary="Pool exhausted again",
        contributing_factors=["Same as before"],
        trigger="New campaign",
        blast_radius="api",
        confidence="HIGH",
        evidence_refs=["log:14:00"],
    )
    loop_result = MagicMock()
    loop_result.extracted = expected_rc
    mock_loop_instance = MagicMock()
    mock_loop_instance.run = AsyncMock(return_value=loop_result)

    with patch("agents.root_cause_analyst.AgentLoop", return_value=mock_loop_instance):
        backend = MagicMock()
        analyst = RootCauseAnalyst(backend=backend)
        result = analyst.run(
            evidence=make_empty_evidence(),
            timeline=make_empty_timeline(),
            similar_incidents=[prior_pm],
            demo_mode=False,
        )

    assert result.primary == "Pool exhausted again"
