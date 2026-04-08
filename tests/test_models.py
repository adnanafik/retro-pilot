# tests/test_models.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.models import (
    ActionItem,
    EvaluationScore,
    Evidence,
    Incident,
    PostMortem,
    RootCause,
    Timeline,
    TimelineEvent,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_incident(**overrides) -> dict:
    base = {
        "id": "INC-2026-0001",
        "title": "Redis pool exhaustion in auth-service",
        "severity": "SEV1",
        "started_at": NOW,
        "resolved_at": datetime(2026, 1, 15, 14, 47, 0, tzinfo=UTC),
        "affected_services": ["auth-service", "payment-service"],
        "involved_repos": ["acme/auth-service"],
        "slack_channel": "#incident-2026-0001",
        "metrics_namespace": None,
        "reported_by": "oncall-engineer",
    }
    return {**base, **overrides}


def test_incident_valid():
    inc = Incident(**make_incident())
    assert inc.severity == "SEV1"
    assert inc.id == "INC-2026-0001"


def test_incident_invalid_severity():
    with pytest.raises(ValidationError):
        Incident(**make_incident(severity="SEV5"))


def test_evidence_gaps_default_empty():
    ev = Evidence(
        logs=[], metrics=[], git_events=[], slack_messages=[],
        collected_at=NOW,
    )
    assert ev.gaps == []


def test_timeline_event_significance_literal():
    with pytest.raises(ValidationError):
        TimelineEvent(
            timestamp=NOW, description="x", source="log", significance="extreme"
        )


def test_root_cause_confidence_literal():
    with pytest.raises(ValidationError):
        RootCause(
            primary="x", contributing_factors=[], trigger="y",
            blast_radius="low", confidence="VERY_HIGH", evidence_refs=[]
        )


def test_action_item_all_fields():
    ai = ActionItem(
        title="Add pool saturation alert",
        owner_role="Platform team",
        deadline_days=14,
        priority="P1",
        type="detection",
        acceptance_criteria="Alert fires when pool utilisation > 80% for 5 min",
    )
    assert ai.priority == "P1"


def test_postmortem_draft_default_true():
    inc = Incident(**make_incident())
    rc = RootCause(
        primary="Pool exhausted", contributing_factors=[], trigger="traffic spike",
        blast_radius="high", confidence="HIGH", evidence_refs=[]
    )
    tl = Timeline(
        events=[], first_signal_at=NOW, detection_lag_minutes=12,
        resolution_duration_minutes=47
    )
    pm = PostMortem(
        incident=inc,
        executive_summary="Short summary.",
        timeline=tl,
        root_cause=rc,
        action_items=[],
        lessons_learned=[],
        similar_incidents=[],
        generated_at=NOW,
    )
    assert pm.draft is True
    assert pm.revision_count == 0


def test_evaluation_score_pass_threshold():
    score = EvaluationScore(
        total=0.91,
        timeline_completeness=0.90,
        root_cause_clarity=0.95,
        action_item_quality=0.90,
        executive_summary_clarity=0.85,
        similar_incidents_referenced=0.90,
        passed=True,
        revision_brief=None,
        revision_number=1,
    )
    assert score.passed is True
    assert score.revision_brief is None


def test_evaluation_score_fail_has_brief():
    score = EvaluationScore(
        total=0.72,
        timeline_completeness=0.60,
        root_cause_clarity=0.70,
        action_item_quality=0.80,
        executive_summary_clarity=0.75,
        similar_incidents_referenced=0.70,
        passed=False,
        revision_brief="Timeline missing detection lag. Action item 2 has no acceptance_criteria.",
        revision_number=1,
    )
    assert score.passed is False
    assert score.revision_brief is not None


def test_evaluation_score_passed_with_brief_raises():
    with pytest.raises(ValidationError):
        EvaluationScore(
            total=0.91, timeline_completeness=0.90, root_cause_clarity=0.95,
            action_item_quality=0.90, executive_summary_clarity=0.85,
            similar_incidents_referenced=0.90,
            passed=True, revision_brief="This should not be here",
        )


def test_evaluation_score_failed_without_brief_raises():
    with pytest.raises(ValidationError):
        EvaluationScore(
            total=0.72, timeline_completeness=0.60, root_cause_clarity=0.70,
            action_item_quality=0.80, executive_summary_clarity=0.75,
            similar_incidents_referenced=0.70,
            passed=False, revision_brief=None,
        )
