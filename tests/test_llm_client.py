"""LLM client behaviour with a stub transport: no network, no keys."""

import json
from types import SimpleNamespace

import httpx
import openai
from pydantic import BaseModel, ConfigDict

from onlabel.llm.cache import ResponseCache
from onlabel.llm.client import LLMClient, strict_schema


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: str
    note: str | None


def _resp(content: str, pt: int = 100, ct: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )


class StubClient:
    """Pops queued responses; an Exception in the queue is raised instead."""

    def __init__(self, queue):
        self.queue, self.calls = list(queue), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _rate_limited():
    req = httpx.Request("POST", "https://example.invalid")
    return openai.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)


def _client(stubs: dict, chain, cache=None, offline=False):
    return LLMClient(chain, cache, offline=offline, client_factory=lambda spec: stubs.get(spec.provider))


def _ask(llm):
    return llm.complete_json(prompt_version="t1", system="s", user="u", schema=Answer, max_completion_tokens=50)


def test_strict_schema_closes_objects_and_requires_every_field():
    s = strict_schema(Answer)
    assert s["additionalProperties"] is False and set(s["required"]) == {"verdict", "note"}


def test_valid_answer_is_returned_and_cached(tmp_path):
    stub = StubClient([_resp(json.dumps({"verdict": "supported", "note": None}))])
    cache = ResponseCache(tmp_path)
    res = _ask(_client({"ollama": stub}, ["ollama/llama3.1-8b"], cache))
    assert res.data.verdict == "supported" and res.source == "live" and res.prompt_tokens == 100
    again = _ask(_client({"ollama": StubClient([])}, ["ollama/llama3.1-8b"], cache))
    assert again.source == "cache" and again.data.verdict == "supported"


def test_invalid_json_gets_exactly_one_repair():
    stub = StubClient([_resp("not json"), _resp(json.dumps({"verdict": "unsupported", "note": "x"}))])
    res = _ask(_client({"ollama": stub}, ["ollama/llama3.1-8b"]))
    assert res.data.verdict == "unsupported" and len(stub.calls) == 2
    assert stub.calls[1]["messages"][-1]["role"] == "user"  # the repair request


def test_rate_limit_falls_through_to_the_next_model():
    groq = StubClient([_rate_limited()])
    local = StubClient([_resp(json.dumps({"verdict": "supported", "note": None}))])
    res = _ask(_client({"groq": groq, "ollama": local}, ["groq/gpt-oss-120b", "ollama/llama3.1-8b"]))
    assert res.model_key == "ollama/llama3.1-8b"
    assert "RateLimitError" in res.attempts[0]["error"]


def test_missing_key_skips_and_nothing_left_returns_none():
    res = _ask(_client({}, ["groq/gpt-oss-120b"]))
    assert res.data is None and res.attempts == [{"model": "groq/gpt-oss-120b", "skipped": "no api key"}]


def test_request_over_the_per_minute_budget_is_never_sent():
    stub = StubClient([])
    llm = _client({"groq": stub}, ["groq/gpt-oss-120b"])
    res = llm.complete_json(prompt_version="t1", system="s" * 30_000, user="u", schema=Answer,
                            max_completion_tokens=500)
    assert res.data is None and stub.calls == []
    assert res.attempts[0]["skipped"] == "request exceeds per-minute budget"


def test_gpt_oss_gets_low_reasoning_effort_and_no_temperature_drift():
    stub = StubClient([_resp(json.dumps({"verdict": "supported", "note": None}))])
    _ask(_client({"groq": stub}, ["groq/gpt-oss-120b"]))
    assert stub.calls[0]["reasoning_effort"] == "low" and stub.calls[0]["temperature"] == 0


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 1))
        self.t += s


def _ok():
    # Realistic usage: the ledger settles to it, so two calls fill most of 7,040 and a third waits.
    return _resp(json.dumps({"verdict": "supported", "note": None}), pt=2_300, ct=700)


def _big_ask(llm):
    # 8,000 chars -> 2,667 estimated prompt tokens + 700 completion = 3,367 per request:
    # two fit under 7,040 (8K TPM x 0.88 headroom), a third does not.
    return llm.complete_json(prompt_version="t1", system="s" * 2_000, user="u" * 6_000, schema=Answer,
                             max_completion_tokens=700)


