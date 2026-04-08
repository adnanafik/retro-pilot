# Phase 4 — Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve ≥85% coverage on `agents/` and `evaluator/` by completing and hardening the test suite with shared fixtures, edge cases, and coverage gap analysis.

**Architecture:** All tests use injected mock backends — no real API calls. `tests/conftest.py` provides shared fixtures. Existing test files from Phases 1–3 are extended with edge cases. `tests/fixtures/` holds sample JSON data for realistic testing.

**Tech Stack:** pytest, pytest-asyncio, pytest-cov, unittest.mock

**Prerequisite:** Phase 3 merged. All source files exist.

---

## File Map

| File | Responsibility |
|------|----------------|
| `tests/conftest.py` | Shared fixtures: `sample_incident`, `mock_backend`, `mock_chroma`, `mock_embedder` |
| `tests/fixtures/sample_incident.json` | Realistic incident JSON for fixture loading |
| `tests/fixtures/sample_evidence.json` | Sample evidence data |
| `tests/test_orchestrator.py` | Extended: edge cases, KB retrieval, revision loop |
| `tests/test_evaluator.py` | Extended: boundary scores, each dimension independently |
| `tests/test_vector_store.py` | Extended: consolidator tests |
| `tests/test_timeline_builder.py` | Extended: empty evidence, all-same-timestamp |
| `tests/test_root_cause_analyst.py` | Extended: similar incidents integration |
| `tests/test_action_item_generator.py` | Extended: prior incident escalation |

---

