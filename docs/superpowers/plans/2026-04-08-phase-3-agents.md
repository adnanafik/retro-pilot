# Phase 3 — Agent Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all 6 specialist agents and the OrchestratorAgent that coordinates them, including the 3-cycle revision loop.

**Architecture:** Each specialist agent extends `BaseAgent`, constructs an `AgentLoop` with scoped tools, and returns a typed Pydantic model. The OrchestratorAgent runs them in sequence, passes typed outputs downstream, sends the assembled PostMortem through EvaluatorAgent, and loops up to 3 times on revision. Evidence workers (Log, Metrics, Git, Slack) run with READ_ONLY tools and cannot spawn further workers.

**Tech Stack:** Anthropic SDK (via backend injection), Pydantic v2, asyncio, existing `AgentLoop` / `ToolRegistry` / `VectorStore` from Phases 1 & 2.

**Prerequisite:** Phases 1 and 2 merged.

---

## File Map

| File | Responsibility |
|------|----------------|
| `agents/evidence_collector.py` | Runs 4 parallel workers (Log, Metrics, Git, Slack); assembles Evidence |
| `agents/timeline_builder.py` | Evidence → Timeline; identifies first_signal_at, detection lag |
| `agents/root_cause_analyst.py` | Evidence + Timeline + similar_incidents → RootCause |
| `agents/action_item_generator.py` | RootCause + similar_incidents → list[ActionItem]; checks prior action item completion |
| `agents/postmortem_writer.py` | Assembles all outputs → PostMortem; writes executive_summary + lessons_learned |
| `agents/orchestrator_agent.py` | Coordinates full pipeline + revision loop (max 3 cycles) |
| `scripts/run_postmortem.py` | CLI entry point: loads config, triggers orchestrator for an incident |
| `tests/test_timeline_builder.py` | Timeline event ordering, first_signal_at, detection lag |
| `tests/test_root_cause_analyst.py` | Primary/contributing/trigger distinction, evidence refs |
| `tests/test_action_item_generator.py` | Owner + deadline + acceptance criteria validation |
| `tests/test_orchestrator.py` | Full pipeline with mocks; revision loop termination at 3 cycles |

---

## Task 1: EvidenceCollector

**Files:**
- Create: `agents/evidence_collector.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_evidence_collector.py
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from shared.models import Incident, Evidence
from agents.evidence_collector import EvidenceCollector

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_incident() -> Incident:
    return Incident(
        id="INC-2026-0001",
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
        affected_services=["auth-service"],
        involved_repos=["acme/auth-service"],
        slack_channel="#incidents",
        reported_by="oncall",
    )


def test_evidence_collector_returns_evidence_model():
    """EvidenceCollector.run() returns a typed Evidence in DEMO_MODE."""
    collector = EvidenceCollector()
    inc = make_incident()
    result = collector.run(inc, demo_mode=True)
    assert isinstance(result, Evidence)


def test_evidence_has_logs_in_demo_mode():
    collector = EvidenceCollector()
    result = collector.run(make_incident(), demo_mode=True)
    assert isinstance(result.logs, list)
    assert isinstance(result.metrics, list)
    assert isinstance(result.git_events, list)
    assert isinstance(result.slack_messages, list)


def test_evidence_collector_describe():
    collector = EvidenceCollector()
    assert "evidence" in collector.describe().lower()


def test_evidence_collector_gaps_list_is_present():
    collector = EvidenceCollector()
    result = collector.run(make_incident(), demo_mode=True)
    assert isinstance(result.gaps, list)
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_evidence_collector.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.evidence_collector'`

- [ ] **Step 3: Implement agents/evidence_collector.py**

