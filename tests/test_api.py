"""API contract tests. No lifespan (so no model loading): the pipeline is stubbed."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from onlabel.api import main
from onlabel.data.chunk import section_chunks
from onlabel.data.parse_spl import parse_spl
from onlabel.retrieval.index import LabelIndex
from tests.fixtures import SPL, HashEncoder


class StubReviewer:
    def __init__(self):
        self.calls = []

    def review_claim(self, claim, labels):
        self.calls.append((claim, labels))
        return SimpleNamespace(to_dict=lambda: {"claim": claim, "status": "unsupported", "labels": labels})


@pytest.fixture
def client(monkeypatch):
    label = parse_spl(SPL)
    idx = LabelIndex.build(section_chunks(label, "testadrug", "testaglutide"), HashEncoder(),
                           meta={"labels": {"testadrug": {"set_id": label.set_id, "version": label.version}}})
    monkeypatch.setattr(main.state, "index", idx)
    monkeypatch.setattr(main.state, "reviewer", StubReviewer())
    monkeypatch.setattr(main.state, "error", None)
    main._recent.clear()
    return TestClient(main.app)  # not a context manager: lifespan (model loading) never runs


def test_health_reports_ready(client):
    body = client.get("/health").json()
    assert body["status"] == "ready" and body["chunks"] > 0


def test_review_round_trip(client):
    r = client.post("/reviews", json={"claim": "Testadrug cures obesity in everyone.", "labels": ["testadrug"]})
    assert r.status_code == 200 and r.json()["status"] == "unsupported"


@pytest.mark.parametrize(
    "payload",
    [
        {"claim": "short"},
        {"claim": "x" * 601},
        {"claim": "A long enough claim.", "unexpected": 1},
        {"claim": "A long enough claim.", "labels": ["a", "b", "c", "d", "e", "f"]},
    ],
)
def test_bad_requests_are_rejected(client, payload):
    assert client.post("/reviews", json=payload).status_code == 422


def test_unknown_label_is_named(client):
    r = client.post("/reviews", json={"claim": "A long enough claim.", "labels": ["nope"]})
    assert r.status_code == 422 and "nope" in r.json()["detail"]


def test_not_ready_is_503(client, monkeypatch):
    monkeypatch.setattr(main.state, "reviewer", None)
    assert client.post("/reviews", json={"claim": "A long enough claim."}).status_code == 503


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "REVIEWS_PER_HOUR", 2)
    codes = [client.post("/reviews", json={"claim": "A long enough claim."}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_cors_allows_only_configured_origins(client):
    ok = client.options("/reviews", headers={"Origin": "http://localhost:5180", "Access-Control-Request-Method": "POST"})
    bad = client.options("/reviews", headers={"Origin": "https://evil.onrender.com", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5180"
    assert "access-control-allow-origin" not in bad.headers
