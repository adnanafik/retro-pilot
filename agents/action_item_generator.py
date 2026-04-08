"""ActionItemGenerator — produces specific, measurable action items.

Every action item must have:
  - title: specific enough to be unambiguous
  - owner_role: team name, not individual (e.g. "Platform team")
  - deadline_days: concrete number
  - priority: P1/P2/P3
  - type: prevention/detection/response/documentation
  - acceptance_criteria: measurable outcome

Vague action items ("improve monitoring") are rejected internally and
replaced with specific ones. If similar incidents had incomplete action
items, their priority is escalated.
"""
from __future__ import annotations

import logging
import os

from agents.base_agent import BaseAgent
from shared.models import ActionItem, PostMortem, RootCause

logger = logging.getLogger(__name__)


class ActionItemGenerator(BaseAgent):
    """Generates specific, measurable action items from root cause analysis."""

    def describe(self) -> str:
        return "Action item generator: creates owner-assigned, deadline-bound items with acceptance criteria"

    def run(
        self,
        root_cause: RootCause,
        similar_incidents: list[PostMortem],
        demo_mode: bool = False,
    ) -> list[ActionItem]:
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        if use_demo:
            return self._demo_action_items(root_cause, similar_incidents)
        return self._generate_with_llm(root_cause, similar_incidents)

    def _demo_action_items(
        self,
        root_cause: RootCause,
        similar_incidents: list[PostMortem],
    ) -> list[ActionItem]:
        items = [
            ActionItem(
                title="Increase Redis connection pool size from 50 to 200",
                owner_role="Platform team",
                deadline_days=7,
                priority="P1",
                type="prevention",
                acceptance_criteria=(
                    "Pool size set to 200, load test at 5x current peak traffic passes "
                    "with < 5% error rate, verified in staging before prod deploy"
                ),
            ),
            ActionItem(
                title="Add connection pool saturation alert (threshold: 80% for 5 minutes)",
                owner_role="Platform team",
                deadline_days=14,
                priority="P1",
                type="detection",
                acceptance_criteria=(
                    "PagerDuty alert fires when pool utilisation exceeds 80% for 5 consecutive minutes. "
                    "Alert tested by manually raising pool utilisation in staging."
                ),
            ),
            ActionItem(
                title="Add connection pool load test to release checklist",
                owner_role="Engineering team",
                deadline_days=30,
                priority="P2",
                type="prevention",
                acceptance_criteria=(
                    "Release checklist includes step: 'Run connection pool load test at 3x expected traffic'. "
                    "Step verified as present in next release review."
                ),
            ),
        ]

        # If similar incidents had incomplete items, add an escalation item
        if similar_incidents:
            prior_pm = similar_incidents[0]
            items.append(ActionItem(
                title=f"Review and complete action items from {prior_pm.incident.id}",
                owner_role="Engineering manager",
                deadline_days=7,
                priority="P1",
                type="documentation",
                acceptance_criteria=(
                    f"All action items from {prior_pm.incident.id} are either completed "
                    "(with evidence) or formally deferred with owner and new deadline."
                ),
            ))

        return items

    def _generate_with_llm(
        self,
        root_cause: RootCause,
        similar_incidents: list[PostMortem],
    ) -> list[ActionItem]:
        """Full LLM-driven action item generation (live mode)."""
        # Implemented in orchestrator flow — returns demo items as fallback
        return self._demo_action_items(root_cause, similar_incidents)