## Task 1: Shared Fixtures & Fixture Data

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_incident.json`
- Create: `tests/fixtures/sample_evidence.json`

- [ ] **Step 1: Create fixtures directory and sample data**

```bash
mkdir -p tests/fixtures
```

- [ ] **Step 2: Create tests/fixtures/sample_incident.json**

```json
{
  "id": "INC-2026-0001",
  "title": "Redis connection pool exhaustion in auth-service",
  "severity": "SEV1",
  "started_at": "2026-01-15T14:00:00+00:00",
  "resolved_at": "2026-01-15T14:47:00+00:00",
  "affected_services": ["auth-service", "payment-service", "session-service"],
  "involved_repos": ["acme/auth-service"],
  "slack_channel": "#incident-2026-0001",
  "metrics_namespace": "auth-service",
  "reported_by": "oncall-engineer"
}
```

- [ ] **Step 3: Create tests/fixtures/sample_evidence.json**

```json
{
  "logs": [
    {
      "timestamp": "2026-01-15T14:02:00+00:00",
      "level": "WARN",
      "service": "auth-service",
      "message": "Connection pool utilisation at 85%"
    },
    {
      "timestamp": "2026-01-15T14:05:00+00:00",
      "level": "ERROR",
      "service": "auth-service",
      "message": "Connection pool exhausted — timeout waiting for available slot"
    },
    {
      "timestamp": "2026-01-15T14:07:00+00:00",
      "level": "ERROR",
      "service": "payment-service",
      "message": "Upstream auth-service request timeout after 5000ms"
    }
  ],
  "metrics": [
    {
      "timestamp": "2026-01-15T14:01:00+00:00",
      "metric_name": "connection_pool_utilisation",
      "value": 82.0,
      "unit": "Percent"
    },
    {
      "timestamp": "2026-01-15T14:05:00+00:00",
      "metric_name": "connection_pool_utilisation",
      "value": 100.0,
      "unit": "Percent"
    }
  ],
  "git_events": [
    {
      "timestamp": "2026-01-15T13:00:00+00:00",
      "commit_sha": "abc1234567890",
      "author": "deploy-bot@acme.com",
      "message": "Deploy auth-service v2.3.1 — no code changes, dependency bump",
      "repo": "acme/auth-service",
      "type": "deploy"
    }
  ],
  "slack_messages": [
    {
      "timestamp": "2026-01-15T14:12:00+00:00",
      "author": "oncall-engineer",
      "text": "Incident declared — auth-service returning 503s. Investigating.",
      "thread_ts": "1705327920.000100"
    },
    {
      "timestamp": "2026-01-15T14:47:00+00:00",
      "author": "oncall-engineer",
      "text": "Incident resolved — increased connection pool size to 200. Monitoring.",
      "thread_ts": "1705327920.000200"
    }
  ],
  "collected_at": "2026-01-15T15:00:00+00:00",
  "gaps": []
}
```

- [ ] **Step 4: Create tests/conftest.py**

```python
"""Shared fixtures for retro-pilot test suite."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.models import (
    ActionItem, Evidence, GitEvent, Incident, LogEntry,
    MetricSnapshot, PostMortem, RootCause, SlackMessage,
    Timeline, TimelineEvent,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
RESOLVED = datetime(2026, 1, 15, 14, 47, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_incident() -> Incident:
    data = json.loads((FIXTURES_DIR / "sample_incident.json").read_text())
    return Incident(**data)


@pytest.fixture
def sample_evidence() -> Evidence:
    data = json.loads((FIXTURES_DIR / "sample_evidence.json").read_text())
    return Evidence(**data)


@pytest.fixture
def sample_root_cause() -> RootCause:
    return RootCause(
        primary="Connection pool exhausted in auth-service caused cascading timeouts",
        contributing_factors=[
            "Pool size (50) not reviewed after 3x traffic growth over 6 months",
            "No pool saturation alert existed to warn before exhaustion",
        ],
        trigger="Marketing campaign launched at 14:00 increased login rate 4x",
        blast_radius="payment-service and session-service — all auth-service dependents",
        confidence="HIGH",
        evidence_refs=["log:auth-service:14:05", "metric:connection_pool_utilisation:14:05"],
    )


@pytest.fixture
def sample_action_items() -> list[ActionItem]:
    return [
        ActionItem(
            title="Increase Redis connection pool size from 50 to 200",
            owner_role="Platform team",
            deadline_days=7,
            priority="P1",
            type="prevention",
            acceptance_criteria=(
                "Pool size set to 200, load test at 5x current peak traffic passes "
                "with <5% error rate in staging before prod deployment"
            ),
        ),
        ActionItem(
            title="Add connection pool saturation PagerDuty alert",
            owner_role="Platform team",
            deadline_days=14,
            priority="P1",
            type="detection",
            acceptance_criteria=(
                "Alert fires when pool utilisation exceeds 80% for 5 consecutive minutes. "
                "Tested by manually raising utilisation in staging."
            ),
        ),
        ActionItem(
            title="Add connection pool load test to release checklist",
            owner_role="Engineering team",
            deadline_days=30,
            priority="P2",
            type="prevention",
            acceptance_criteria=(
                "Release checklist includes load test step. "
                "Verified present in next release review."
            ),
        ),
    ]


@pytest.fixture
def sample_timeline() -> Timeline:
    return Timeline(
        events=[
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 1, tzinfo=timezone.utc),
                description="Metric connection_pool_utilisation = 82%",
                source="metric", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 2, tzinfo=timezone.utc),
                description="[auth-service] Connection pool utilisation at 85%",
                source="log", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 5, tzinfo=timezone.utc),
                description="[auth-service] Connection pool exhausted",
                source="log", significance="critical",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 7, tzinfo=timezone.utc),
                description="[payment-service] Upstream timeout from auth-service",
                source="log", significance="critical",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 12, tzinfo=timezone.utc),
                description="[Slack] oncall: Incident declared",
                source="slack", significance="high",
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
                description="[Slack] oncall: Incident resolved",
                source="slack", significance="critical",
            ),
        ],
        first_signal_at=datetime(2026, 1, 15, 14, 1, tzinfo=timezone.utc),
        detection_lag_minutes=11,
        resolution_duration_minutes=47,
    )


@pytest.fixture
def sample_postmortem(
    sample_incident, sample_timeline, sample_root_cause, sample_action_items
) -> PostMortem:
    return PostMortem(
        incident=sample_incident,
        executive_summary=(
            "Auth service experienced a 47-minute outage affecting payment and session services. "
            "The outage was caused by a capacity limit that had not been reviewed since user traffic tripled. "
            "Capacity has been increased and monitoring added to prevent recurrence."
        ),
        timeline=sample_timeline,
        root_cause=sample_root_cause,
        action_items=sample_action_items,
        lessons_learned=[
            "Connection pool capacity should be reviewed whenever traffic grows by more than 50%.",
            "Detection lag often exceeds 10 minutes when monitoring measures availability, not leading indicators.",
        ],
        similar_incidents=["INC-2026-0089"],
        generated_at=NOW,
    )


@pytest.fixture
def mock_backend():
    """Mock LLM backend. Returns configurable responses."""
    backend = MagicMock()
    backend.complete.return_value = "Mock LLM response"
    backend.complete_with_tools.return_value = MagicMock(
        content=[MagicMock(type="text", text="done")],
        stop_reason="end_turn",
    )
    return backend


@pytest.fixture
def mock_embedder():
    """Mock embedder returning a fixed 384-dim vector."""
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 384
    embedder.embed_many.return_value = [[0.1] * 384]
    return embedder


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB collection."""
    collection = MagicMock()
    collection.count.return_value = 0
    collection.query.return_value = {
        "ids": [[]], "distances": [[]], "metadatas": [[]]
    }
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client, collection
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/fixtures/
git commit -m "test: shared fixtures — conftest, sample incident and evidence JSON"
```

---

## Task 2: Coverage Gap Analysis & Hardening

Run the existing suite and identify what's below 85%.

- [ ] **Step 1: Run coverage report**

```bash
pytest tests/ -v --cov=agents --cov=evaluator --cov=shared --cov=tools \
  --cov-report=term-missing --tb=short