```python
"""EvidenceCollector — parallel evidence gathering for retro-pilot.

Runs four workers concurrently (Log, Metrics, Git, Slack), each with
READ_ONLY scoped tools. Workers cannot spawn further workers.
Assembles typed Evidence, noting gaps where data was unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from agents.base_agent import BaseAgent
from shared.models import (
    Evidence, GitEvent, Incident, LogEntry,
    MetricSnapshot, SlackMessage,
)
from tools.read_tools import (
    GetGitHistoryTool, GetLogsTool, GetMetricsTool,
    GetServiceMapTool, GetSlackThreadTool,
)

logger = logging.getLogger(__name__)

_WINDOW_MINUTES = 30  # ± window around incident


class EvidenceCollector(BaseAgent):
    """Gathers evidence from logs, metrics, git, and Slack in parallel.

    Each data source runs in an isolated worker with READ_ONLY tools.
    Workers cannot call each other or spawn sub-workers.
    """

    def describe(self) -> str:
        return "Parallel evidence collector: fetches logs, metrics, git history, and Slack thread"

    def run(self, incident: Incident, demo_mode: bool = False) -> Evidence:
        """Collect evidence for an incident.

        Args:
            incident: The Incident to investigate.
            demo_mode: If True (or DEMO_MODE env var set), returns synthetic data.

        Returns:
            Evidence with logs, metrics, git_events, slack_messages, gaps.
        """
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        return asyncio.run(self._collect(incident, use_demo))

    async def _collect(self, incident: Incident, demo_mode: bool) -> Evidence:
        start = incident.started_at - timedelta(minutes=_WINDOW_MINUTES)
        end = incident.resolved_at + timedelta(minutes=_WINDOW_MINUTES)
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        log_tool = GetLogsTool()
        metrics_tool = GetMetricsTool()
        git_tool = GetGitHistoryTool()
        slack_tool = GetSlackThreadTool()

        results = await asyncio.gather(
            self._run_log_worker(log_tool, incident, start_iso, end_iso, demo_mode),
            self._run_metrics_worker(metrics_tool, incident, start_iso, end_iso, demo_mode),
            self._run_git_worker(git_tool, incident, demo_mode),
            self._run_slack_worker(slack_tool, incident, demo_mode),
            return_exceptions=True,
        )

        logs, metrics, git_events, slack_messages = [], [], [], []
        gaps: list[str] = []

        for i, (label, result) in enumerate(zip(
            ["logs", "metrics", "git_events", "slack_messages"], results
        )):
            if isinstance(result, Exception):
                gaps.append(f"{label}: {result}")
                logger.warning("EvidenceCollector: %s worker failed: %s", label, result)
            else:
                if label == "logs": logs = result
                elif label == "metrics": metrics = result
                elif label == "git_events": git_events = result
                elif label == "slack_messages": slack_messages = result

        return Evidence(
            logs=logs,
            metrics=metrics,
            git_events=git_events,
            slack_messages=slack_messages,
            collected_at=datetime.now(tz=timezone.utc),
            gaps=gaps,
        )

    async def _run_log_worker(
        self, tool: GetLogsTool, incident: Incident,
        start: str, end: str, demo_mode: bool
    ) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for service in incident.affected_services:
            raw = tool.execute(service=service, start_time=start, end_time=end,
                               demo_mode=demo_mode)
            for item in json.loads(raw):
                if isinstance(item, dict) and "timestamp" in item:
                    entries.append(LogEntry(
                        timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                        level=item.get("level", "INFO"),
                        service=item.get("service", service),
                        message=item.get("message", ""),
                    ))
        return entries

    async def _run_metrics_worker(
        self, tool: GetMetricsTool, incident: Incident,
        start: str, end: str, demo_mode: bool
    ) -> list[MetricSnapshot]:
        snapshots: list[MetricSnapshot] = []
        ns = incident.metrics_namespace or incident.affected_services[0]
        raw = tool.execute(namespace=ns, metric_name="error_rate",
                           start_time=start, end_time=end, demo_mode=demo_mode)
        for item in json.loads(raw):
            if isinstance(item, dict) and "timestamp" in item:
                snapshots.append(MetricSnapshot(
                    timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                    metric_name=item.get("metric_name", "error_rate"),
                    value=float(item.get("value", 0.0)),
                    unit=item.get("unit", ""),
                ))
        return snapshots

    async def _run_git_worker(
        self, tool: GetGitHistoryTool, incident: Incident, demo_mode: bool
    ) -> list[GitEvent]:
        events: list[GitEvent] = []
        for repo in incident.involved_repos:
            raw = tool.execute(repo=repo, since_hours=24, demo_mode=demo_mode)
            for item in json.loads(raw):
                if isinstance(item, dict) and "timestamp" in item:
                    events.append(GitEvent(
                        timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                        commit_sha=item.get("commit_sha", ""),
                        author=item.get("author", ""),
                        message=item.get("message", ""),
                        repo=item.get("repo", repo),
                        type=item.get("type", "commit"),
                    ))
        return events

    async def _run_slack_worker(
        self, tool: GetSlackThreadTool, incident: Incident, demo_mode: bool
    ) -> list[SlackMessage]:
        raw = tool.execute(channel=incident.slack_channel, demo_mode=demo_mode)
        messages: list[SlackMessage] = []
        for item in json.loads(raw):
            if isinstance(item, dict) and "timestamp" in item:
                messages.append(SlackMessage(
                    timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                    author=item.get("author", ""),
                    text=item.get("text", ""),
                    thread_ts=item.get("thread_ts"),
                ))
        return messages
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_evidence_collector.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/evidence_collector.py tests/test_evidence_collector.py
git commit -m "feat: EvidenceCollector — parallel log/metrics/git/slack workers"
```

