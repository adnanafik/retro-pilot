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
