# tests/test_evaluator.py
from datetime import UTC, datetime

from evaluator.rubric import PASS_THRESHOLD, WEIGHTS
from evaluator.scorer import score_postmortem
from shared.models import (
    ActionItem,
    Incident,
    PostMortem,
    RootCause,
    Timeline,
    TimelineEvent,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_strong_postmortem() -> PostMortem:
    """A post-mortem that should score >= 0.80."""
    inc = Incident(
        id="INC-2026-0001", title="Redis pool exhaustion",
        severity="SEV1", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=UTC),
        affected_services=["auth-service", "payment-service"],
        involved_repos=["acme/auth"], slack_channel="#incidents", reported_by="oncall",
    )
    events = [
        TimelineEvent(timestamp=NOW, description=f"Event {i}",
                      source="log", significance="medium")
        for i in range(6)
    ]
    tl = Timeline(
        events=events, first_signal_at=NOW,
        detection_lag_minutes=12, resolution_duration_minutes=47,
    )
    rc = RootCause(
        primary="Connection pool exhausted in auth-service",
        contributing_factors=["Pool size not scaled after 3x traffic growth"],
        trigger="Marketing campaign launched at 14:00 increased login rate 4x",
        blast_radius="payment-service, session-service",
        confidence="HIGH",
        evidence_refs=["log:auth:14:00", "metric:pool_util:14:05"],
    )
    action_items = [
        ActionItem(
            title="Increase connection pool size to 200",
            owner_role="Platform team",
            deadline_days=7,
            priority="P1",
            type="prevention",
            acceptance_criteria="Pool size >= 200, load test passes at 5x current traffic",
        ),
        ActionItem(
            title="Add pool saturation alert",
            owner_role="Platform team",
            deadline_days=14,
            priority="P1",
            type="detection",
            acceptance_criteria="Alert fires when pool utilisation > 80% for 5 minutes",
        ),
        ActionItem(
            title="Add load test to release checklist",
            owner_role="Engineering team",
            deadline_days=30,
            priority="P2",
            type="prevention",
            acceptance_criteria="Release checklist includes load test step, verified in next release",
        ),
    ]
    return PostMortem(
        incident=inc,
        executive_summary=(
            "Auth service experienced a 47-minute outage due to connection pool exhaustion. "
            "Payment and session services were affected. "
            "Pool capacity has been increased and monitoring added."
        ),
        timeline=tl,
        root_cause=rc,
        action_items=action_items,
        lessons_learned=["Scale connection pools proactively after traffic growth"],
        similar_incidents=["INC-2026-0089"],
        generated_at=NOW,
    )


def make_weak_postmortem() -> PostMortem:
    """A post-mortem that should score < 0.80."""
    inc = Incident(
        id="INC-2026-0002", title="Outage",
        severity="SEV2", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        affected_services=["api"], involved_repos=[],
        slack_channel="#alerts", reported_by="oncall",
    )
    tl = Timeline(
        events=[  # Only 2 events — below the 5 minimum
            TimelineEvent(timestamp=NOW, description="Outage started",
                          source="log", significance="critical"),
            TimelineEvent(timestamp=NOW, description="Outage resolved",
                          source="log", significance="critical"),
        ],
        first_signal_at=NOW, detection_lag_minutes=5, resolution_duration_minutes=30,
    )
    rc = RootCause(
        primary="Something went wrong with the database and the API crashed causing problems",
        contributing_factors=[],  # No contributing factors
        trigger="unknown",
        blast_radius="api",
        confidence="LOW",
        evidence_refs=[],  # No evidence refs
    )
    action_items = [
        ActionItem(
            title="Improve monitoring",  # Vague
            owner_role="",  # No owner
            deadline_days=1,  # minimum valid (ge=1)
            priority="P3",
            type="detection",
            acceptance_criteria="",  # No acceptance criteria
        ),
    ]
    return PostMortem(
        incident=inc,
        executive_summary=(
            "There was an API outage that impacted customers. "
            "The root cause was a database issue. "
            "We are investigating this further and will implement fixes. "
            "This is the fourth sentence which exceeds the 3-sentence limit and adds jargon like RCA and MTTR."
        ),
        timeline=tl,
        root_cause=rc,
        action_items=action_items,
        lessons_learned=[],
        similar_incidents=[],
        generated_at=NOW,
    )


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001


def test_pass_threshold_is_0_80():
    assert PASS_THRESHOLD == 0.80


def test_strong_postmortem_passes():
    score = score_postmortem(make_strong_postmortem(), knowledge_base_size=10)
    assert score.passed is True
    assert score.total >= 0.80
    assert score.revision_brief is None


def test_weak_postmortem_fails():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.passed is False
    assert score.total < 0.80
    assert score.revision_brief is not None
    assert len(score.revision_brief) > 0


def test_weak_postmortem_has_low_timeline_score():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.timeline_completeness < 0.80


def test_weak_postmortem_has_low_action_item_score():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.action_item_quality < 0.50


def test_revision_brief_mentions_specific_issues():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    # Brief should mention specific problems, not generic feedback
    assert score.revision_brief is not None
    brief_lower = score.revision_brief.lower()
    # At least one specific issue should be called out
    assert any(kw in brief_lower for kw in [
        "timeline", "action item", "root cause", "executive summary",
        "evidence", "acceptance criteria", "owner"
    ])


def test_similar_incidents_dimension_scores_well_when_referenced():
    pm = make_strong_postmortem()
    pm.similar_incidents = ["INC-2026-0089"]
    score = score_postmortem(pm, knowledge_base_size=10)
    assert score.similar_incidents_referenced >= 0.80


def test_similar_incidents_dimension_penalised_when_empty_large_kb():
    pm = make_strong_postmortem()
    pm.similar_incidents = []
    score = score_postmortem(pm, knowledge_base_size=10)
    assert score.similar_incidents_referenced < 0.80


def test_similar_incidents_not_penalised_when_kb_small():
    pm = make_strong_postmortem()
    pm.similar_incidents = []
    score = score_postmortem(pm, knowledge_base_size=3)
    assert score.similar_incidents_referenced == 1.0
    assert score.passed is True


# ── EvaluatorAgent tests ───────────────────────────────────────────────────────
from unittest.mock import MagicMock

from agents.evaluator_agent import EvaluatorAgent


def make_mock_backend_for_evaluator(revision_brief_response: str) -> MagicMock:
    backend = MagicMock()
    backend.complete.return_value = revision_brief_response
    return backend


def test_evaluator_agent_passes_strong_postmortem():
    backend = make_mock_backend_for_evaluator("No revision needed.")
    agent = EvaluatorAgent(backend=backend)
    score = agent.run(make_strong_postmortem(), knowledge_base_size=10)
    assert score.passed is True
    # LLM should not be called for passing post-mortems
    backend.complete.assert_not_called()


def test_evaluator_agent_calls_llm_for_revision_brief_on_fail():
    backend = make_mock_backend_for_evaluator(
        "Root cause primary is two sentences. Timeline missing detection lag."
    )
    agent = EvaluatorAgent(backend=backend)
    score = agent.run(make_weak_postmortem(), knowledge_base_size=10)
    assert score.passed is False
    # LLM enriches the revision brief generated by the scorer
    backend.complete.assert_called_once()
    assert score.revision_brief is not None


def test_evaluator_agent_describe():
    agent = EvaluatorAgent()
    assert "LLM-as-judge" in agent.describe() or "evaluator" in agent.describe().lower()
