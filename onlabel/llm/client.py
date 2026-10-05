"""One way to ask any registered model for JSON that matches a Pydantic schema.

Order for every request: committed cache -> each model in the chain -> give up and let the
caller fall back to a deterministic answer. A model is skipped when its key is missing or
the request would not fit its per-minute token budget (Groq counts prompt plus
max_completion_tokens against the limit up front and answers 413 if it is exceeded, which
no retry fixes). A response that fails validation gets exactly one repair attempt.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from onlabel.llm.cache import ResponseCache, cache_key
from onlabel.llm.registry import MODELS, ModelSpec, providers

TPM_HEADROOM = 0.88  # stay under the per-minute limit: estimates are rough


def estimate_tokens(text: str) -> int:
    return len(text) // 3 + 1  # deliberately pessimistic for English with numbers


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
    ) -> None:
        self.chain = [MODELS[k] for k in chain]
        self.cache = cache
        self.offline = offline  # cache only: what a keyless clone and CI run
        self.timeout_s = timeout_s
        self._factory = client_factory or self._openai_client
        self._clients: dict[str, Any] = {}

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
            if spec.tpm and estimate_tokens(system + user) + max_completion_tokens > spec.tpm * TPM_HEADROOM:
                result.attempts.append({"model": spec.key, "skipped": "request exceeds per-minute budget"})
                continue
            outcome = self._call(client, spec, system, user, schema, max_completion_tokens)
            result.attempts.append({k: v for k, v in outcome.items() if k != "data"})
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
            t = time.perf_counter()
            try:
                resp = client.chat.completions.create(**kwargs)
            except (openai.APIStatusError, openai.APIConnectionError, openai.APITimeoutError) as exc:
                out["latency_s"] += time.perf_counter() - t
                out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
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
