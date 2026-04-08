"""Rule-based scorer for retro-pilot post-mortems.

Scores each dimension 0.0 → 1.0 using heuristics defined in rubric.py.
The LLM-as-judge in evaluator_agent.py calls this scorer first, then uses
an LLM to generate the specific revision_brief.

Scoring is deterministic and does not require LLM calls — this makes the
rubric fully testable without API access.
"""
from __future__ import annotations

from evaluator.rubric import (
    EXECUTIVE_JARGON,
    MIN_KB_SIZE_FOR_SIMILAR,
    MIN_TIMELINE_EVENTS,
    PASS_THRESHOLD,
    WEIGHTS,
)
from shared.models import EvaluationScore, PostMortem


def _score_timeline(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0

    if len(pm.timeline.events) < MIN_TIMELINE_EVENTS:
        deficit = MIN_TIMELINE_EVENTS - len(pm.timeline.events)
        score -= 0.15 * deficit
        issues.append(
            f"Timeline has {len(pm.timeline.events)} events — minimum is {MIN_TIMELINE_EVENTS}."
        )

    if pm.timeline.detection_lag_minutes == 0:
        score -= 0.10
        issues.append("Timeline detection_lag_minutes is 0 — verify this is accurate.")

    sources_present = {e.source for e in pm.timeline.events}
    if not sources_present:
        score -= 0.10
        issues.append("Timeline events have no sources.")

    if not pm.timeline.first_signal_at:
        score -= 0.15
        issues.append("Timeline is missing first_signal_at.")

    return max(0.0, min(1.0, score)), issues


def _score_root_cause(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0
    rc = pm.root_cause

    # Primary should be one sentence (no period in the middle)
    sentence_count = len([s for s in rc.primary.split(".") if s.strip()])
    if sentence_count > 1:
        score -= 0.20
        issues.append(
            f"Root cause primary is {sentence_count} sentences — condense to one."
        )

    if not rc.contributing_factors:
        score -= 0.15
        issues.append("Root cause has no contributing factors.")

    if rc.trigger.lower() in ("unknown", "", "n/a"):
        score -= 0.15
        issues.append("Root cause trigger is vague — specify what changed.")

    if not rc.evidence_refs:
        score -= 0.20
        issues.append("Root cause has no evidence_refs — link to supporting evidence.")

    return max(0.0, min(1.0, score)), issues


def _score_action_items(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0

    if not pm.action_items:
        return 0.0, ["No action items present."]

    vague_titles = {
        "improve monitoring",
        "add monitoring",
        "investigate further",
        "fix the issue",
        "address the problem",
    }
    types_present = {ai.type for ai in pm.action_items}

    for i, ai in enumerate(pm.action_items, 1):
        if not ai.acceptance_criteria.strip():
            score -= 0.25
            issues.append(f"Action item {i} ('{ai.title}') has no acceptance_criteria.")
        if not ai.owner_role.strip():
            score -= 0.05
            issues.append(f"Action item {i} has no owner_role.")
        if ai.deadline_days <= 1:
            score -= 0.05
            issues.append(
                f"Action item {i} has a very short or no deadline "
                f"(deadline_days={ai.deadline_days})."
            )
        if ai.title.lower().strip() in vague_titles:
            score -= 0.10
            issues.append(
                f"Action item {i} title '{ai.title}' is too vague — be specific."
            )

    if len(types_present) < 2:
        score -= 0.10
        issues.append(
            f"Action items only cover type(s) {types_present} — include prevention, "
            "detection, or response types for balance."
        )

    return max(0.0, min(1.0, score)), issues


def _score_executive_summary(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0
    summary = pm.executive_summary

    sentence_count = len([s for s in summary.split(".") if s.strip()])
    if sentence_count > 3:
        score -= 0.20
        issues.append(
            f"Executive summary is {sentence_count} sentences — maximum is 3."
        )

    jargon_found = [j for j in EXECUTIVE_JARGON if j.lower() in summary.lower()]
    if jargon_found:
        score -= min(0.30, 0.10 * len(jargon_found))
        issues.append(
            f"Executive summary contains technical jargon: {', '.join(jargon_found)}. "
            "Rewrite for a non-technical executive."
        )

    if len(summary) < 50:
        score -= 0.20
        issues.append("Executive summary is too short to be meaningful.")

    return max(0.0, min(1.0, score)), issues


def _score_similar_incidents(
    pm: PostMortem, knowledge_base_size: int
) -> tuple[float, list[str]]:
    if knowledge_base_size < MIN_KB_SIZE_FOR_SIMILAR:
        return 1.0, []  # Not enough KB entries to require references

    if not pm.similar_incidents:
        return 0.40, [
            f"Knowledge base has {knowledge_base_size} incidents but none are referenced. "
            "Search the knowledge base for similar incidents."
        ]

    return 1.0, []


def score_postmortem(
    pm: PostMortem,
    knowledge_base_size: int = 0,
    revision_number: int = 0,
) -> EvaluationScore:
    """Score a PostMortem against the rubric. Deterministic, no LLM calls.

    Args:
        pm: The post-mortem to score.
        knowledge_base_size: Number of past post-mortems in the vector store.
        revision_number: Which revision this is (0 = first draft).

    Returns:
        EvaluationScore with per-dimension scores, total, pass/fail, and
        a specific revision_brief if failed.
    """
    tl_score, tl_issues = _score_timeline(pm)
    rc_score, rc_issues = _score_root_cause(pm)
    ai_score, ai_issues = _score_action_items(pm)
    es_score, es_issues = _score_executive_summary(pm)
    si_score, si_issues = _score_similar_incidents(pm, knowledge_base_size)

    total = (
        tl_score * WEIGHTS["timeline_completeness"]
        + rc_score * WEIGHTS["root_cause_clarity"]
        + ai_score * WEIGHTS["action_item_quality"]
        + es_score * WEIGHTS["executive_summary_clarity"]
        + si_score * WEIGHTS["similar_incidents_referenced"]
    )

    passed = total >= PASS_THRESHOLD

    revision_brief: str | None = None
    if not passed:
        all_issues = tl_issues + rc_issues + ai_issues + es_issues + si_issues
        revision_brief = " ".join(all_issues) if all_issues else (
            "Post-mortem quality below threshold. Review all dimensions."
        )

    return EvaluationScore(
        total=round(total, 3),
        timeline_completeness=round(tl_score, 3),
        root_cause_clarity=round(rc_score, 3),
        action_item_quality=round(ai_score, 3),
        executive_summary_clarity=round(es_score, 3),
        similar_incidents_referenced=round(si_score, 3),
        passed=passed,
        revision_brief=revision_brief,
        revision_number=revision_number,
    )
