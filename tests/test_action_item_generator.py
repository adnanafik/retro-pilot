# tests/test_action_item_generator.py
from datetime import UTC, datetime

from agents.action_item_generator import ActionItemGenerator
from shared.models import ActionItem, RootCause

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_root_cause() -> RootCause:
    return RootCause(
        primary="Connection pool exhausted in auth-service",
        contributing_factors=["Pool size not scaled after growth"],
        trigger="Traffic spike from marketing campaign",
        blast_radius="payment-service, session-service",
        confidence="HIGH",
        evidence_refs=["log:auth:14:00"],
    )


def test_action_item_generator_returns_list_of_action_items():
    gen = ActionItemGenerator()
    result = gen.run(
        root_cause=make_root_cause(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result, list)
    assert all(isinstance(ai, ActionItem) for ai in result)


def test_action_items_all_have_acceptance_criteria():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.acceptance_criteria.strip(), \
            f"Action item '{ai.title}' has no acceptance_criteria"


def test_action_items_all_have_owner_role():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.owner_role.strip(), \
            f"Action item '{ai.title}' has no owner_role"


def test_action_items_all_have_deadline():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.deadline_days > 0, \
            f"Action item '{ai.title}' has deadline_days=0"


def test_action_items_cover_multiple_types():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    types_present = {ai.type for ai in result}
    assert len(types_present) >= 2, \
        f"Only one action item type present: {types_present}"


def test_action_item_generator_describe():
    gen = ActionItemGenerator()
    assert "action" in gen.describe().lower()


def test_action_item_generator_adds_escalation_for_similar_incidents():
    """When similar incidents exist, a review item is added (similar_incidents branch)."""
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

    gen = ActionItemGenerator()
    result = gen.run(
        root_cause=make_root_cause(),
        similar_incidents=[prior_pm],
        demo_mode=True,
    )
    titles = [ai.title for ai in result]
    assert any("INC-2026-0089" in t for t in titles), \
        "Expected escalation action item referencing prior incident"


def test_action_item_generator_llm_path_falls_back_to_demo():
    """LLM path (_generate_with_llm) calls _demo_action_items as fallback."""
    gen = ActionItemGenerator()
    # No backend set — LLM path returns demo items
    result = gen.run(root_cause=make_root_cause(), similar_incidents=[], demo_mode=False)
    assert isinstance(result, list)
    assert len(result) > 0
