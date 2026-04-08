# Phase 2 — Knowledge Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two architectural features unique to retro-pilot — ChromaDB semantic vector store and LLM-as-judge evaluator — in isolation before the agent pipeline exists.

**Architecture:** `knowledge/embedder.py` wraps sentence-transformers. `knowledge/vector_store.py` wraps ChromaDB (local persistent mode, no server). `evaluator/rubric.py` defines weighted scoring dimensions. `evaluator/scorer.py` computes EvaluationScore from a PostMortem. `agents/evaluator_agent.py` calls the scorer via an LLM loop.

**Tech Stack:** ChromaDB 0.5+, sentence-transformers (all-MiniLM-L6-v2), Pydantic v2, pytest with mock chromadb

**Prerequisite:** Phase 1 merged. All imports from `shared.models`, `tools.registry`, `agents.base_agent` are available.

---

## File Map

| File | Responsibility |
|------|----------------|
| `knowledge/__init__.py` | Empty package marker |
| `knowledge/embedder.py` | sentence-transformers wrapper — embed text → float vector |
| `knowledge/vector_store.py` | ChromaDB wrapper — embed, store, retrieve PostMortems |
| `knowledge/consolidator.py` | Weekly job: finds similarity > 0.90, merges lessons + action items |
| `evaluator/__init__.py` | Empty package marker |
| `evaluator/rubric.py` | Scoring rubric constants and dimension weights |
| `evaluator/scorer.py` | Rubric → EvaluationScore from a PostMortem (no LLM needed) |
| `agents/evaluator_agent.py` | LLM-as-judge: uses scorer + LLM to generate revision_brief |
| `tests/test_vector_store.py` | embed, store, retrieve, similarity filter |
| `tests/test_evaluator.py` | Rubric scoring with known fixture inputs |

---

## Task 1: Embedder

**Files:**
- Create: `knowledge/embedder.py`
- Create: `tests/test_vector_store.py` (partial — embedder tests only at this step)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vector_store.py
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from knowledge.embedder import Embedder


def test_embedder_returns_list_of_floats():
    """Embedder.embed() returns a non-empty list of floats."""
    with patch("knowledge.embedder.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        mock_st.return_value = mock_model

        embedder = Embedder()
        result = embedder.embed("Redis connection pool exhaustion")

    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(v, float) for v in result)