def test_busy_model_is_skipped_for_the_next_one_in_the_live_api():
    from onlabel.llm.client import MinuteBudget

    clock = FakeClock()
    groq, local = StubClient([_ok(), _ok()]), StubClient([_ok()])
    llm = LLMClient(["groq/gpt-oss-120b", "ollama/llama3.1-8b"], budget=MinuteBudget(clock),
                    client_factory=lambda spec: {"groq": groq, "ollama": local}[spec.provider])
    assert _big_ask(llm).model_key == "groq/gpt-oss-120b"
    assert _big_ask(llm).model_key == "groq/gpt-oss-120b"
    third = _big_ask(llm)
    assert third.model_key == "ollama/llama3.1-8b"
    assert third.attempts[0]["skipped"].startswith("per-minute budget in use")
    assert len(groq.calls) == 2  # the busy model never received a request it would 429


def test_eval_mode_waits_for_the_budget_instead_of_switching_models():
    from onlabel.llm.client import MinuteBudget

    clock = FakeClock()
    groq = StubClient([_ok(), _ok(), _ok()])
    llm = LLMClient(["groq/gpt-oss-120b"], budget=MinuteBudget(clock), wait_for_budget=True,
                    sleep=clock.sleep, client_factory=lambda spec: groq)
    for _ in range(3):
        assert _big_ask(llm).model_key == "groq/gpt-oss-120b"
    assert clock.slept == [60.0]  # waited for the first request to leave the window


def test_429_is_waited_out_in_eval_mode_and_its_text_never_reaches_the_trace():
    clock = FakeClock()
    groq = StubClient([_rate_limited(), _ok()])
    llm = LLMClient(["groq/gpt-oss-120b"], wait_for_budget=True, sleep=clock.sleep,
                    client_factory=lambda spec: groq)
    res = _ask(llm)
    assert res.data is not None and len(groq.calls) == 2 and clock.slept == [60.0]


def test_provider_error_text_is_not_exposed():
    res = _ask(_client({"groq": StubClient([_rate_limited()])}, ["groq/gpt-oss-120b"]))
    assert res.attempts[0]["error"] == "RateLimitError 429"
    assert "slow down" not in json.dumps(res.attempts)


def test_rejected_answer_moves_to_the_next_model_and_is_never_cached(tmp_path):
    groq = StubClient([_resp(json.dumps({"verdict": "", "note": None}))])
    local = StubClient([_resp(json.dumps({"verdict": "supported", "note": None}))])
    cache = ResponseCache(tmp_path)
    llm = LLMClient(["groq/gpt-oss-120b", "ollama/llama3.1-8b"], cache,
                    client_factory=lambda spec: {"groq": groq, "ollama": local}[spec.provider])
    res = llm.complete_json(prompt_version="t1", system="s", user="u", schema=Answer, max_completion_tokens=50,
                            accept=lambda a: None if a.verdict else "empty verdict")
    assert res.model_key == "ollama/llama3.1-8b" and res.attempts[0]["rejected"] == "empty verdict"
    assert cache.writes == 1  # only the accepted answer


def test_a_cached_answer_that_is_now_rejected_is_asked_again(tmp_path):
    cache = ResponseCache(tmp_path)
    first = StubClient([_resp(json.dumps({"verdict": "", "note": None}))])
    _ask(_client({"ollama": first}, ["ollama/llama3.1-8b"], cache))  # caches the empty answer
    again = StubClient([_resp(json.dumps({"verdict": "supported", "note": None}))])
    res = _client({"ollama": again}, ["ollama/llama3.1-8b"], cache).complete_json(
        prompt_version="t1", system="s", user="u", schema=Answer, max_completion_tokens=50,
        accept=lambda a: None if a.verdict else "empty verdict")
    assert res.source == "live" and res.data.verdict == "supported"
    assert res.attempts[0]["rejected"].startswith("cached answer")


def test_offline_mode_never_calls_a_model(tmp_path):
    stub = StubClient([])
    res = _ask(_client({"ollama": stub}, ["ollama/llama3.1-8b"], ResponseCache(tmp_path), offline=True))
    assert res.data is None and stub.calls == []


def test_a_rate_limited_model_rests_until_the_provider_says():
    groq = StubClient([_rate_limited()])
    local = StubClient([_ok(), _ok()])
    llm = _client({"groq": groq, "ollama": local}, ["groq/gpt-oss-120b", "ollama/llama3.1-8b"])
    first, second = _ask(llm), _ask(llm)
    assert first.model_key == second.model_key == "ollama/llama3.1-8b"
    assert len(groq.calls) == 1  # not asked again while it rests
    assert second.attempts[0]["skipped"].startswith("rate limited (429), resting")