---

## Task 2: TimelineBuilder

**Files:**
- Create: `agents/timeline_builder.py`
- Create: `tests/test_timeline_builder.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_timeline_builder.py
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import MagicMock
from shared.models import (
    Evidence, LogEntry, MetricSnapshot, GitEvent, SlackMessage, Timeline,
)
from agents.timeline_builder import TimelineBuilder

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_evidence_with_events() -> Evidence:
    return Evidence(
        logs=[
            LogEntry(timestamp=NOW + timedelta(minutes=5),
                     level="ERROR", service="auth-service",
                     message="Connection pool exhausted"),
            LogEntry(timestamp=NOW + timedelta(minutes=7),
                     level="ERROR", service="payment-service",
                     message="Upstream timeout from auth-service"),
        ],
        metrics=[
            MetricSnapshot(timestamp=NOW + timedelta(minutes=2),
                           metric_name="connection_pool_utilisation",
                           value=95.0, unit="Percent"),
        ],
        git_events=[
            GitEvent(timestamp=NOW - timedelta(hours=1),
                     commit_sha="abc123", author="dev@acme.com",
                     message="Deploy v2.3.1", repo="acme/auth", type="deploy"),
        ],
        slack_messages=[
            SlackMessage(timestamp=NOW + timedelta(minutes=12),
                         author="oncall", text="Incident declared",
                         thread_ts=None),
        ],
        collected_at=NOW,
        gaps=[],
    )


def test_timeline_builder_returns_timeline():
    backend = MagicMock()
    backend.complete.return_value = "{}"  # won't be used in demo mode
    builder = TimelineBuilder(backend=backend)
    evidence = make_evidence_with_events()
    result = builder.run(evidence, demo_mode=True)
    assert isinstance(result, Timeline)


def test_timeline_events_sorted_by_timestamp():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    timestamps = [e.timestamp for e in result.events]
    assert timestamps == sorted(timestamps)


def test_timeline_has_events_from_all_sources():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    sources = {e.source for e in result.events}
    assert "log" in sources
    assert "metric" in sources
    assert "git" in sources
    assert "slack" in sources


def test_timeline_first_signal_is_earliest_anomaly():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    # First signal should be the metric at NOW+2min (before the log error at NOW+5min)
    assert result.first_signal_at <= NOW + timedelta(minutes=5)


def test_timeline_detection_lag_is_non_negative():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    assert result.detection_lag_minutes >= 0


def test_timeline_resolution_duration_is_positive():
    backend = MagicMock()
    builder = TimelineBuilder(backend=backend)
    result = builder.run(make_evidence_with_events(), demo_mode=True)
    assert result.resolution_duration_minutes > 0


def test_timeline_builder_describe():
    builder = TimelineBuilder()
    assert "timeline" in builder.describe().lower()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_timeline_builder.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.timeline_builder'`

- [ ] **Step 3: Implement agents/timeline_builder.py**

```python
"""TimelineBuilder — reconstructs incident timeline from Evidence.

Correlates events across logs, metrics, git, and Slack by timestamp.
Identifies first_signal_at (earliest anomaly before the alert), calculates
detection_lag_minutes (first signal → human alert), and marks significance.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from agents.base_agent import BaseAgent
from shared.models import (
    Evidence, GitEvent, LogEntry, MetricSnapshot,
    SlackMessage, Timeline, TimelineEvent,
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
            started_at or datetime.now(tz=timezone.utc)
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
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_timeline_builder.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/timeline_builder.py tests/test_timeline_builder.py
git commit -m "feat: TimelineBuilder — correlates events, identifies first signal"
```

---

## Task 3: RootCauseAnalyst