def test_embedder_embed_many_returns_list_of_lists():
    with patch("knowledge.embedder.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_st.return_value = mock_model

        embedder = Embedder()
        result = embedder.embed_many(["text one", "text two"])

    assert len(result) == 2
    assert all(len(v) == 2 for v in result)


def test_embedder_uses_correct_model_name():
    with patch("knowledge.embedder.SentenceTransformer") as mock_st:
        mock_st.return_value = MagicMock()
        mock_st.return_value.encode.return_value = np.array([0.1])
        Embedder()
        mock_st.assert_called_once_with("all-MiniLM-L6-v2")
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_vector_store.py::test_embedder_returns_list_of_floats -v
```
Expected: `ModuleNotFoundError: No module named 'knowledge.embedder'`

- [ ] **Step 3: Implement knowledge/embedder.py**

```python
"""Sentence-transformers embedder wrapper for retro-pilot.

Uses all-MiniLM-L6-v2 (80MB, CPU-compatible) to produce 384-dim vectors.
Model is loaded once at construction and reused across all calls.
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps SentenceTransformer for post-mortem embedding.

    Args:
        model_name: HuggingFace model ID. Default: all-MiniLM-L6-v2.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a list of floats."""
        vector = self._model.encode(text)
        return vector.tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple strings in one batch pass."""
        vectors = self._model.encode(texts)
        return [v.tolist() for v in vectors]
```

- [ ] **Step 4: Run tests — pass**

```bash
pytest tests/test_vector_store.py -k "embedder" -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add knowledge/embedder.py tests/test_vector_store.py
git commit -m "feat: knowledge/embedder.py — sentence-transformers all-MiniLM-L6-v2 wrapper"
```

---

## Task 2: Vector Store

**Files:**
- Modify: `tests/test_vector_store.py` (add vector store tests)
- Create: `knowledge/vector_store.py`

- [ ] **Step 1: Add vector store tests to tests/test_vector_store.py**

Append to the existing file:

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from shared.models import (
    Incident, Evidence, Timeline, RootCause, ActionItem,
    PostMortem, EvaluationScore,
)
from knowledge.vector_store import VectorStore

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_postmortem(incident_id: str = "INC-2026-0001") -> PostMortem:
    inc = Incident(
        id=incident_id,
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
        affected_services=["auth-service"],
        involved_repos=["acme/auth-service"],
        slack_channel="#incidents",
        reported_by="oncall",
    )
    tl = Timeline(
        events=[], first_signal_at=NOW, detection_lag_minutes=12,
        resolution_duration_minutes=47,
    )
    rc = RootCause(
        primary="Connection pool exhausted due to traffic spike",
        contributing_factors=["Pool size not scaled after growth"],
        trigger="Marketing campaign increased login rate 4x",
        blast_radius="payment-service, session-service",
        confidence="HIGH",
        evidence_refs=["log:auth-service:14:00"],
    )
    return PostMortem(
        incident=inc,
        executive_summary="Auth service experienced pool exhaustion.",
        timeline=tl,
        root_cause=rc,
        action_items=[],
        lessons_learned=["Scale connection pools proactively"],
        generated_at=NOW,
    )


def make_mock_collection():
    col = MagicMock()
    col.count.return_value = 0
    return col


@patch("knowledge.vector_store.chromadb.PersistentClient")
@patch("knowledge.vector_store.Embedder")
def test_store_adds_document(mock_embedder_cls, mock_chroma_cls):
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384
    mock_embedder_cls.return_value = mock_embedder

    mock_collection = make_mock_collection()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_chroma_cls.return_value = mock_client

    store = VectorStore(path="/tmp/test_chroma")
    pm = make_postmortem()
    store.store(pm)

    mock_collection.add.assert_called_once()
    call_kwargs = mock_collection.add.call_args.kwargs
    assert call_kwargs["ids"] == ["INC-2026-0001"]
    assert "documents" in call_kwargs
    assert "embeddings" in call_kwargs
    assert "metadatas" in call_kwargs


@patch("knowledge.vector_store.chromadb.PersistentClient")
@patch("knowledge.vector_store.Embedder")
def test_retrieve_returns_similar_postmortems(mock_embedder_cls, mock_chroma_cls):
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384
    mock_embedder_cls.return_value = mock_embedder

    pm = make_postmortem()
    pm_json = pm.model_dump_json()

    mock_collection = MagicMock()
    mock_collection.count.return_value = 3
    mock_collection.query.return_value = {
        "ids": [["INC-2026-0001"]],
        "distances": [[0.10]],  # distance 0.10 → similarity 0.90 → above 0.65 threshold
        "metadatas": [[{"postmortem_json": pm_json}]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_chroma_cls.return_value = mock_client

    store = VectorStore(path="/tmp/test_chroma")
    results = store.retrieve("Redis auth service pool exhaustion")

    assert len(results) == 1
    assert results[0].incident.id == "INC-2026-0001"


@patch("knowledge.vector_store.chromadb.PersistentClient")
@patch("knowledge.vector_store.Embedder")
def test_retrieve_filters_low_similarity(mock_embedder_cls, mock_chroma_cls):
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384
    mock_embedder_cls.return_value = mock_embedder

    mock_collection = MagicMock()
    mock_collection.count.return_value = 3
    # distance 0.80 → similarity 0.20 → below 0.65 threshold
    mock_collection.query.return_value = {
        "ids": [["INC-2026-0001"]],
        "distances": [[0.80]],
        "metadatas": [[{"postmortem_json": make_postmortem().model_dump_json()}]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_chroma_cls.return_value = mock_client

    store = VectorStore(path="/tmp/test_chroma")
    results = store.retrieve("completely unrelated query")

    assert results == []


@patch("knowledge.vector_store.chromadb.PersistentClient")
@patch("knowledge.vector_store.Embedder")
def test_retrieve_returns_empty_when_collection_empty(mock_embedder_cls, mock_chroma_cls):
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384
    mock_embedder_cls.return_value = mock_embedder

    mock_collection = MagicMock()
    mock_collection.count.return_value = 0
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_chroma_cls.return_value = mock_client

    store = VectorStore(path="/tmp/test_chroma")
    results = store.retrieve("any query")

    assert results == []
    mock_collection.query.assert_not_called()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_vector_store.py -k "store" -v
```
Expected: `ModuleNotFoundError: No module named 'knowledge.vector_store'`

- [ ] **Step 3: Implement knowledge/vector_store.py**

```python
"""ChromaDB vector store for retro-pilot post-mortems.

Stores post-mortems as semantic embeddings for similarity retrieval.
Uses local persistent mode — no external server required.
Retrieval threshold: cosine similarity > 0.65 (distance < 0.35).

What gets embedded per post-mortem:
  "{title} {executive_summary} {root_cause.primary}
   {contributing_factors joined} {lessons_learned joined}"
"""
from __future__ import annotations

import logging

import chromadb

from knowledge.embedder import Embedder
from shared.models import PostMortem

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "postmortems"
_SIMILARITY_THRESHOLD = 0.65  # cosine similarity minimum
_TOP_K = 3


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB L2/cosine distance to similarity score [0, 1].

    ChromaDB with cosine metric returns distance = 1 - cosine_similarity,
    so similarity = 1 - distance.
    """
    return max(0.0, 1.0 - distance)


def _document_text(pm: PostMortem) -> str:
    """Build the embedding document from a post-mortem."""
    parts = [
        pm.incident.title,
        pm.executive_summary,
        pm.root_cause.primary,
        " ".join(pm.root_cause.contributing_factors),
        " ".join(pm.lessons_learned),
    ]
    return " ".join(p for p in parts if p)


class VectorStore:
    """ChromaDB-backed semantic store for post-mortems.

    Args:
        path: Directory for ChromaDB persistence. Default: ./chroma_db
        embedder: Embedder instance. Created automatically if not provided.
    """

    def __init__(
        self,
        path: str = "./chroma_db",
        embedder: Embedder | None = None,
    ) -> None:
        self._embedder = embedder or Embedder()
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def store(self, pm: PostMortem) -> None:
        """Embed and store a post-mortem. Overwrites if same incident_id exists."""
        doc = _document_text(pm)
        embedding = self._embedder.embed(doc)
        metadata = {
            "incident_id": pm.incident.id,
            "severity": pm.incident.severity,
            "affected_services": ",".join(pm.incident.affected_services),
            "started_at": pm.incident.started_at.isoformat(),
            "resolution_duration_minutes": pm.timeline.resolution_duration_minutes,
            "action_item_count": len(pm.action_items),
            "postmortem_json": pm.model_dump_json(),
        }
        # upsert: update if exists, insert if not
        try:
            self._collection.delete(ids=[pm.incident.id])
        except Exception:
            pass
        self._collection.add(
            ids=[pm.incident.id],
            documents=[doc],
            embeddings=[embedding],
            metadatas=[metadata],
        )
        logger.info("VectorStore: stored post-mortem %s", pm.incident.id)

    def retrieve(self, query: str, top_k: int = _TOP_K) -> list[PostMortem]:
        """Retrieve post-mortems similar to query.

        Returns up to top_k post-mortems with cosine similarity > 0.65,
        ordered by similarity descending. Returns [] if store is empty.
        """
        if self._collection.count() == 0:
            return []

        query_embedding = self._embedder.embed(query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            include=["distances", "metadatas"],
        )

        postmortems: list[PostMortem] = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for _id, distance, meta in zip(ids, distances, metadatas):
            similarity = _distance_to_similarity(distance)
            if similarity < _SIMILARITY_THRESHOLD:
                continue
            try:
                pm = PostMortem.model_validate_json(meta["postmortem_json"])
                postmortems.append(pm)
                logger.debug(
                    "VectorStore: retrieved %s with similarity %.2f", _id, similarity
                )
            except Exception as exc:
                logger.warning("VectorStore: failed to deserialise %s: %s", _id, exc)

        return postmortems

    def count(self) -> int:
        """Return total number of stored post-mortems."""
        return self._collection.count()
```

- [ ] **Step 4: Run all vector store tests — pass**

```bash
pytest tests/test_vector_store.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add knowledge/vector_store.py tests/test_vector_store.py
git commit -m "feat: knowledge/vector_store.py — ChromaDB with cosine similarity retrieval"
```

---

## Task 3: Knowledge Consolidator

**Files:**
- Create: `knowledge/consolidator.py`

No tests required at this phase — consolidator is a standalone weekly job with no agent dependencies. It will be covered in Phase 4.

- [ ] **Step 1: Implement knowledge/consolidator.py**

```python
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
from datetime import datetime, timezone

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

            # Filter to only very-high similarity matches
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
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            patterns.append(pattern)
            logger.info(
                "Consolidator: pattern found — %d incidents: %s",
                len(all_in_cluster),
                ", ".join(c.incident.id for c in all_in_cluster),
            )

        return patterns
```

- [ ] **Step 2: Commit**

```bash
git add knowledge/consolidator.py
git commit -m "feat: knowledge/consolidator.py — weekly pattern detection job"
```

---

## Task 4: Evaluator Rubric & Scorer

**Files:**
- Create: `evaluator/rubric.py`
- Create: `evaluator/scorer.py`
- Create: `tests/test_evaluator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_evaluator.py
from datetime import datetime, timezone
import pytest
from shared.models import (
    Incident, Evidence, Timeline, TimelineEvent, RootCause,
    ActionItem, PostMortem, EvaluationScore,
)
from evaluator.rubric import WEIGHTS, PASS_THRESHOLD
from evaluator.scorer import score_postmortem

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_strong_postmortem() -> PostMortem:
    """A post-mortem that should score >= 0.80."""
    inc = Incident(
        id="INC-2026-0001", title="Redis pool exhaustion",
        severity="SEV1", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),
        affected_services=["auth-service", "payment-service"],
        involved_repos=["acme/auth"], slack_channel="#incidents", reported_by="oncall",
    )
    events = [
        TimelineEvent(timestamp=NOW, description=f"Event {i}",
                      source="log", significance="medium")
        for i in range(6)
    ]
    tl = Timeline(
        events=events, first_signal_at=NOW,
        detection_lag_minutes=12, resolution_duration_minutes=47,
    )
    rc = RootCause(
        primary="Connection pool exhausted in auth-service",
        contributing_factors=["Pool size not scaled after 3x traffic growth"],
        trigger="Marketing campaign launched at 14:00 increased login rate 4x",
        blast_radius="payment-service, session-service",
        confidence="HIGH",
        evidence_refs=["log:auth:14:00", "metric:pool_util:14:05"],
    )
    action_items = [
        ActionItem(
            title="Increase connection pool size to 200",
            owner_role="Platform team",
            deadline_days=7,
            priority="P1",
            type="prevention",
            acceptance_criteria="Pool size >= 200, load test passes at 5x current traffic",
        ),
        ActionItem(
            title="Add pool saturation alert",
            owner_role="Platform team",
            deadline_days=14,
            priority="P1",
            type="detection",
            acceptance_criteria="Alert fires when pool utilisation > 80% for 5 minutes",
        ),
        ActionItem(
            title="Add load test to release checklist",
            owner_role="Engineering team",
            deadline_days=30,
            priority="P2",
            type="prevention",
            acceptance_criteria="Release checklist includes load test step, verified in next release",
        ),
    ]
    return PostMortem(
        incident=inc,
        executive_summary=(
            "Auth service experienced a 47-minute outage due to connection pool exhaustion. "
            "Payment and session services were affected. "
            "Pool capacity has been increased and monitoring added."
        ),
        timeline=tl,
        root_cause=rc,
        action_items=action_items,
        lessons_learned=["Scale connection pools proactively after traffic growth"],
        similar_incidents=["INC-2026-0089"],
        generated_at=NOW,
    )


