"""ChromaDB vector store for retro-pilot post-mortems.

Stores post-mortems as semantic embeddings for similarity retrieval.
Uses local persistent mode — no external server required.
Retrieval threshold: cosine similarity > 0.65 (distance < 0.35).

What gets embedded per post-mortem:
  "{title} {executive_summary} {root_cause.primary}
   {contributing_factors joined} {lessons_learned joined}"
"""
from __future__ import annotations

import contextlib
import logging

import chromadb

from knowledge.embedder import Embedder
from shared.models import PostMortem

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "postmortems"
_SIMILARITY_THRESHOLD = 0.65  # cosine similarity minimum
_TOP_K = 3


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB cosine distance to similarity score [0, 1].

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
        """Embed and store a post-mortem. Upserts if same incident_id exists."""
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
        # upsert: delete then add so we always have the latest version
        # suppress NotFoundError only — first store of any ID is not an error
        with contextlib.suppress(chromadb.errors.NotFoundError):
            self._collection.delete(ids=[pm.incident.id])
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

        for _id, distance, meta in zip(ids, distances, metadatas, strict=False):
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