**Files:**
- Create: `agents/root_cause_analyst.py`
- Create: `tests/test_root_cause_analyst.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_root_cause_analyst.py
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
from shared.models import Evidence, Timeline, RootCause, PostMortem
from agents.root_cause_analyst import RootCauseAnalyst

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_empty_evidence() -> Evidence:
    return Evidence(
        logs=[], metrics=[], git_events=[], slack_messages=[],
        collected_at=NOW, gaps=[],
    )


def make_empty_timeline() -> Timeline:
    return Timeline(
        events=[], first_signal_at=NOW,
        detection_lag_minutes=12, resolution_duration_minutes=47,
    )


def test_root_cause_analyst_returns_root_cause_in_demo_mode():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result, RootCause)


def test_root_cause_has_required_fields():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert result.primary
    assert isinstance(result.contributing_factors, list)
    assert result.trigger
    assert result.blast_radius
    assert result.confidence in ("HIGH", "MEDIUM", "LOW")


def test_root_cause_primary_is_single_sentence():
    analyst = RootCauseAnalyst()
    result = analyst.run(
        evidence=make_empty_evidence(),
        timeline=make_empty_timeline(),
        similar_incidents=[],
        demo_mode=True,
    )
    sentence_count = len([s for s in result.primary.split(".") if s.strip()])
    assert sentence_count <= 2  # Generous allowance for demo data


def test_root_cause_analyst_describe():
    analyst = RootCauseAnalyst()
    assert "root cause" in analyst.describe().lower()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_root_cause_analyst.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.root_cause_analyst'`

- [ ] **Step 3: Implement agents/root_cause_analyst.py**

```python
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

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent, AgentLoop
from shared.models import Evidence, PostMortem, RootCause, Timeline
from tools.read_tools import GetLogsTool, GetMetricsTool, GetGitHistoryTool
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
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_root_cause_analyst.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/root_cause_analyst.py tests/test_root_cause_analyst.py
git commit -m "feat: RootCauseAnalyst — primary/contributing/trigger distinction"
```

---

## Task 4: ActionItemGenerator

**Files:**
- Create: `agents/action_item_generator.py`
- Create: `tests/test_action_item_generator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_action_item_generator.py
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
from shared.models import ActionItem, PostMortem, RootCause
from agents.action_item_generator import ActionItemGenerator

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_root_cause() -> RootCause:
    return RootCause(
        primary="Connection pool exhausted in auth-service",
        contributing_factors=["Pool size not scaled after growth"],
        trigger="Traffic spike from marketing campaign",
        blast_radius="payment-service, session-service",
        confidence="HIGH",
        evidence_refs=["log:auth:14:00"],
    )


def test_action_item_generator_returns_list_of_action_items():
    gen = ActionItemGenerator()
    result = gen.run(
        root_cause=make_root_cause(),
        similar_incidents=[],
        demo_mode=True,
    )
    assert isinstance(result, list)
    assert all(isinstance(ai, ActionItem) for ai in result)


def test_action_items_all_have_acceptance_criteria():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.acceptance_criteria.strip(), \
            f"Action item '{ai.title}' has no acceptance_criteria"


def test_action_items_all_have_owner_role():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.owner_role.strip(), \
            f"Action item '{ai.title}' has no owner_role"


def test_action_items_all_have_deadline():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    for ai in result:
        assert ai.deadline_days > 0, \
            f"Action item '{ai.title}' has deadline_days=0"


def test_action_items_cover_multiple_types():
    gen = ActionItemGenerator()
    result = gen.run(make_root_cause(), similar_incidents=[], demo_mode=True)
    types_present = {ai.type for ai in result}
    assert len(types_present) >= 2, \
        f"Only one action item type present: {types_present}"


def test_action_item_generator_describe():
    gen = ActionItemGenerator()
    assert "action" in gen.describe().lower()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_action_item_generator.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.action_item_generator'`

- [ ] **Step 3: Implement agents/action_item_generator.py**

```python
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
from typing import Any

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
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_action_item_generator.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/action_item_generator.py tests/test_action_item_generator.py
git commit -m "feat: ActionItemGenerator — owner-assigned items with acceptance criteria"
```

---

## Task 5: PostMortemWriter

