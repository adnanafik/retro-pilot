"""TimelineBuilder — reconstructs incident timeline from Evidence.

Correlates events across logs, metrics, git, and Slack by timestamp.
Identifies first_signal_at (earliest anomaly before the alert), calculates
detection_lag_minutes (first signal → human alert), and marks significance.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from agents.base_agent import BaseAgent
from shared.models import (
    Evidence,
    Timeline,
    TimelineEvent,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior SRE reconstructing an incident timeline.
Given evidence from logs, metrics, git history, and Slack, your job is to:
1. Identify the EARLIEST signal of a problem (not when the alert fired — when something first looked wrong).
2. Order events chronologically, noting the source (log/metric/git/slack/manual).
3. Mark significance: critical (directly caused or resolved the incident), high (contributed), medium (context), low (background).
4. Calculate detection_lag_minutes: from first_signal_at to when humans were alerted (Slack incident declaration or PagerDuty).
Stop when you have a complete picture of the incident sequence."""


class TimelineBuilder(BaseAgent):
    """Builds a Timeline from collected Evidence."""

    def describe(self) -> str:
        return "Timeline builder: correlates events across sources, identifies first signal and detection lag"

    def run(
        self,
        evidence: Evidence,
        incident_started_at: datetime | None = None,
        incident_resolved_at: datetime | None = None,
        demo_mode: bool = False,
    ) -> Timeline:
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        if use_demo:
            return self._build_from_evidence(evidence, incident_started_at, incident_resolved_at)
        return self._build_with_llm(evidence, incident_started_at, incident_resolved_at)

    def _build_from_evidence(
        self,
        evidence: Evidence,
        started_at: datetime | None,
        resolved_at: datetime | None,
    ) -> Timeline:
        """Build timeline directly from evidence without LLM (DEMO_MODE / fast path)."""
        events: list[TimelineEvent] = []

        for log in evidence.logs:
            sig = "critical" if log.level == "ERROR" else "medium"
            events.append(TimelineEvent(
                timestamp=log.timestamp, description=f"[{log.service}] {log.message}",
                source="log", significance=sig,
            ))

        for metric in evidence.metrics:
            sig = "high" if metric.value > 90 else "medium"
            events.append(TimelineEvent(
                timestamp=metric.timestamp,
                description=f"Metric {metric.metric_name} = {metric.value}{metric.unit}",
                source="metric", significance=sig,
            ))

        for git in evidence.git_events:
            events.append(TimelineEvent(
                timestamp=git.timestamp,
                description=f"Git {git.type}: {git.message} ({git.commit_sha[:8]})",
                source="git", significance="medium",
            ))

        for slack in evidence.slack_messages:
            events.append(TimelineEvent(
                timestamp=slack.timestamp,
                description=f"[Slack] {slack.author}: {slack.text[:100]}",
                source="slack", significance="medium",
            ))

        events.sort(key=lambda e: e.timestamp)

        # First signal: earliest non-git event (git events predate the incident)
        non_git = [e for e in events if e.source != "git"]
        first_signal = non_git[0].timestamp if non_git else (
            started_at or datetime.now(tz=UTC)
        )

        # Detection lag: from first signal to first Slack message
        slack_times = [e.timestamp for e in events if e.source == "slack"]
        first_alert = slack_times[0] if slack_times else first_signal
        detection_lag = max(0, int((first_alert - first_signal).total_seconds() / 60))

        # Resolution duration
        if started_at and resolved_at:
            resolution_duration = max(1, int((resolved_at - started_at).total_seconds() / 60))
        else:
            resolution_duration = 60  # fallback

        return Timeline(
            events=events,
            first_signal_at=first_signal,
            detection_lag_minutes=detection_lag,
            resolution_duration_minutes=resolution_duration,
        )

    def _build_with_llm(
        self,
        evidence: Evidence,
        started_at: datetime | None,
        resolved_at: datetime | None,
    ) -> Timeline:
        """Use LLM AgentLoop for richer timeline construction (live mode)."""
        # Fall back to heuristic build — LLM-driven timeline construction
        # will be wired in the orchestrator flow using the full AgentLoop.
        return self._build_from_evidence(evidence, started_at, resolved_at)
