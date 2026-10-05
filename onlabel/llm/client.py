"""One way to ask any registered model for JSON that matches a Pydantic schema.

Order for every request: committed cache -> each model in the chain -> give up and let the
caller fall back to a deterministic answer. A response that fails validation gets exactly
one repair attempt.

Free tiers meter tokens per minute, and Groq charges prompt plus the requested
max_completion_tokens at request time. The first keyed run hit a 429 on its third claim in
a minute, so the client keeps its own ledger of what each model has been charged in the
last 60 s. The live API skips to the next model when one is busy; eval runs
(`wait_for_budget=True`) wait instead, so a whole run uses the model under test. A request
bigger than a model's minute budget is never sent (Groq answers 413 and no retry fixes it).

Provider error text never leaves this module: Groq's 429 body names the organization, and
attempts are shown in the trace on the public page. Only the error type and status code
are kept.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from onlabel.llm.cache import ResponseCache, cache_key
from onlabel.llm.registry import MODELS, ModelSpec, providers

TPM_HEADROOM = 0.88  # stay under the per-minute limit: estimates are rough
WINDOW_S = 60.0


def estimate_tokens(text: str) -> int:
    return len(text) // 3 + 1  # deliberately pessimistic for English with numbers


class MinuteBudget:
    """Tokens charged to each model in the trailing 60 s, the way the provider counts them."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._spent: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[tuple[float, int]]:
        q = self._spent[key]
        while q and now - q[0][0] >= WINDOW_S:
            q.popleft()
        return q

    def wait_s(self, key: str, need: int, limit: int) -> float:
        """Seconds until `need` more tokens fit under `limit`; 0 if they fit now."""
        with self._lock:
            now = self.clock()
            q = self._trim(key, now)
            used = sum(t for _, t in q)
            if used + need <= limit:
                return 0.0
            freed = 0
            for ts, tokens in q:
                freed += tokens
                if used - freed + need <= limit:
                    return max(0.0, ts + WINDOW_S - now)
            return WINDOW_S

    def charge(self, key: str, tokens: int) -> None:
        with self._lock:
            self._spent[key].append((self.clock(), tokens))


def _public_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__} {status}" if status else type(exc).__name__


def _retry_after(exc: Exception) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None


@dataclass
class LLMResult:
    data: BaseModel | None
    model_key: str | None = None
    source: str = "none"  # "cache" | "live" | "none"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    attempts: list[dict] = field(default_factory=list)


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic's JSON schema, shaped for strict structured outputs: every object closed,
    every property required (optional fields must be declared nullable instead)."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items() if k not in ("default", "title")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(model.model_json_schema())


