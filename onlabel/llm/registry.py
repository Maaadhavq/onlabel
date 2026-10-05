"""Every model OnLabel can call, in one place.

Free-tier model IDs changed several times during 2026 (Groq dropped its free Llama chat
models; Cerebras dropped its free tier). Nothing outside this module names a model, and
`scripts/smoke_llm.py` checks each ID against the provider's live model list.

All chat models here are open-weight. Every provider speaks the OpenAI chat-completions
protocol, so one client covers all of them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_env: str | None  # None: no key needed (local Ollama)

    @property
    def api_key(self) -> str | None:
        if self.key_env is None:
            return "ollama"  # the SDK insists on a non-empty key; Ollama ignores it
        return os.environ.get(self.key_env) or None


@dataclass(frozen=True)
class ModelSpec:
    key: str  # stable name used in config, cache keys and reports
    provider: str
    model_id: str  # the provider's own ID
    family: str
    strict_json: bool = True  # response_format json_schema with strict=true
    tools: bool = True  # native function calling
    reasoning_effort: str | None = None  # gpt-oss only
    tpm: int | None = None  # free-tier tokens per minute; None = local, unmetered
    rpd: int | None = None  # free-tier requests per day
    preview: bool = False  # provider may withdraw it at short notice


def providers() -> dict[str, Provider]:
    return {
        "groq": Provider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        "gemini": Provider(
            "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"
        ),
        "ollama": Provider(
            "ollama", os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"), None
        ),
    }


MODELS: dict[str, ModelSpec] = {
    m.key: m
    for m in [
        # Hosted, free tier. Groq counts prompt + max_completion_tokens against TPM up front.
        ModelSpec("groq/gpt-oss-120b", "groq", "openai/gpt-oss-120b", "gpt-oss",
                  reasoning_effort="low", tpm=8_000, rpd=1_000),
        ModelSpec("groq/gpt-oss-20b", "groq", "openai/gpt-oss-20b", "gpt-oss",
                  reasoning_effort="low", tpm=8_000, rpd=1_000),
        ModelSpec("groq/qwen3.8-27b", "groq", "qwen/qwen3.8-27b", "qwen",
                  tpm=8_000, rpd=1_000, preview=True),
        ModelSpec("gemini/gemma-4-26b", "gemini", "gemma-4-26b-a4b-it", "gemma",
                  tools=False, tpm=15_000, rpd=14_400),
        # Local, for bulk evals: no quota, 8 GB GPU.
        ModelSpec("ollama/llama3.1-8b", "ollama", "llama3.1:8b", "llama"),
        ModelSpec("ollama/qwen3-8b", "ollama", "qwen3:8b", "qwen"),
        ModelSpec("ollama/gemma4-e4b", "ollama", "gemma4:e4b", "gemma"),
    ]
}

# Tried in order by the live demo; each model has its own quota, so the chain also
# multiplies daily capacity. After the last one the API serves cached samples.
DEMO_CHAIN = ["groq/gpt-oss-120b", "groq/gpt-oss-20b", "groq/qwen3.8-27b", "gemini/gemma-4-26b"]
LOCAL_EVAL = ["ollama/llama3.1-8b", "ollama/qwen3-8b", "ollama/gemma4-e4b"]

# Injection classifier (86M params), served free by Groq. Not a chat model.
PROMPT_GUARD = ModelSpec(
    "groq/prompt-guard-2-86m", "groq", "meta-llama/llama-prompt-guard-2-86m", "llama",
    strict_json=False, tools=False, preview=True,
)
