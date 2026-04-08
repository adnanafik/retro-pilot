"""EvaluatorAgent — LLM-as-judge for retro-pilot post-mortems.

Two-step evaluation:
1. Rule-based scorer (evaluator/scorer.py) produces a structural score and
   a list of specific issues. This is deterministic and requires no LLM.
2. If the draft fails, the LLM enriches the revision_brief — making it more
   actionable and specific to the post-mortem content.

If the draft passes (total >= 0.80), no LLM call is made.
"""
from __future__ import annotations

import logging

from agents.base_agent import BaseAgent
from evaluator.scorer import score_postmortem
from shared.models import EvaluationScore, PostMortem

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior incident post-mortem reviewer.
Your role is to improve the revision brief for a post-mortem that did not meet quality standards.
The structural scorer has identified specific issues. Your job is to:
1. Confirm or refine the identified issues based on the actual post-mortem content.
2. Add any additional specific issues the structural check missed.
3. Be specific: quote the problematic text, not just the section name.
4. Be actionable: tell the author exactly what to change, not just that it's wrong.
5. Be concise: the revision brief is 2-4 sentences, not a paragraph.
Do not mention scores or thresholds — focus on content quality."""


class EvaluatorAgent(BaseAgent):
    """Scores a PostMortem draft using the rubric + LLM enrichment.

    Pass: score >= 0.80 → returns EvaluationScore with passed=True, no LLM call.
    Fail: score < 0.80 → calls LLM to enrich revision_brief with specific feedback.
    """

    def describe(self) -> str:
        return "LLM-as-judge: scores post-mortem drafts against the rubric, returns revision_brief if below threshold"

    def run(
        self,
        postmortem: PostMortem,
        knowledge_base_size: int = 0,
        revision_number: int = 0,
    ) -> EvaluationScore:
        """Score the post-mortem. Enriches revision_brief via LLM if it fails.

        Args:
            postmortem: The draft PostMortem to evaluate.
            knowledge_base_size: Number of past post-mortems in the vector store.
            revision_number: Which revision cycle this is.

        Returns:
            EvaluationScore with passed=True/False and revision_brief if failed.
        """
        score = score_postmortem(
            postmortem,
            knowledge_base_size=knowledge_base_size,
            revision_number=revision_number,
        )

        if score.passed:
            logger.info(
                "EvaluatorAgent: PASSED %s (score=%.3f, revision=%d)",
                postmortem.incident.id, score.total, revision_number,
            )
            return score

        logger.info(
            "EvaluatorAgent: FAILED %s (score=%.3f, revision=%d) — enriching brief",
            postmortem.incident.id, score.total, revision_number,
        )

        # Enrich revision brief with LLM — make it specific to the actual content
        if self.backend is not None:
            enriched = self._enrich_revision_brief(postmortem, score)
            score = score.model_copy(update={"revision_brief": enriched})

        return score

    def _enrich_revision_brief(
        self, pm: PostMortem, score: EvaluationScore
    ) -> str:
        prompt = f"""Post-mortem for {pm.incident.id} — {pm.incident.title}

Executive summary: {pm.executive_summary}

Root cause primary: {pm.root_cause.primary}
Contributing factors: {pm.root_cause.contributing_factors}
Evidence refs: {pm.root_cause.evidence_refs}

Timeline events: {len(pm.timeline.events)} events
Detection lag: {pm.timeline.detection_lag_minutes} minutes

Action items: {[ai.title for ai in pm.action_items]}
Action item acceptance criteria: {[ai.acceptance_criteria for ai in pm.action_items]}

Similar incidents referenced: {pm.similar_incidents}

Structural issues found:
{score.revision_brief}

Write a specific, actionable revision brief (2-4 sentences) for the author."""

        return self.backend.complete(  # type: ignore[union-attr]
            system=_SYSTEM_PROMPT,
            user=prompt,
            model=self.model,
            max_tokens=512,
        )
