"""PostMortemWriter — assembles the final PostMortem document.

Writes:
  - executive_summary: ≤3 sentences, non-technical, for a business audience
  - lessons_learned: distilled insights, not action items
  - Assembles all specialist outputs into the PostMortem model

draft is always True — humans review and approve before distribution.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime

from agents.base_agent import BaseAgent
from shared.models import ActionItem, Incident, PostMortem, RootCause, Timeline

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior SRE writing a post-mortem for a mixed technical and business audience.

Your job:
1. Executive summary (≤3 sentences, NO jargon): What happened, who was affected, what was done.
   Write for a VP who doesn't know what Redis or connection pools are.
2. Lessons learned: 2-5 distilled insights. Not action items — broader lessons.
   Example: "Systems that grow 3x in users without reviewing resource capacity bounds
   will fail at unpredictable times."

Rules:
- Executive summary: 3 sentences maximum. No technical acronyms.
- Lessons learned: insights, not "improve X" — those belong in action items."""


class PostMortemWriter(BaseAgent):
    """Assembles all specialist outputs into a final PostMortem."""

    def describe(self) -> str:
        return "Post-mortem writer: assembles executive summary, timeline, root cause, and action items"

    def run(
        self,
        incident: Incident,
        timeline: Timeline,
        root_cause: RootCause,
        action_items: list[ActionItem],
        similar_incidents: list[str],
        revision_brief: str | None = None,
        demo_mode: bool = False,
    ) -> PostMortem:
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"

        executive_summary = self._write_executive_summary(
            incident, root_cause, timeline, use_demo, revision_brief
        )
        lessons_learned = self._write_lessons(
            root_cause, action_items, use_demo, revision_brief
        )

        return PostMortem(
            incident=incident,
            executive_summary=executive_summary,
            timeline=timeline,
            root_cause=root_cause,
            action_items=action_items,
            lessons_learned=lessons_learned,
            similar_incidents=similar_incidents,
            draft=True,
            generated_at=datetime.now(tz=UTC),
        )

    def _write_executive_summary(
        self,
        incident: Incident,
        root_cause: RootCause,
        timeline: Timeline,
        demo_mode: bool,
        revision_brief: str | None,
    ) -> str:
        if demo_mode or self.backend is None:
            services = " and ".join(incident.affected_services[:2])
            duration = timeline.resolution_duration_minutes
            return (
                f"A {duration}-minute service disruption affected {services} on "
                f"{incident.started_at.strftime('%B %d, %Y')}. "
                f"The disruption was caused by {root_cause.trigger.lower()}, "
                f"which exposed an underlying capacity constraint. "
                f"The service was restored after the capacity limit was addressed."
            )

        revision_note = ""
        if revision_brief:
            revision_note = f"\n\nRevision feedback: {revision_brief}\nAddress the feedback above."

        prompt = (
            f"Incident: {incident.title} ({incident.id})\n"
            f"Duration: {timeline.resolution_duration_minutes} minutes\n"
            f"Affected: {', '.join(incident.affected_services)}\n"
            f"Root cause: {root_cause.primary}\n"
            f"Trigger: {root_cause.trigger}"
            f"{revision_note}\n\n"
            "Write the executive summary (≤3 sentences, no jargon):"
        )
        return self.backend.complete(  # type: ignore[union-attr]
            system=_SYSTEM_PROMPT,
            user=prompt,
            model=self.model,
            max_tokens=256,
        )

    def _write_lessons(
        self,
        root_cause: RootCause,
        action_items: list[ActionItem],
        demo_mode: bool,
        revision_brief: str | None,
    ) -> list[str]:
        if demo_mode or self.backend is None:
            return [
                "Connection pool capacity should be reviewed whenever user traffic "
                "grows by more than 50% — resource limits that are adequate today "
                "may be dangerously close to exhaustion within weeks.",
                "Automation that has not been tested recently should be treated as "
                "non-existent — a capacity review automation that silently fails "
                "provides false assurance.",
                "Detection lag often exceeds 10 minutes when monitoring focuses on "
                "service availability rather than leading indicators like resource utilisation.",
            ]

        prompt = (
            f"Root cause: {root_cause.primary}\n"
            f"Contributing factors: {root_cause.contributing_factors}\n"
            f"Action items: {[ai.title for ai in action_items]}\n\n"
            "Write 2-5 lessons learned (broader insights, not action items). "
            "Return as a JSON array of strings."
        )
        raw = self.backend.complete(  # type: ignore[union-attr]
            system=_SYSTEM_PROMPT,
            user=prompt,
            model=self.model,
            max_tokens=512,
        )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except Exception:
            return [cleaned]
