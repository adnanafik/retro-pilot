# tests/test_postmortem_writer.py
from datetime import UTC, datetime

from agents.postmortem_writer import PostMortemWriter
from shared.models import (
    ActionItem,
    Incident,
    PostMortem,
    RootCause,
    Timeline,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def make_all_inputs():
    inc = Incident(
        id="INC-2026-0001", title="Redis pool exhaustion",
        severity="SEV1", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=UTC),
        affected_services=["auth-service"], involved_repos=["acme/auth"],
        slack_channel="#incidents", reported_by="oncall",
    )
    tl = Timeline(
        events=[], first_signal_at=NOW,
        detection_lag_minutes=12, resolution_duration_minutes=47,
    )
    rc = RootCause(
        primary="Connection pool exhausted",
        contributing_factors=["Pool not scaled"],
        trigger="Traffic spike", blast_radius="payment-service",
        confidence="HIGH", evidence_refs=["log:14:00"],
    )
    action_items = [
        ActionItem(
            title="Increase pool size",
            owner_role="Platform team",
            deadline_days=7,
            priority="P1",
            type="prevention",
            acceptance_criteria="Pool size >= 200",
        )
    ]
    return inc, tl, rc, action_items


def test_postmortem_writer_returns_postmortem():
    writer = PostMortemWriter()
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result, PostMortem)


def test_postmortem_draft_is_always_true():
    writer = PostMortemWriter()
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[], demo_mode=True,
    )
    assert result.draft is True


def test_postmortem_executive_summary_max_3_sentences():
    writer = PostMortemWriter()
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[], demo_mode=True,
    )
    sentence_count = len([s for s in result.executive_summary.split(".") if s.strip()])
    assert sentence_count <= 3


def test_postmortem_has_lessons_learned():
    writer = PostMortemWriter()
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[], demo_mode=True,
    )
    assert isinstance(result.lessons_learned, list)
    assert len(result.lessons_learned) > 0