class LLMClient:
    def __init__(
        self,
        chain: list[str],
        cache: ResponseCache | None = None,
        *,
        offline: bool = False,
        timeout_s: float = 90,
        client_factory: Callable[[ModelSpec], Any] | None = None,
        budget: MinuteBudget | None = None,
        wait_for_budget: bool = False,
        max_wait_s: float = 65.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.chain = [MODELS[k] for k in chain]
        self.cache = cache
        self.offline = offline  # cache only: what a keyless clone and CI run
        self.timeout_s = timeout_s
        self._factory = client_factory or self._openai_client
        self._clients: dict[str, Any] = {}
        self.budget = budget or MinuteBudget()
        self.wait_for_budget = wait_for_budget
        self.max_wait_s = max_wait_s
        self._sleep = sleep

    def _openai_client(self, spec: ModelSpec) -> Any:
        prov = providers()[spec.provider]
        if prov.api_key is None:
            return None
        return OpenAI(api_key=prov.api_key, base_url=prov.base_url, max_retries=0, timeout=self.timeout_s)

    def _client(self, spec: ModelSpec) -> Any:
        if spec.provider not in self._clients:
            self._clients[spec.provider] = self._factory(spec)
        return self._clients[spec.provider]

    def complete_json(
        self,
        *,
        prompt_version: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_completion_tokens: int,
    ) -> LLMResult:
        result = LLMResult(data=None)
        for spec in self.chain:
            key = cache_key(spec.key, prompt_version, schema.__name__, system, user)
            if self.cache is not None:
                hit = self.cache.get(key)
                if hit is not None:
                    try:
                        result.data = schema.model_validate(hit["response"])
                    except ValidationError:
                        pass  # schema changed since the entry was written: treat as a miss
                    else:
                        usage = hit.get("usage", {})
                        result.model_key, result.source = spec.key, "cache"
                        result.prompt_tokens = usage.get("prompt_tokens", 0)
                        result.completion_tokens = usage.get("completion_tokens", 0)
                        return result
            if self.offline:
                result.attempts.append({"model": spec.key, "skipped": "offline"})
                continue
            client = self._client(spec)
            if client is None:
                result.attempts.append({"model": spec.key, "skipped": "no api key"})
                continue
            need = estimate_tokens(system + user) + max_completion_tokens
            limit = int(spec.tpm * TPM_HEADROOM) if spec.tpm else None
            if limit is not None and need > limit:
                result.attempts.append({"model": spec.key, "skipped": "request exceeds per-minute budget"})
                continue

            outcome: dict = {}
            for _ in range(2):  # a second pass only after waiting out a 429 in eval mode
                if limit is not None:
                    wait = self.budget.wait_s(spec.key, need, limit)
                    if wait > 0 and not (self.wait_for_budget and wait <= self.max_wait_s):
                        outcome = {"model": spec.key, "skipped": f"per-minute budget in use for {wait:.0f}s"}
                        break
                    if wait > 0:
                        self._sleep(wait)
                outcome = self._call(client, spec, system, user, schema, max_completion_tokens)
                retry = outcome.get("retry_after")
                if not (retry and self.wait_for_budget and retry <= self.max_wait_s):
                    break
                self._sleep(retry)
            result.attempts.append({k: v for k, v in outcome.items() if k not in ("data", "retry_after")})
            result.prompt_tokens += outcome.get("prompt_tokens", 0)
            result.completion_tokens += outcome.get("completion_tokens", 0)
            result.latency_s += outcome.get("latency_s", 0.0)
            if outcome.get("data") is not None:
                result.data, result.model_key, result.source = outcome["data"], spec.key, "live"
                if self.cache is not None:
                    self.cache.put(key, model_key=spec.key, prompt_version=prompt_version,
                                   schema_name=schema.__name__,
                                   response=outcome["data"].model_dump(mode="json"),
                                   usage={"prompt_tokens": outcome.get("prompt_tokens", 0),
                                          "completion_tokens": outcome.get("completion_tokens", 0)})
                return result
        return result

    def _call(self, client: Any, spec: ModelSpec, system: str, user: str,
              schema: type[BaseModel], max_completion_tokens: int) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        out: dict = {"model": spec.key, "prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0.0}
        for attempt in range(2):  # the second pass is the single repair attempt
            kwargs: dict[str, Any] = {
                "model": spec.model_id,
                "messages": messages,
                "temperature": 0,
                "max_completion_tokens": max_completion_tokens,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "schema": strict_schema(schema), "strict": True}},
            }
            if spec.reasoning_effort:
                kwargs["reasoning_effort"] = spec.reasoning_effort
            if spec.tpm:  # every request is charged, including the repair attempt
                sent = "".join(m["content"] for m in messages)
                self.budget.charge(spec.key, estimate_tokens(sent) + max_completion_tokens)
            t = time.perf_counter()
            try:
                resp = client.chat.completions.create(**kwargs)
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                out["latency_s"] += time.perf_counter() - t
                out["error"] = _public_error(exc)
                if getattr(exc, "status_code", None) == 429:
                    out["retry_after"] = _retry_after(exc) or WINDOW_S
                return out
            out["latency_s"] += time.perf_counter() - t
            if resp.usage:
                out["prompt_tokens"] += resp.usage.prompt_tokens or 0
                out["completion_tokens"] += resp.usage.completion_tokens or 0
            content = resp.choices[0].message.content or ""
            try:
                out["data"] = schema.model_validate(json.loads(content))
                out["repaired"] = attempt == 1
                return out
            except (json.JSONDecodeError, ValidationError) as exc:
                out["error"] = f"invalid output: {str(exc)[:160]}"
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": "That JSON did not match the schema: "
                     f"{str(exc)[:400]}. Reply with corrected JSON only."},
                ]
        return out