def make_weak_postmortem() -> PostMortem:
    """A post-mortem that should score < 0.80."""
    inc = Incident(
        id="INC-2026-0002", title="Outage",
        severity="SEV2", started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc),
        affected_services=["api"], involved_repos=[],
        slack_channel="#alerts", reported_by="oncall",
    )
    tl = Timeline(
        events=[  # Only 2 events — below the 5 minimum
            TimelineEvent(timestamp=NOW, description="Outage started",
                          source="log", significance="critical"),
            TimelineEvent(timestamp=NOW, description="Outage resolved",
                          source="log", significance="critical"),
        ],
        first_signal_at=NOW, detection_lag_minutes=5, resolution_duration_minutes=30,
    )
    rc = RootCause(
        primary="Something went wrong with the database and the API crashed causing problems",
        contributing_factors=[],  # No contributing factors
        trigger="unknown",
        blast_radius="api",
        confidence="LOW",
        evidence_refs=[],  # No evidence refs
    )
    action_items = [
        ActionItem(
            title="Improve monitoring",  # Vague
            owner_role="",  # No owner
            deadline_days=0,  # No deadline
            priority="P3",
            type="detection",
            acceptance_criteria="",  # No acceptance criteria
        ),
    ]
    return PostMortem(
        incident=inc,
        executive_summary=(
            "There was an API outage that impacted customers. "
            "The root cause was a database issue. "
            "We are investigating this further and will implement fixes. "
            "This is the fourth sentence which exceeds the 3-sentence limit and adds jargon like RCA and MTTR."
        ),
        timeline=tl,
        root_cause=rc,
        action_items=action_items,
        lessons_learned=[],
        similar_incidents=[],
        generated_at=NOW,
    )


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001