```
Note which files are below 85%. Common gaps will be in:
- `agents/orchestrator_agent.py` — revision cycle edge cases
- `evaluator/scorer.py` — boundary conditions per dimension
- `agents/evidence_collector.py` — exception paths

- [ ] **Step 2: Add edge case tests for EvidenceCollector gaps**

Add to `tests/test_evidence_collector.py`:

```python
def test_evidence_collector_handles_worker_exception_gracefully():
    """If one worker fails, the rest still return data."""
    from agents.evidence_collector import EvidenceCollector
    from unittest.mock import patch
    import asyncio

    collector = EvidenceCollector()
    # Patch the Slack worker to raise
    with patch.object(collector, "_run_slack_worker", side_effect=RuntimeError("Slack down")):
        result = collector.run(make_incident(), demo_mode=True)

    assert isinstance(result, Evidence)
    # Gap should be recorded
    assert any("slack" in g.lower() for g in result.gaps)
```

- [ ] **Step 3: Add boundary tests for scorer dimensions**

Add to `tests/test_evaluator.py`:

```python
def test_scorer_timeline_zero_events_scores_very_low():
    from evaluator.scorer import score_postmortem
    pm = make_strong_postmortem()
    pm = pm.model_copy(update={"timeline": pm.timeline.model_copy(update={"events": []})})
    score = score_postmortem(pm, knowledge_base_size=0)
    assert score.timeline_completeness < 0.40


def test_scorer_root_cause_no_evidence_refs_penalised():
    from evaluator.scorer import score_postmortem
    pm = make_strong_postmortem()
    rc = pm.root_cause.model_copy(update={"evidence_refs": []})
    pm = pm.model_copy(update={"root_cause": rc})
    score = score_postmortem(pm, knowledge_base_size=0)
    assert score.root_cause_clarity < 0.90


def test_scorer_executive_summary_jargon_penalised():
    from evaluator.scorer import score_postmortem
    pm = make_strong_postmortem()
    pm = pm.model_copy(update={
        "executive_summary": "The RCA showed p99 latency spikes. MTTR was 47 minutes. SLO was breached."
    })
    score = score_postmortem(pm, knowledge_base_size=0)
    assert score.executive_summary_clarity < 0.70


def test_scorer_all_action_items_missing_criteria_scores_zero():
    from evaluator.scorer import score_postmortem
    pm = make_strong_postmortem()
    bad_items = [
        ai.model_copy(update={"acceptance_criteria": ""})
        for ai in pm.action_items
    ]
    pm = pm.model_copy(update={"action_items": bad_items})
    score = score_postmortem(pm, knowledge_base_size=0)
    assert score.action_item_quality < 0.60


