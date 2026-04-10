"""Tests for POST /postmortems review API routes."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo.app as app_module


FIXTURES_DIR = Path(__file__).parent.parent / "demo"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with file paths redirected to tmp_path."""
    src_pms = FIXTURES_DIR / "mock_postmortems.json"
    dest_pms = tmp_path / "mock_postmortems.json"
    shutil.copy(src_pms, dest_pms)
    # Start with empty reviews (no pre-seeded entries)
    dest_reviews = tmp_path / "reviews.json"
    monkeypatch.setattr(app_module, "MOCK_POSTMORTEMS_FILE", dest_pms)
    monkeypatch.setattr(app_module, "REVIEWS_FILE", dest_reviews)
    return TestClient(app_module.app)


@pytest.fixture()
def client_with_seed(tmp_path, monkeypatch):
    """TestClient with pre-seeded reviews.json."""
    src_pms = FIXTURES_DIR / "mock_postmortems.json"
    dest_pms = tmp_path / "mock_postmortems.json"
    shutil.copy(src_pms, dest_pms)
    src_reviews = FIXTURES_DIR / "reviews.json"
    dest_reviews = tmp_path / "reviews.json"
    shutil.copy(src_reviews, dest_reviews)
    monkeypatch.setattr(app_module, "MOCK_POSTMORTEMS_FILE", dest_pms)
    monkeypatch.setattr(app_module, "REVIEWS_FILE", dest_reviews)
    return TestClient(app_module.app)


def test_list_returns_all_three(client):
    resp = client.get("/postmortems")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3


def test_list_status_filter_draft(client):
    resp = client.get("/postmortems?status=draft")
    assert resp.status_code == 200
    data = resp.json()
    assert all(pm["status"] == "draft" for pm in data)
    assert len(data) == 3  # no reviews seeded → all draft


def test_list_status_filter_approved(client_with_seed):
    resp = client_with_seed.get("/postmortems?status=approved")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "INC-2026-0156"


def test_list_severity_filter_sev1(client):
    resp = client.get("/postmortems?severity=SEV1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "INC-2026-0142"


def test_list_card_fields(client):
    resp = client.get("/postmortems")
    assert resp.status_code == 200
    pm = resp.json()[0]
    for field in ("id", "title", "severity", "started_at", "evaluator_total",
                  "status", "last_reviewer", "last_reviewed_at"):
        assert field in pm, f"Missing field: {field}"


def test_review_approve_persists(client):
    resp = client.post("/postmortems/INC-2026-0142/review", json={
        "action": "approve",
        "reviewer": "Carol",
        "comment": "LGTM",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Verify it appears in the list as approved
    list_resp = client.get("/postmortems?status=approved")
    ids = [pm["id"] for pm in list_resp.json()]
    assert "INC-2026-0142" in ids


def test_review_double_approve_idempotent(client):
    """Two approve actions: history accumulates but derived status stays 'approved'."""
    for _ in range(2):
        resp = client.post("/postmortems/INC-2026-0142/review", json={
            "action": "approve",
            "reviewer": "Carol",
            "comment": None,
        })
        assert resp.status_code == 200
    detail_resp = client.get("/postmortems/INC-2026-0142")
    data = detail_resp.json()
    assert len(data["review_history"]) == 2
    assert data["status"] == "approved"


def test_review_missing_reviewer_returns_422(client):
    resp = client.post("/postmortems/INC-2026-0142/review", json={
        "action": "approve",
        "reviewer": "",
        "comment": None,
    })
    assert resp.status_code == 422


def test_review_request_changes_without_comment_returns_422(client):
    resp = client.post("/postmortems/INC-2026-0142/review", json={
        "action": "request_changes",
        "reviewer": "Carol",
        "comment": None,
    })
    assert resp.status_code == 422


def test_review_unknown_id_returns_404(client):
    resp = client.post("/postmortems/INC-DOES-NOT-EXIST/review", json={
        "action": "approve",
        "reviewer": "Carol",
        "comment": None,
    })
    assert resp.status_code == 404


def test_detail_returns_review_history(client_with_seed):
    resp = client_with_seed.get("/postmortems/INC-2026-0156")
    assert resp.status_code == 200
    data = resp.json()
    assert "review_history" in data
    assert len(data["review_history"]) >= 1
    assert data["review_history"][0]["action"] == "approve"


def test_detail_unknown_id_returns_404(client):
    resp = client.get("/postmortems/INC-DOES-NOT-EXIST")
    assert resp.status_code == 404