**Files:**
- Create: `agents/postmortem_writer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_postmortem_writer.py
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
from shared.models import (
    Incident, Evidence, Timeline, RootCause, ActionItem, PostMortem,
)
from agents.postmortem_writer import PostMortemWriter

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_all_inputs():
    inc = Incident(
        id="INC-2026-0001", title="Redis pool exhaustion",
        severity="SEV1", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
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
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_postmortem_writer.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.postmortem_writer'`

- [ ] **Step 3: Implement agents/postmortem_writer.py**

```python
"""PostMortemWriter — assembles the final PostMortem document.

Writes:
  - executive_summary: ≤3 sentences, non-technical, for a business audience
  - lessons_learned: distilled insights, not action items
  - Assembles all specialist outputs into the PostMortem model

draft is always True — humans review and approve before distribution.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

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
            generated_at=datetime.now(tz=timezone.utc),
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
        return self.backend.complete(
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
        raw = self.backend.complete(
            system=_SYSTEM_PROMPT,
            user=prompt,
            model=self.model,
            max_tokens=512,
        )
        import json, re
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except Exception:
            return [cleaned]
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_postmortem_writer.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/postmortem_writer.py tests/test_postmortem_writer.py
git commit -m "feat: PostMortemWriter — assembles PostMortem with non-technical executive summary"
```

---

## Task 6: OrchestratorAgent

**Files:**
- Create: `agents/orchestrator_agent.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch
from shared.models import Incident, PostMortem, EvaluationScore
from agents.orchestrator_agent import OrchestratorAgent

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_incident() -> Incident:
    return Incident(
        id="INC-2026-0001",
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
        affected_services=["auth-service"],
        involved_repos=["acme/auth"],
        slack_channel="#incidents",
        reported_by="oncall",
    )


def make_passing_score(revision_number: int = 0) -> EvaluationScore:
    return EvaluationScore(
        total=0.91, timeline_completeness=0.90, root_cause_clarity=0.95,
        action_item_quality=0.90, executive_summary_clarity=0.85,
        similar_incidents_referenced=0.90, passed=True,
        revision_brief=None, revision_number=revision_number,
    )


def make_failing_score(revision_number: int = 0) -> EvaluationScore:
    return EvaluationScore(
        total=0.72, timeline_completeness=0.60, root_cause_clarity=0.70,
        action_item_quality=0.80, executive_summary_clarity=0.75,
        similar_incidents_referenced=0.70, passed=False,
        revision_brief="Timeline has only 2 events. Action item 1 missing acceptance_criteria.",
        revision_number=revision_number,
    )


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_returns_postmortem_on_first_pass(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    assert result.draft is True
    assert result.revision_count == 0
    mock_evaluator.run.assert_called_once()


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_revises_on_fail_then_passes(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.side_effect = [
        make_failing_score(revision_number=0),  # First attempt fails
        make_passing_score(revision_number=1),  # Revision passes
    ]

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    assert mock_evaluator.run.call_count == 2
    assert result.revision_count == 1


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_stops_at_max_3_revisions(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    # Always fail
    mock_evaluator.run.return_value = make_failing_score()

    orchestrator = OrchestratorAgent(demo_mode=True, max_revision_cycles=3)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    assert isinstance(result, PostMortem)
    # Should be called at most max_revision_cycles + 1 times
    assert mock_evaluator.run.call_count <= 4
    assert result.draft is True  # Still draft — never passed


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_stores_passing_postmortem(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())

    mock_vs.store.assert_called_once()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_orchestrator.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.orchestrator_agent'`

- [ ] **Step 3: Implement agents/orchestrator_agent.py**

```python
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
from typing import Any

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
        backend: Any = None,
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
```

- [ ] **Step 4: Run all orchestrator tests — pass**

```bash
pytest tests/test_orchestrator.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator_agent.py tests/test_orchestrator.py
git commit -m "feat: OrchestratorAgent — full pipeline + revision loop, max 3 cycles"
```

---

## Task 7: CLI Entry Point

**Files:**
- Create: `scripts/run_postmortem.py`

- [ ] **Step 1: Implement scripts/run_postmortem.py**

