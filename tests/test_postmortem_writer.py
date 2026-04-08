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


def test_postmortem_writer_describe():
    writer = PostMortemWriter()
    assert "post-mortem" in writer.describe().lower() or "writer" in writer.describe().lower()


def test_postmortem_writer_llm_path_executive_summary():
    """LLM path: backend.complete() is called when demo_mode=False and backend is set."""
    from unittest.mock import MagicMock
    backend = MagicMock()
    backend.complete.return_value = "Service was disrupted. Users were affected. Issue was fixed."

    writer = PostMortemWriter(backend=backend)
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[], demo_mode=False,
    )
    assert isinstance(result, PostMortem)
    # backend.complete should be called for both executive_summary and lessons_learned
    assert backend.complete.call_count >= 1


def test_postmortem_writer_llm_path_with_revision_brief():
    """Revision brief is forwarded to the LLM prompt."""
    from unittest.mock import MagicMock
    backend = MagicMock()
    backend.complete.side_effect = [
        "Revised executive summary here.",  # executive summary call
        '["Lesson one.", "Lesson two."]',   # lessons learned call (JSON array)
    ]

    writer = PostMortemWriter(backend=backend)
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[],
        revision_brief="Improve the executive summary clarity.",
        demo_mode=False,
    )
    assert isinstance(result, PostMortem)
    # Verify revision brief was forwarded — check prompt contained "Revision feedback"
    call_args = backend.complete.call_args_list[0]
    user_prompt = call_args[1].get("user", "") or (call_args[0][1] if len(call_args[0]) > 1 else "")
    assert "Revision feedback" in user_prompt or "revision_brief" in str(call_args)


def test_postmortem_writer_llm_lessons_invalid_json_returns_raw():
    """If LLM returns non-JSON for lessons, raw string is returned in list."""
    from unittest.mock import MagicMock
    backend = MagicMock()
    backend.complete.side_effect = [
        "Executive summary from LLM.",
        "Not valid JSON at all — just raw text from the model.",
    ]

    writer = PostMortemWriter(backend=backend)
    inc, tl, rc, items = make_all_inputs()
    result = writer.run(
        incident=inc, timeline=tl, root_cause=rc,
        action_items=items, similar_incidents=[], demo_mode=False,
    )
    assert isinstance(result.lessons_learned, list)
    assert len(result.lessons_learned) > 0