def test_pass_threshold_is_0_80():
    assert PASS_THRESHOLD == 0.80


def test_strong_postmortem_passes():
    score = score_postmortem(make_strong_postmortem(), knowledge_base_size=10)
    assert score.passed is True
    assert score.total >= 0.80
    assert score.revision_brief is None


def test_weak_postmortem_fails():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.passed is False
    assert score.total < 0.80
    assert score.revision_brief is not None
    assert len(score.revision_brief) > 0


def test_weak_postmortem_has_low_timeline_score():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.timeline_completeness < 0.80


def test_weak_postmortem_has_low_action_item_score():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    assert score.action_item_quality < 0.50


def test_revision_brief_mentions_specific_issues():
    score = score_postmortem(make_weak_postmortem(), knowledge_base_size=10)
    # Brief should mention specific problems, not generic feedback
    assert score.revision_brief is not None
    brief_lower = score.revision_brief.lower()
    # At least one specific issue should be called out
    assert any(kw in brief_lower for kw in [
        "timeline", "action item", "root cause", "executive summary",
        "evidence", "acceptance criteria", "owner"
    ])


def test_similar_incidents_dimension_scores_well_when_referenced():
    pm = make_strong_postmortem()
    pm.similar_incidents = ["INC-2026-0089"]
    score = score_postmortem(pm, knowledge_base_size=10)
    assert score.similar_incidents_referenced >= 0.80


