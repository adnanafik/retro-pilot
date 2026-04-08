from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np

from knowledge.embedder import Embedder
from knowledge.vector_store import VectorStore
from shared.models import (
    Incident,
    PostMortem,
    RootCause,
    Timeline,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)  # noqa: UP017


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
    assert all(isinstance(v, float) for row in result for v in row)


def test_embedder_uses_correct_model_name():
    with patch("knowledge.embedder.SentenceTransformer") as mock_st:
        mock_st.return_value = MagicMock()
        mock_st.return_value.encode.return_value = np.array([0.1])
        Embedder()
        mock_st.assert_called_once_with("all-MiniLM-L6-v2")


def make_postmortem(incident_id: str = "INC-2026-0001") -> PostMortem:
    inc = Incident(
        id=incident_id,
        title="Redis pool exhaustion",
        severity="SEV1",
        started_at=NOW,
        resolved_at=datetime(2026, 1, 15, 14, 47, tzinfo=timezone.utc),  # noqa: UP017
        affected_services=["auth-service"],
        involved_repos=["acme/auth-service"],
        slack_channel="#incidents",
        reported_by="oncall",
    )
    tl = Timeline(
        events=[],
        first_signal_at=NOW,
        detection_lag_minutes=12,
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
        "distances": [[0.10]],  # similarity 0.90 → above 0.65 threshold
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