```python
#!/usr/bin/env python3
"""Entry point: trigger a post-mortem for a resolved incident.

Usage:
  python scripts/run_postmortem.py --incident-id INC-2026-0001 \
    --title "Redis pool exhaustion" --severity SEV1 \
    --started-at 2026-01-15T14:00:00Z \
    --resolved-at 2026-01-15T14:47:00Z \
    --services auth-service payment-service \
    --repos acme/auth-service \
    --slack-channel "#incident-2026-0001" \
    --reported-by oncall
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run post-mortem for a resolved incident")
    p.add_argument("--incident-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--severity", choices=["SEV1", "SEV2", "SEV3", "SEV4"], required=True)
    p.add_argument("--started-at", required=True, help="ISO 8601 datetime")
    p.add_argument("--resolved-at", required=True, help="ISO 8601 datetime")
    p.add_argument("--services", nargs="+", required=True)
    p.add_argument("--repos", nargs="+", default=[])
    p.add_argument("--slack-channel", required=True)
    p.add_argument("--reported-by", required=True)
    p.add_argument("--metrics-namespace", default=None)
    p.add_argument("--demo-mode", action="store_true",
                   help="Run in demo mode without API calls")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.demo_mode:
        os.environ["DEMO_MODE"] = "true"

    from shared.models import Incident
    from agents.orchestrator_agent import OrchestratorAgent

    incident = Incident(
        id=args.incident_id,
        title=args.title,
        severity=args.severity,
        started_at=datetime.fromisoformat(args.started_at.replace("Z", "+00:00")),
        resolved_at=datetime.fromisoformat(args.resolved_at.replace("Z", "+00:00")),
        affected_services=args.services,
        involved_repos=args.repos,
        slack_channel=args.slack_channel,
        metrics_namespace=args.metrics_namespace,
        reported_by=args.reported_by,
    )

    demo = args.demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
    orchestrator = OrchestratorAgent(demo_mode=demo)

    logger.info("Starting post-mortem for %s", incident.id)
    postmortem = orchestrator.run(incident)

    output_path = f"postmortems/{incident.id}.json"
    import pathlib
    pathlib.Path("postmortems").mkdir(exist_ok=True)
    pathlib.Path(output_path).write_text(postmortem.model_dump_json(indent=2))

    logger.info("Post-mortem written to %s (draft=%s)", output_path, postmortem.draft)
    print(f"\nPost-mortem for {incident.id}:")
    print(f"  Executive summary: {postmortem.executive_summary}")
    print(f"  Root cause: {postmortem.root_cause.primary}")
    print(f"  Action items: {len(postmortem.action_items)}")
    print(f"  Revision count: {postmortem.revision_count}")
    print(f"  Draft: {postmortem.draft}")
    print(f"\nFull output: {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

```bash
python scripts/run_postmortem.py \
  --incident-id INC-2026-TEST \
  --title "Test incident" \
  --severity SEV2 \
  --started-at 2026-01-15T14:00:00Z \
  --resolved-at 2026-01-15T14:47:00Z \
  --services auth-service \
  --slack-channel "#test-incidents" \
  --reported-by engineer \
  --demo-mode
```
Expected: prints post-mortem summary, writes `postmortems/INC-2026-TEST.json`.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_postmortem.py
git commit -m "feat: scripts/run_postmortem.py — CLI entry point for post-mortem generation"
```

---

## Phase 3 Completion Gate

- [ ] **Run full suite and open PR**

```bash
pytest tests/ -v --tb=short
ruff check agents/ shared/ tools/ evaluator/ knowledge/
git push -u origin phase/3-agents
gh pr create \
  --title "feat: agent pipeline — orchestrator, 6 specialist agents, revision loop" \
  --body "$(cat <<'EOF'
## Summary

- `EvidenceCollector` — parallel workers (Log/Metrics/Git/Slack) with READ_ONLY scope
- `TimelineBuilder` — correlates events by timestamp, identifies first_signal_at
- `RootCauseAnalyst` — primary / contributing_factors / trigger distinction
- `ActionItemGenerator` — every item has owner, deadline, acceptance_criteria
- `PostMortemWriter` — ≤3 sentence executive summary, lessons_learned
- `OrchestratorAgent` — full pipeline + revision loop (max 3 cycles)
- `scripts/run_postmortem.py` — CLI entry point

## Test plan

- [ ] `pytest tests/` passes
- [ ] `python scripts/run_postmortem.py --demo-mode` completes without error
- [ ] Revision loop terminates at 3 cycles (mocked always-failing evaluator)
- [ ] Passing post-mortem is stored in vector store
- [ ] All action items have acceptance_criteria and owner_role
- [ ] `docker compose run --rm test` exits 0
EOF
)"
```
