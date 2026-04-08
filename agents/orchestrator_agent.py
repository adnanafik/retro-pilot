"""OrchestratorAgent — top-level coordinator for retro-pilot.

Orchestration sequence:
  Incident + similar_incidents (ChromaDB)
    → EvidenceCollector (parallel workers)
    → TimelineBuilder
    → RootCauseAnalyst
    → ActionItemGenerator
    → PostMortemWriter
    → EvaluatorAgent → [pass] store + notify
                     → [fail, < max_cycles] revise → re-evaluate
                     → [fail, max_cycles] save as draft, flag for human review

The revision loop has a hard cap (default 3 cycles) to prevent unbounded LLM calls.
After max_cycles, the best draft is returned with draft=True.
"""
from __future__ import annotations

import logging
import os

from agents.action_item_generator import ActionItemGenerator
from agents.base_agent import BaseAgent
from agents.evaluator_agent import EvaluatorAgent
from agents.evidence_collector import EvidenceCollector
from agents.postmortem_writer import PostMortemWriter
from agents.root_cause_analyst import RootCauseAnalyst
from agents.timeline_builder import TimelineBuilder
from knowledge.vector_store import VectorStore
from shared.models import Incident, PostMortem

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Coordinates the full post-mortem pipeline with revision loop."""

    def __init__(
        self,
        backend=None,
        model: str | None = None,
        demo_mode: bool = False,
        max_revision_cycles: int = 3,
        vector_store_path: str = "./chroma_db",
    ) -> None:
        super().__init__(backend=backend, model=model)
        self._demo_mode = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        self._max_revision_cycles = max_revision_cycles
        self._vector_store = VectorStore(path=vector_store_path)

        # Agents — backend injected for live mode, None for demo
        _b = None if self._demo_mode else backend
        self._evidence_collector = EvidenceCollector(backend=_b, model=model)
        self._timeline_builder = TimelineBuilder(backend=_b, model=model)
        self._root_cause_analyst = RootCauseAnalyst(backend=_b, model=model)
        self._action_item_generator = ActionItemGenerator(backend=_b, model=model)
        self._postmortem_writer = PostMortemWriter(backend=_b, model=model)
        self._evaluator = EvaluatorAgent(backend=_b, model=model)

    def describe(self) -> str:
        return "Orchestrator: coordinates full post-mortem pipeline with up to 3 revision cycles"

    def run(self, incident: Incident) -> PostMortem:
        """Run the full pipeline for an incident.

        Args:
            incident: The resolved Incident to post-mortem.

        Returns:
            PostMortem with draft=True (always; human approves to publish).
        """
        logger.info("OrchestratorAgent: starting post-mortem for %s", incident.id)

        # Retrieve similar past incidents
        query = f"{incident.title} {' '.join(incident.affected_services)}"
        similar_incidents = self._vector_store.retrieve(query)
        similar_ids = [pm.incident.id for pm in similar_incidents]
        kb_size = self._vector_store.count()

        logger.info(
            "OrchestratorAgent: found %d similar incidents in KB (%d total)",
            len(similar_incidents), kb_size,
        )

        # Phase 1: Collect evidence
        evidence = self._evidence_collector.run(incident, demo_mode=self._demo_mode)
        logger.info("OrchestratorAgent: evidence collected, gaps=%s", evidence.gaps)

        # Phase 2: Build timeline
        timeline = self._timeline_builder.run(
            evidence,
            incident_started_at=incident.started_at,
            incident_resolved_at=incident.resolved_at,
            demo_mode=self._demo_mode,
        )
        logger.info(
            "OrchestratorAgent: timeline built, %d events, detection_lag=%dmin",
            len(timeline.events), timeline.detection_lag_minutes,
        )

        # Phase 3: Root cause
        root_cause = self._root_cause_analyst.run(
            evidence=evidence,
            timeline=timeline,
            similar_incidents=similar_incidents,
            demo_mode=self._demo_mode,
        )
        logger.info("OrchestratorAgent: root cause — %s", root_cause.primary)

        # Phase 4: Action items
        action_items = self._action_item_generator.run(
            root_cause=root_cause,
            similar_incidents=similar_incidents,
            demo_mode=self._demo_mode,
        )
        logger.info("OrchestratorAgent: %d action items generated", len(action_items))

        # Phase 5: Initial draft
        postmortem = self._postmortem_writer.run(
            incident=incident,
            timeline=timeline,
            root_cause=root_cause,
            action_items=action_items,
            similar_incidents=similar_ids,
            demo_mode=self._demo_mode,
        )

        # Phase 6: Evaluate + revision loop
        best: PostMortem = postmortem
        for cycle in range(self._max_revision_cycles + 1):
            score = self._evaluator.run(
                postmortem=best,
                knowledge_base_size=kb_size,
                revision_number=cycle,
            )
            logger.info(
                "OrchestratorAgent: evaluation cycle %d — score=%.3f, passed=%s",
                cycle, score.total, score.passed,
            )

            if score.passed:
                logger.info("OrchestratorAgent: PASSED — storing to knowledge base")
                self._vector_store.store(best)
                return best

            if cycle >= self._max_revision_cycles:
                logger.warning(
                    "OrchestratorAgent: max revisions (%d) reached — "
                    "returning best draft for human review",
                    self._max_revision_cycles,
                )
                return best

            # Revise
            logger.info(
                "OrchestratorAgent: revision %d requested — brief: %s",
                cycle + 1, score.revision_brief,
            )
            best = self._postmortem_writer.run(
                incident=incident,
                timeline=timeline,
                root_cause=root_cause,
                action_items=action_items,
                similar_incidents=similar_ids,
                revision_brief=score.revision_brief,
                demo_mode=self._demo_mode,
            )
            best = best.model_copy(update={"revision_count": cycle + 1})

        return best