def test_score_total_matches_weighted_sum():
    from evaluator.scorer import score_postmortem
    from evaluator.rubric import WEIGHTS
    pm = make_strong_postmortem()
    score = score_postmortem(pm, knowledge_base_size=10)
    expected = (
        score.timeline_completeness * WEIGHTS["timeline_completeness"]
        + score.root_cause_clarity * WEIGHTS["root_cause_clarity"]
        + score.action_item_quality * WEIGHTS["action_item_quality"]
        + score.executive_summary_clarity * WEIGHTS["executive_summary_clarity"]
        + score.similar_incidents_referenced * WEIGHTS["similar_incidents_referenced"]
    )
    assert abs(score.total - round(expected, 3)) < 0.001
```

- [ ] **Step 4: Add KB-size edge cases for orchestrator**

Add to `tests/test_orchestrator.py`:

```python
@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_handles_empty_kb(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs.count.return_value = 0
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.return_value = make_passing_score()

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())
    assert isinstance(result, PostMortem)


@patch("agents.orchestrator_agent.VectorStore")
def test_orchestrator_revision_count_increments(mock_vs_cls):
    mock_vs = MagicMock()
    mock_vs.retrieve.return_value = []
    mock_vs_cls.return_value = mock_vs

    mock_evaluator = MagicMock()
    mock_evaluator.run.side_effect = [
        make_failing_score(0),
        make_failing_score(1),
        make_passing_score(2),
    ]

    orchestrator = OrchestratorAgent(demo_mode=True)
    orchestrator._evaluator = mock_evaluator

    result = orchestrator.run(make_incident())
    assert result.revision_count == 2
```

- [ ] **Step 5: Run coverage again — target ≥85%**

```bash
pytest tests/ --cov=agents --cov=evaluator --cov-report=term-missing --tb=short
```
Expected: agents/ and evaluator/ both ≥85%.

If still below 85%, check the `--cov-report=term-missing` output for uncovered lines and add targeted tests.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: harden suite — edge cases, coverage gaps, shared fixtures"
```

---

## Task 3: Docker Test Run

- [ ] **Step 1: Verify docker compose test target works**

```bash
docker compose run --rm test
```
Expected:
```
... all tests pass ...
---------- coverage: ... ----------
PASSED  X tests
```
Exit code 0.

- [ ] **Step 2: Fix any Docker-only failures**

Common issues:
- Import errors from missing `__init__.py` files — check all packages
- ChromaDB needing write access — verify `/app/chroma_db` is created in Dockerfile
- sentence-transformers model download — set `HF_HUB_OFFLINE=1` for tests using mock embedder

- [ ] **Step 3: Commit any Docker fixes**

```bash
git add .
git commit -m "chore: fix docker test environment issues"
```

---

## Phase 4 Completion Gate

- [ ] **Final coverage check and PR**

```bash
pytest tests/ -v \
  --cov=agents --cov=evaluator --cov=shared --cov=tools \
  --cov-report=term-missing \
  --cov-fail-under=85
```
Expected: exit code 0 (≥85% coverage).

```bash
ruff check .
git push -u origin phase/4-tests
gh pr create \
  --title "test: full pytest suite — ≥85% coverage on agents and evaluator" \
  --body "$(cat <<'EOF'
## Summary

- `tests/conftest.py` — shared fixtures: sample_incident, sample_evidence, mock_backend, mock_embedder, mock_chroma
- `tests/fixtures/` — realistic sample JSON data
- Extended test files with edge cases: worker failure handling, scorer boundaries, revision loop increments
- ≥85% coverage on agents/ and evaluator/

## Test plan

- [ ] `pytest tests/ --cov-fail-under=85` exits 0
- [ ] `docker compose run --rm test` exits 0
- [ ] No test uses real API calls (all backends mocked)
- [ ] Scorer boundary tests cover all 5 dimensions independently
- [ ] Orchestrator revision loop tested: 0 revisions, 1 revision, max revisions
EOF
)"
```
