# tests/test_orchestrator.py
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from agents.orchestrator_agent import OrchestratorAgent
from shared.models import EvaluationScore, Incident, PostMortem

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_incident() -> Incident:
    return Incident(
        id="INC-2026-0001",
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=UTC),
        affected_services=["auth-service"],
        involved_repos=["acme/auth"],
        slack_channel="#incidents",
        reported_by="oncall",
    )


def make_passing_score(revision_number: int = 0) -> EvaluationScore:
    return EvaluationScore(
        total=0.91, timeline_completeness=0.90, root_cause_clarity=0.95,
        action_item_quality=0.90, executive_summary_clarity=0.85,
        similar_incidents_referenced=0.90, passed=True,
        revision_brief=None, revision_number=revision_number,
    )


def make_failing_score(revision_number: int = 0) -> EvaluationScore:
    return EvaluationScore(
        total=0.72, timeline_completeness=0.60, root_cause_clarity=0.70,
        action_item_quality=0.80, executive_summary_clarity=0.75,
        similar_incidents_referenced=0.70, passed=False,
        revision_brief="Timeline has only 2 events. Action item 1 missing acceptance_criteria.",
        revision_number=revision_number,
    )


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_returns_postmortem_on_first_pass(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    assert result.draft is True
    assert result.revision_count == 0
    mock_evaluator.run.assert_called_once()


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_revises_on_fail_then_passes(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.side_effect = [
        make_failing_score(revision_number=0),  # First attempt fails
        make_passing_score(revision_number=1),  # Revision passes
    ]

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    assert mock_evaluator.run.call_count == 2
    assert result.revision_count == 1


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_stops_at_max_3_revisions(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    # Always fail
    mock_evaluator.run.return_value = make_failing_score()

    orchestrator = OrchestratorAgent(demo_mode=True, max_revision_cycles=3)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    # Should be called at most max_revision_cycles + 1 times
    assert mock_evaluator.run.call_count <= 4
    assert result.draft is True  # Still draft — never passed


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_stores_passing_postmortem(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    orchestrator.run(make_incident())

    mock_vs.store.assert_called_once()


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_handles_empty_kb(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs.count.return_value = 0
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())
    assert isinstance(result, PostMortem)


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_revision_count_increments(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.side_effect = [
        make_failing_score(0),
        make_failing_score(1),
        make_passing_score(2),
    ]

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())
    assert result.revision_count == 2
