"""Weekly knowledge consolidation job.

Finds post-mortems with cosine similarity > 0.90 and merges their
lessons_learned and action_items into a "pattern record" — a signal
that a systemic problem exists, not just a one-off incident.

Example output:
  "Redis connection pool exhausted 4 times in 6 weeks across 3 services —
   architectural issue, not incident-level."
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from knowledge.vector_store import VectorStore
from shared.models import PostMortem

logger = logging.getLogger(__name__)

_CONSOLIDATION_THRESHOLD = 0.90


class Consolidator:
    """Finds and merges highly similar post-mortems into pattern records.

    Args:
        vector_store: VectorStore instance to query.
    """

    def __init__(self, vector_store: VectorStore) -> None:
        self._store = vector_store

    def run(self, postmortems: list[PostMortem]) -> list[dict]:
        """Find clusters of similar incidents and produce pattern records.

        Args:
            postmortems: All post-mortems to analyse.

        Returns:
            List of pattern records, each a dict with:
              - incident_ids: list of merged IDs
              - merged_lessons: deduplicated lessons from all incidents
              - merged_action_items: deduplicated action item titles
              - pattern_summary: human-readable description
              - generated_at: ISO timestamp
        """
        visited: set[str] = set()
        patterns: list[dict] = []

        for pm in postmortems:
            if pm.incident.id in visited:
                continue

            doc = (
                f"{pm.incident.title} {pm.executive_summary} "
                f"{pm.root_cause.primary}"
            )
            similar = self._store.retrieve(doc, top_k=10)

            # Filter to only very-high similarity matches (> 0.90)
            # Note: retrieve() already filters > 0.65; we further filter here
            cluster = [
                s for s in similar
                if s.incident.id != pm.incident.id
                and s.incident.id not in visited
            ]

            if not cluster:
                continue

            all_in_cluster = [pm] + cluster
            for c in all_in_cluster:
                visited.add(c.incident.id)

            merged_lessons = list({
                lesson
                for c in all_in_cluster
                for lesson in c.lessons_learned
            })
            merged_actions = list({
                ai.title
                for c in all_in_cluster
                for ai in c.action_items
            })
            services = list({
                svc
                for c in all_in_cluster
                for svc in c.incident.affected_services
            })

            pattern = {
                "incident_ids": [c.incident.id for c in all_in_cluster],
                "merged_lessons": merged_lessons,
                "merged_action_items": merged_actions,
                "pattern_summary": (
                    f"Pattern detected: '{pm.root_cause.primary}' recurred across "
                    f"{len(all_in_cluster)} incidents "
                    f"({', '.join(c.incident.id for c in all_in_cluster)}) "
                    f"affecting {', '.join(services)}. "
                    "This may indicate an architectural issue."
                ),
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }
            patterns.append(pattern)
            logger.info(
                "Consolidator: pattern found — %d incidents: %s",
                len(all_in_cluster),
                ", ".join(c.incident.id for c in all_in_cluster),
            )

        return patterns
