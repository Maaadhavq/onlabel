"""API contract tests. No lifespan (so no model loading): the pipeline is stubbed."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from onlabel.api import main
from onlabel.api.jobs import JobRunner
from onlabel.data.chunk import section_chunks
from onlabel.data.parse_spl import parse_spl
from onlabel.retrieval.index import LabelIndex
from tests.fixtures import SPL, HashEncoder


class StubReviewer:
    def __init__(self, index):
        self.calls = []
        self.index = index

    @property
    def labels_meta(self):
        return self.index.meta.get("labels", {})

    def review_claim(self, claim, labels):
        self.calls.append((claim, labels))
        return SimpleNamespace(to_dict=lambda: {"claim": claim, "status": "unsupported", "labels": labels})

    def review_document(self, text, labels, emit):
        emit("start", {"labels": [{"key": k} for k in (labels or ["testadrug"])]})
        emit("claims", {"claims": [{"n": 1, "text": text[:20]}]})
        emit("claim", {"n": 1, "review": {"claim": text[:20], "status": "supported", "evidence": [], "retrieved": []}})
        emit("done", {"n_claims": 1})


@pytest.fixture
def client(monkeypatch):
    label = parse_spl(SPL)
    idx = LabelIndex.build(section_chunks(label, "testadrug", "testaglutide"), HashEncoder(),
                           meta={"labels": {"testadrug": {"set_id": label.set_id, "version": label.version,
                                                          "products": ["TESTADRUG"], "generic": "testaglutide"}}})
    monkeypatch.setattr(main.state, "index", idx)
    monkeypatch.setattr(main.state, "reviewer", StubReviewer(idx))
    monkeypatch.setattr(main.state, "runner", JobRunner(main._run_document))
    monkeypatch.setattr(main.state, "error", None)
    main._recent.clear()
    main._today.update(day=0, count=0)
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
    assert client.post("/reviews", json={"claim": "Testadrug is a long enough claim."}).status_code == 503


def test_a_claim_without_labels_is_checked_against_the_drug_it_names(client):
    r = client.post("/reviews", json={"claim": "Testadrug cures obesity in everyone."})
    assert r.status_code == 200 and r.json()["labels"] == ["testadrug"]
    r = client.post("/reviews", json={"claim": "This medicine cures obesity in everyone."})
    assert r.status_code == 422  # never every label at once


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "REVIEWS_PER_HOUR", 2)
    codes = [client.post("/reviews", json={"claim": "Testadrug is a long enough claim."}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def _events(body: str) -> list[tuple[str, str]]:
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            out.append((fields["id"], fields["event"]))
    return out


def test_document_review_streams_events_in_order(client):
    r = client.post("/documents", json={"text": "TESTADRUG lowers weight in everyone who takes it.", "audience": "hcp"})
    assert r.status_code == 202
    job_id = r.json()["id"]
    with client.stream("GET", f"/documents/{job_id}/events") as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        assert "no-transform" in s.headers["cache-control"]
        events = _events("".join(s.iter_text()))
    assert [e for _, e in events] == ["start", "claims", "claim", "done"]
    snapshot = client.get(f"/documents/{job_id}").json()
    assert snapshot["done"] is True and len(snapshot["events"]) == 4


def test_stream_resumes_after_last_event_id(client):
    job_id = client.post("/documents", json={"text": "TESTADRUG lowers weight in everyone who takes it."}).json()["id"]
    with client.stream("GET", f"/documents/{job_id}/events") as s:
        "".join(s.iter_text())
    with client.stream("GET", f"/documents/{job_id}/events", headers={"Last-Event-ID": "1"}) as s:
        events = _events("".join(s.iter_text()))
    assert events[0] == ("2", "claim")


def test_document_requests_are_validated(client):
    assert client.post("/documents", json={"text": "too short"}).status_code == 422
    assert client.post("/documents", json={"text": "x" * 4001}).status_code == 422
    assert client.post("/documents", json={"text": "A long enough piece of copy.", "audience": "public"}).status_code == 422
    r = client.post("/documents", json={"text": "A long enough piece of copy.", "label": "nope"})
    assert r.status_code == 422 and "nope" in r.json()["detail"]
    assert client.get("/documents/unknown/events").status_code == 404


def test_rewrite_refuses_traced_or_unchecked_claims(client):
    job_id = client.post("/documents", json={"text": "TESTADRUG lowers weight in everyone who takes it."}).json()["id"]
    with client.stream("GET", f"/documents/{job_id}/events") as s:
        "".join(s.iter_text())
    assert client.post(f"/documents/{job_id}/claims/1/rewrite").status_code == 409  # already traced
    assert client.post(f"/documents/{job_id}/claims/9/rewrite").status_code == 409  # never checked


def test_limit_is_per_visitor_behind_the_proxy(client, monkeypatch):
    monkeypatch.setattr(main, "REVIEWS_PER_HOUR", 1)
    body = {"claim": "Testadrug is a long enough claim."}
    first = client.post("/reviews", json=body, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.1"})
    other = client.post("/reviews", json=body, headers={"X-Forwarded-For": "10.0.0.2"})
    spoofed = client.post("/reviews", json=body, headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
    assert [first.status_code, other.status_code, spoofed.status_code] == [200, 200, 429]


def test_daily_cap_covers_every_visitor(client, monkeypatch):
    monkeypatch.setattr(main, "CHECKS_PER_DAY", 2)
    main._today.update(day=0, count=0)
    codes = [client.post("/reviews", json={"claim": "Testadrug is a long enough claim."},
                         headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_cors_allows_only_configured_origins(client):
    ok = client.options("/reviews", headers={"Origin": "http://localhost:5180", "Access-Control-Request-Method": "POST"})
    bad = client.options("/reviews", headers={"Origin": "https://evil.onrender.com", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5180"
    assert "access-control-allow-origin" not in bad.headers