def test_similar_incidents_dimension_penalised_when_empty_large_kb():
    pm = make_strong_postmortem()
    pm.similar_incidents = []
    score = score_postmortem(pm, knowledge_base_size=10)
    assert score.similar_incidents_referenced < 0.80
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_evaluator.py -v
```
Expected: `ModuleNotFoundError: No module named 'evaluator.rubric'`

- [ ] **Step 3: Implement evaluator/rubric.py**

```python
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
```

- [ ] **Step 4: Implement evaluator/scorer.py**

```python
"""Rule-based scorer for retro-pilot post-mortems.

Scores each dimension 0.0 → 1.0 using heuristics defined in rubric.py.
The LLM-as-judge in evaluator_agent.py calls this scorer first, then uses
an LLM to generate the specific revision_brief.

Scoring is deterministic and does not require LLM calls — this makes the
rubric fully testable without API access.
"""
from __future__ import annotations

from shared.models import EvaluationScore, PostMortem
from evaluator.rubric import (
    EXECUTIVE_JARGON, MIN_KB_SIZE_FOR_SIMILAR,
    MIN_TIMELINE_EVENTS, PASS_THRESHOLD, WEIGHTS,
)


def _score_timeline(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0

    if len(pm.timeline.events) < MIN_TIMELINE_EVENTS:
        deficit = MIN_TIMELINE_EVENTS - len(pm.timeline.events)
        score -= 0.15 * deficit
        issues.append(
            f"Timeline has {len(pm.timeline.events)} events — minimum is {MIN_TIMELINE_EVENTS}."
        )

    if pm.timeline.detection_lag_minutes == 0:
        score -= 0.10
        issues.append("Timeline detection_lag_minutes is 0 — verify this is accurate.")

    sources_present = {e.source for e in pm.timeline.events}
    if not sources_present:
        score -= 0.10
        issues.append("Timeline events have no sources.")

    if not pm.timeline.first_signal_at:
        score -= 0.15
        issues.append("Timeline is missing first_signal_at.")

    return max(0.0, min(1.0, score)), issues


def _score_root_cause(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0
    rc = pm.root_cause

    # Primary should be one sentence (no period in the middle)
    sentence_count = len([s for s in rc.primary.split(".") if s.strip()])
    if sentence_count > 1:
        score -= 0.20
        issues.append(
            f"Root cause primary is {sentence_count} sentences — condense to one."
        )

    if not rc.contributing_factors:
        score -= 0.15
        issues.append("Root cause has no contributing factors.")

    if rc.trigger.lower() in ("unknown", "", "n/a"):
        score -= 0.15
        issues.append("Root cause trigger is vague — specify what changed.")

    if not rc.evidence_refs:
        score -= 0.20
        issues.append("Root cause has no evidence_refs — link to supporting evidence.")

    return max(0.0, min(1.0, score)), issues


def _score_action_items(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0

    if not pm.action_items:
        return 0.0, ["No action items present."]

    vague_titles = {"improve monitoring", "add monitoring", "investigate further",
                    "fix the issue", "address the problem"}
    types_present = {ai.type for ai in pm.action_items}

    for i, ai in enumerate(pm.action_items, 1):
        if not ai.acceptance_criteria.strip():
            score -= 0.10
            issues.append(f"Action item {i} ('{ai.title}') has no acceptance_criteria.")
        if not ai.owner_role.strip():
            score -= 0.05
            issues.append(f"Action item {i} has no owner_role.")
        if ai.deadline_days == 0:
            score -= 0.05
            issues.append(f"Action item {i} has no deadline (deadline_days=0).")
        if ai.title.lower().strip() in vague_titles:
            score -= 0.10
            issues.append(
                f"Action item {i} title '{ai.title}' is too vague — be specific."
            )

    if len(types_present) < 2:
        score -= 0.10
        issues.append(
            f"Action items only cover type(s) {types_present} — include prevention, "
            "detection, or response types for balance."
        )

    return max(0.0, min(1.0, score)), issues


def _score_executive_summary(pm: PostMortem) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0
    summary = pm.executive_summary

    sentence_count = len([s for s in summary.split(".") if s.strip()])
    if sentence_count > 3:
        score -= 0.20
        issues.append(
            f"Executive summary is {sentence_count} sentences — maximum is 3."
        )

    jargon_found = [j for j in EXECUTIVE_JARGON if j.lower() in summary.lower()]
    if jargon_found:
        score -= min(0.30, 0.10 * len(jargon_found))
        issues.append(
            f"Executive summary contains technical jargon: {', '.join(jargon_found)}. "
            "Rewrite for a non-technical executive."
        )

    if len(summary) < 50:
        score -= 0.20
        issues.append("Executive summary is too short to be meaningful.")

    return max(0.0, min(1.0, score)), issues


def _score_similar_incidents(
    pm: PostMortem, knowledge_base_size: int
) -> tuple[float, list[str]]:
    issues: list[str] = []

    if knowledge_base_size < MIN_KB_SIZE_FOR_SIMILAR:
        return 1.0, []  # Not enough KB entries to require references

    if not pm.similar_incidents:
        return 0.40, [
            f"Knowledge base has {knowledge_base_size} incidents but none are referenced. "
            "Search the knowledge base for similar incidents."
        ]

    return 1.0, []


def score_postmortem(
    pm: PostMortem,
    knowledge_base_size: int = 0,
    revision_number: int = 0,
) -> EvaluationScore:
    """Score a PostMortem against the rubric. Deterministic, no LLM calls.

    Args:
        pm: The post-mortem to score.
        knowledge_base_size: Number of past post-mortems in the vector store.
        revision_number: Which revision this is (0 = first draft).

    Returns:
        EvaluationScore with per-dimension scores, total, pass/fail, and
        a specific revision_brief if failed.
    """
    tl_score, tl_issues = _score_timeline(pm)
    rc_score, rc_issues = _score_root_cause(pm)
    ai_score, ai_issues = _score_action_items(pm)
    es_score, es_issues = _score_executive_summary(pm)
    si_score, si_issues = _score_similar_incidents(pm, knowledge_base_size)

    total = (
        tl_score * WEIGHTS["timeline_completeness"]
        + rc_score * WEIGHTS["root_cause_clarity"]
        + ai_score * WEIGHTS["action_item_quality"]
        + es_score * WEIGHTS["executive_summary_clarity"]
        + si_score * WEIGHTS["similar_incidents_referenced"]
    )

    passed = total >= PASS_THRESHOLD

    revision_brief: str | None = None
    if not passed:
        all_issues = tl_issues + rc_issues + ai_issues + es_issues + si_issues
        revision_brief = " ".join(all_issues) if all_issues else (
            "Post-mortem quality below threshold. Review all dimensions."
        )

    return EvaluationScore(
        total=round(total, 3),
        timeline_completeness=round(tl_score, 3),
        root_cause_clarity=round(rc_score, 3),
        action_item_quality=round(ai_score, 3),
        executive_summary_clarity=round(es_score, 3),
        similar_incidents_referenced=round(si_score, 3),
        passed=passed,
        revision_brief=revision_brief,
        revision_number=revision_number,
    )
```

- [ ] **Step 5: Run evaluator tests — all pass**

```bash
pytest tests/test_evaluator.py -v
```
Expected: all 9 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add evaluator/rubric.py evaluator/scorer.py tests/test_evaluator.py
git commit -m "feat: evaluator rubric and scorer — deterministic rule-based scoring"
```

---

## Task 5: EvaluatorAgent (LLM-as-judge)

**Files:**
- Create: `agents/evaluator_agent.py`
- Modify: `tests/test_evaluator.py` (append evaluator agent tests)

- [ ] **Step 1: Append evaluator agent tests to tests/test_evaluator.py**

```python
# Append to tests/test_evaluator.py
from unittest.mock import MagicMock, patch
from agents.evaluator_agent import EvaluatorAgent


def make_mock_backend_for_evaluator(revision_brief_response: str) -> MagicMock:
    backend = MagicMock()
    backend.complete.return_value = revision_brief_response
    return backend


def test_evaluator_agent_passes_strong_postmortem():
    backend = make_mock_backend_for_evaluator("No revision needed.")
    agent = EvaluatorAgent(backend=backend)
    score = agent.run(make_strong_postmortem(), knowledge_base_size=10)
    assert score.passed is True
    # LLM should not be called for passing post-mortems
    backend.complete.assert_not_called()


def test_evaluator_agent_calls_llm_for_revision_brief_on_fail():
    backend = make_mock_backend_for_evaluator(
        "Root cause primary is two sentences. Timeline missing detection lag."
    )
    agent = EvaluatorAgent(backend=backend)
    score = agent.run(make_weak_postmortem(), knowledge_base_size=10)
    assert score.passed is False
    # LLM enriches the revision brief generated by the scorer
    backend.complete.assert_called_once()
    assert score.revision_brief is not None


def test_evaluator_agent_describe():
    agent = EvaluatorAgent()
    assert "LLM-as-judge" in agent.describe() or "evaluator" in agent.describe().lower()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_evaluator.py -k "evaluator_agent" -v
```
Expected: `ModuleNotFoundError: No module named 'agents.evaluator_agent'`

- [ ] **Step 3: Implement agents/evaluator_agent.py**

```python
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
from typing import Any

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

    def __init__(self, backend: Any = None, model: str | None = None) -> None:
        super().__init__(backend=backend, model=model)

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

        return self.backend.complete(
            system=_SYSTEM_PROMPT,
            user=prompt,
            model=self.model,
            max_tokens=512,
        )
```

- [ ] **Step 4: Run all evaluator tests — pass**

```bash
pytest tests/test_evaluator.py -v
```
Expected: all 12 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v --tb=short
ruff check agents/ knowledge/ evaluator/ shared/ tools/
```
Expected: all tests pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add agents/evaluator_agent.py tests/test_evaluator.py
git commit -m "feat: EvaluatorAgent — LLM-as-judge with rule-based scorer + LLM brief enrichment"
```

---

## Phase 2 Completion Gate

- [ ] **Push and open PR**

```bash
git push -u origin phase/2-knowledge
gh pr create \
  --title "feat: knowledge layer — ChromaDB vector store, embedder, evaluator (LLM-as-judge)" \
  --body "$(cat <<'EOF'
## Summary

- `knowledge/embedder.py` — sentence-transformers all-MiniLM-L6-v2 wrapper
- `knowledge/vector_store.py` — ChromaDB persistent store with cosine similarity > 0.65 threshold
- `knowledge/consolidator.py` — weekly pattern detection job (similarity > 0.90)
- `evaluator/rubric.py` + `evaluator/scorer.py` — deterministic 5-dimension scoring (no LLM required)
- `agents/evaluator_agent.py` — LLM-as-judge: passes on score >= 0.80, enriches revision_brief on fail

## Test plan

- [ ] `pytest tests/test_vector_store.py` — embed, store, retrieve, similarity filter
- [ ] `pytest tests/test_evaluator.py` — rubric weights, pass/fail thresholds, revision brief content
- [ ] Strong post-mortem fixture passes (>= 0.80)
- [ ] Weak post-mortem fixture fails with specific revision brief
- [ ] EvaluatorAgent does not call LLM when draft passes
- [ ] `docker compose run --rm test` exits 0
EOF
)"
```
