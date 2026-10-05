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


def test_offline_mode_never_calls_a_model(tmp_path):
    stub = StubClient([])
    res = _ask(_client({"ollama": stub}, ["ollama/llama3.1-8b"], ResponseCache(tmp_path), offline=True))
    assert res.data is None and stub.calls == []
