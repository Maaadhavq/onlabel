import json
from types import SimpleNamespace

from onlabel.agent.document import (
    detect_labels,
    risk_information_check,
    sentence_claims,
    split_claims,
)
from onlabel.data.chunk import Chunk
from onlabel.llm.client import LLMClient

COPY = (
    "Your weight-loss journey starts here. Wegovy is approved for weight loss in children as young as 8. "
    "In clinical trials, adults lost an average of 14.9% of their body weight at 68 weeks. "
    "Ask your doctor if Wegovy is right for you."
)

META = {
    "wegovy": {"products": ["WEGOVY"], "generic": "semaglutide"},
    "ozempic": {"products": ["OZEMPIC"], "generic": "semaglutide"},
    "mounjaro": {"products": ["MOUNJARO", "MOUNJARO KWIKPEN"], "generic": "tirzepatide"},
}


def test_sentence_split_drops_calls_to_action_and_keeps_offsets():
    claims = sentence_claims(COPY)
    assert [c.text for c in claims][-1].startswith("In clinical trials")
    assert all(COPY[c.start : c.end] == c.text for c in claims)
    assert not any(c.text.startswith("Ask your doctor") for c in claims)


class _Stub:
    def __init__(self, payload):
        self.payload = payload
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))],
                               usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))


def _splitter(payload):
    return LLMClient(["ollama/llama3.1-8b"], client_factory=lambda spec: _Stub(payload))


def test_model_claims_are_located_in_the_copy_and_invented_ones_dropped():
    payload = {"claims": [
        {"text": "In clinical trials, adults lost an average of 14.9% of their body weight at 68 weeks.", "kind": "efficacy"},
        {"text": "Wegovy is approved for weight loss in children as young as 8.", "kind": "indication"},
        {"text": "Wegovy cures obesity forever.", "kind": "efficacy"},  # not in the copy
    ]}
    claims, res = split_claims(_splitter(payload), COPY)
    assert [c.n for c in claims] == [1, 2] and res.model_key == "ollama/llama3.1-8b"
    assert claims[0].text.startswith("Wegovy is approved")  # reading order, not model order
    assert all(COPY[c.start : c.end] == c.text and c.source == "model" for c in claims)


def test_an_empty_split_asks_the_next_model():
    empty, good = _Stub({"claims": []}), _Stub({"claims": [
        {"text": "Wegovy is approved for weight loss in children as young as 8.", "kind": "indication"}]})
    llm = LLMClient(["groq/qwen3.8-27b", "ollama/llama3.1-8b"],
                    client_factory=lambda spec: {"groq": empty, "ollama": good}[spec.provider])
    claims, res = split_claims(llm, COPY)
    assert [c.source for c in claims] == ["model"] and res.model_key == "ollama/llama3.1-8b"
    assert res.attempts[0]["rejected"] == "no claims in the answer"


def test_no_usable_model_answer_falls_back_to_sentences():
    claims, _ = split_claims(_splitter({"claims": [{"text": "not in the copy at all", "kind": "other"}]}), COPY)
    assert claims and all(c.source == "sentences" for c in claims)


def test_detect_labels_prefers_brands_and_flags_generic_ambiguity():
    assert detect_labels("Try Mounjaro KwikPen today", META) == (["mounjaro"], False)
    assert detect_labels("semaglutide helps", META) == (["ozempic", "wegovy"], True)
    assert detect_labels("no drug named here", META) == ([], False)


def test_a_brand_on_two_labels_is_ambiguous():
    meta = {**META, "rybelsus": {"products": ["OZEMPIC", "RYBELSUS"], "generic": "semaglutide"}}
    assert detect_labels("Ask about Ozempic", meta) == (["ozempic", "rybelsus"], True)


def _boxed() -> list[Chunk]:
    text = "- In rodents, semaglutide causes thyroid C-cell tumors. It is unknown whether WEGOVY causes them."
    return [Chunk("w:v19:0:0", "wegovy", "set", 19, "WEGOVY", "semaglutide", 0,
                  "WARNING: RISK OF THYROID C-CELL TUMORS", "34066-1", None, 0, len(text), 0, len(text), text)]


def test_missing_boxed_warning_is_flagged():
    found = risk_information_check(COPY, "wegovy", "WEGOVY", _boxed())
    assert found["ok"] is False and found["title"] == "Risk information missing"
    assert "WARNING: RISK OF THYROID C-CELL TUMORS" in found["detail"]
    assert found["evidence"]["quote"].startswith("In rodents")


def test_mentioning_the_warning_subject_passes_but_still_asks_for_review():
    found = risk_information_check(COPY + " Wegovy may cause thyroid tumors.", "wegovy", "WEGOVY", _boxed())
    assert found["ok"] is True and "thyroid" in found["detail"]


def test_no_boxed_warning_no_check():
    assert risk_information_check(COPY, "jardiance", "JARDIANCE", []) is None


def test_denying_the_warning_subject_is_flagged_as_minimized():
    found = risk_information_check(COPY + " Unlike insulin, Wegovy carries no risk of thyroid tumors.",
                                   "wegovy", "WEGOVY", _boxed())
    assert found["ok"] is False and found["title"] == "Boxed-warning risk is denied"
    assert found["denied"] == ["Unlike insulin, Wegovy carries no risk of thyroid tumors."]


def test_risk_language_with_conditions_or_instructions_is_not_a_denial():
    for line in ["It is not known whether Wegovy causes thyroid C-cell tumors in people.",
                 "Do not use Wegovy if you have had thyroid cancer.",
                 "Do not ignore thyroid symptoms such as a lump in your neck."]:
        found = risk_information_check(COPY + " " + line, "wegovy", "WEGOVY", _boxed())
        assert found["ok"] is True and found["denied"] == [], line
