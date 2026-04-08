"""Structured scoring rubric for retro-pilot LLM-as-judge.

Five dimensions, each scored 0.0 → 1.0, with weights summing to 1.0.
PASS_THRESHOLD = 0.80 (configurable in retro-pilot.yml).
"""
from __future__ import annotations

PASS_THRESHOLD: float = 0.80

WEIGHTS: dict[str, float] = {
    "timeline_completeness": 0.20,
    "root_cause_clarity": 0.25,
    "action_item_quality": 0.25,
    "executive_summary_clarity": 0.15,
    "similar_incidents_referenced": 0.15,
}

# Minimum events for a complete timeline
MIN_TIMELINE_EVENTS: int = 5

# Minimum knowledge base size before similar-incidents dimension is scored strictly
MIN_KB_SIZE_FOR_SIMILAR: int = 5

# Jargon terms that lower executive summary score
EXECUTIVE_JARGON: list[str] = [
    "RCA", "MTTR", "MTTD", "SLO", "SLA", "p99", "percentile",
    "latency", "throughput", "idempotent", "synchronous", "asynchronous",
    "microservice", "kubernetes", "terraform", "canary", "blue-green",
]
