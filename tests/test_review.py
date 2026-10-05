"""Reviewer behaviour with a stub judge: routing and the event stream for a document."""

import json
from types import SimpleNamespace

from onlabel.data.chunk import section_chunks
from onlabel.data.parse_spl import parse_spl
from onlabel.llm.client import LLMClient
from onlabel.retrieval.bm25 import BM25
from onlabel.retrieval.index import LabelIndex
from onlabel.review import Reviewer
from tests.fixtures import SPL, HashEncoder


class _Judge:
    """Answers every judge call with 'unsupported' and records what it was shown."""

    def __init__(self):
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.prompts.append(kw["messages"][-1]["content"])
        body = {"reasoning": "r", "verdict": "unsupported", "violations": [], "evidence": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _reviewer(k=1):
    label = parse_spl(SPL)
    meta = {"labels": {"testadrug": {"set_id": label.set_id, "version": label.version, "products": ["TESTADRUG"],
                                     "generic": "testaglutide", "effective_time": label.effective_time}}}
    idx = LabelIndex.build(section_chunks(label, "testadrug", "testaglutide", max_words=40), HashEncoder(), meta=meta)
    judge = _Judge()
    llm = LLMClient(["ollama/llama3.1-8b"], client_factory=lambda spec: judge)
    return Reviewer(idx, HashEncoder(), llm, k=k), judge


def test_indication_claims_always_see_the_indications_section():
    rev, judge = _reviewer(k=1)
    out = rev.review_claim("Testadrug lowers body weight by 14.9 percent", ["testadrug"], kind="indication")
    sections = [r["section"] for r in out.retrieved]
    assert any(s.startswith("1 INDICATIONS") for s in sections)
    search = out.trace[0]
    assert search["routed_to"] == ["Indications and Usage"] and search["routed_added"] >= 1
    assert "INDICATIONS AND USAGE" in judge.prompts[0]


def test_safety_claims_see_the_boxed_warning():
    rev, _ = _reviewer(k=1)
    out = rev.review_claim("Testadrug is completely safe for everyone", ["testadrug"], kind="safety")
    assert any(r["section"].startswith("WARNING") for r in out.retrieved)


def test_unrouted_kinds_search_as_before():
    rev, _ = _reviewer(k=2)
    out = rev.review_claim("Testadrug lowers body weight", ["testadrug"], kind="other")
    assert out.trace[0]["routed_to"] == [] and len(out.retrieved) == 2


def test_a1c_finds_hba1c():
    bm = BM25.build(["HbA1c change from baseline was -1.8", "body weight change"])
    assert bm.scores("It lowers A1C")[0] > 0


def test_document_review_emits_every_stage_in_order():
    rev, _ = _reviewer(k=2)
    events = []
    rev.review_document("TESTADRUG lowers body weight in adults with obesity. It is safe for everyone.",
                        None, lambda e, d: events.append((e, d)))
    names = [e for e, _ in events]
    assert names[0] == "start" and names[1] == "claims" and names[-2:] == ["document", "done"]
    assert names.count("claim") == len(events[1][1]["claims"]) > 0
    risk = events[-2][1]["checks"][0]
    assert risk["title"] == "Risk information missing"


def test_document_naming_no_indexed_drug_is_an_error():
    rev, _ = _reviewer()
    events = []
    rev.review_document("Some other drug works wonders for everyone.", None, lambda e, d: events.append((e, d)))
    assert events == [("error", {"message": "No indexed drug is named in the copy. Pick the label to check against.",
                                 "code": "no_label"})]
