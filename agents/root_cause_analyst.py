"""RootCauseAnalyst — deep multi-factor root cause analysis.

Distinguishes between:
  primary:              single-sentence root cause (what ultimately failed)
  contributing_factors: conditions that made the primary possible
  trigger:              what changed that exposed the issue
  blast_radius:         what else was affected

Uses Evidence + Timeline + similar_incidents from ChromaDB.
If similar incidents exist, explicitly notes whether their action items
were completed — escalates priority if they were not.
"""
from __future__ import annotations

import logging
import os

from agents.base_agent import AgentLoop, BaseAgent
from shared.models import Evidence, PostMortem, RootCause, Timeline
from tools.read_tools import GetGitHistoryTool, GetLogsTool, GetMetricsTool
from tools.registry import Permission, ToolRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert SRE performing multi-factor root cause analysis.

Your job is to distinguish between:
1. PRIMARY root cause: one sentence — the fundamental reason the system failed
2. CONTRIBUTING FACTORS: conditions that made the primary possible (not the same as primary)
3. TRIGGER: the specific change that exposed the issue (what was different today vs. yesterday)
4. BLAST RADIUS: which other services/users were affected

Rules:
- Primary must be ONE sentence. Not a paragraph. Not a list.
- Contributing factors must be distinct from the primary — do not repeat it.
- Trigger must be specific: "Marketing campaign launched at 14:00 increased login rate 4x"
  not "traffic increase".
- Include evidence_refs: reference specific log entries, metrics, or git events.
- If similar past incidents are provided, check: were their action items completed?
  If not, flag this — the same root cause recurring means the fix wasn't applied.
- Be honest about confidence: HIGH only if you have direct evidence."""


class RootCauseAnalyst(BaseAgent):
    """Performs deep multi-factor root cause analysis."""

    def describe(self) -> str:
        return "Root cause analyst: distinguishes primary cause, contributing factors, and trigger"

    def run(
        self,
        evidence: Evidence,
        timeline: Timeline,
        similar_incidents: list[PostMortem],
        demo_mode: bool = False,
    ) -> RootCause:
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        if use_demo:
            return self._demo_root_cause(evidence, similar_incidents)
        return self._analyse_with_llm(evidence, timeline, similar_incidents)

    def _demo_root_cause(
        self,
        evidence: Evidence,
        similar_incidents: list[PostMortem],
    ) -> RootCause:
        contributing = [
            "Connection pool size (50) was not adjusted after 3x user growth over 6 months"
        ]
        if similar_incidents:
            contributing.append(
                f"Similar incident {similar_incidents[0].incident.id} had the same pattern — "
                "verify whether its action items were completed"
            )
        evidence_refs = []
        if evidence.logs:
            evidence_refs.append(f"log:{evidence.logs[0].service}:{evidence.logs[0].timestamp.isoformat()}")
        if evidence.metrics:
            evidence_refs.append(f"metric:{evidence.metrics[0].metric_name}")

        return RootCause(
            primary="Connection pool exhaustion in auth-service caused cascading timeouts to downstream services",
            contributing_factors=contributing,
            trigger="Marketing campaign launched at 14:00 increased login rate 4x, exhausting the fixed-size pool",
            blast_radius="payment-service and session-service — all services with auth-service dependency",
            confidence="HIGH",
            evidence_refs=evidence_refs if evidence_refs else ["log:auth-service:14:00"],
        )

    def _analyse_with_llm(
        self,
        evidence: Evidence,
        timeline: Timeline,
        similar_incidents: list[PostMortem],
    ) -> RootCause:
        """Full LLM-driven analysis (live mode, non-demo)."""
        registry = ToolRegistry()
        for tool in [GetLogsTool(), GetMetricsTool(), GetGitHistoryTool()]:
            registry.register(tool)
        tools = registry.get_tools(max_permission=Permission.READ_ONLY)

        similar_context = ""
        if similar_incidents:
            similar_context = "\n\nSIMILAR PAST INCIDENTS:\n" + "\n".join(
                f"- {pm.incident.id}: {pm.root_cause.primary}\n"
                f"  Action items: {[ai.title for ai in pm.action_items]}"
                for pm in similar_incidents
            )

        prompt = (
            f"Analyse the root cause for this incident.\n\n"
            f"Timeline: {len(timeline.events)} events, "
            f"first signal at {timeline.first_signal_at.isoformat()}, "
            f"detection lag {timeline.detection_lag_minutes} minutes.\n"
            f"Evidence: {len(evidence.logs)} logs, {len(evidence.metrics)} metrics, "
            f"{len(evidence.git_events)} git events.\n"
            f"Gaps: {evidence.gaps}"
            f"{similar_context}"
        )

        loop = AgentLoop(
            tools=tools,
            backend=self.backend,
            domain_system_prompt=_SYSTEM_PROMPT,
            response_model=RootCause,
            model=self.model,
        )

        import asyncio
        result = asyncio.run(loop.run(
            messages=[{"role": "user", "content": prompt}],
            incident_id="",
        ))
        return result.extracted
