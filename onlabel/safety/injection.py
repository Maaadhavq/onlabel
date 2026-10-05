"""Is the copy trying to instruct the reviewer?

Promotional copy is untrusted input and the judge reads it. Three layers, cheapest first:

1. Reveal. Zero-width characters are removed, HTML comments, hidden elements and base64
   blobs are decoded or exposed, so text a person would not see is checked as well.
2. Patterns written for this application: "pre-approved by MLR", "mark this claim as
   supported", "ignore previous instructions", role labels, verdict fields. A general
   jailbreak classifier has no reason to find "MLR already approved this" suspicious.
3. Llama Prompt Guard 2 (86M parameters, served by Groq) over the revealed text, when a
   key is set. Its score is a probability; 0.5 and above counts.

A finding does not stop the review: the copy is still checked claim by claim. It adds a
document check, and the reviewer traces no claim from that copy, because an approval the
copy asked for is not an approval.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

PROMPT_GUARD_THRESHOLD = 0.5
WINDOW_CHARS = 1800  # about 512 tokens, Prompt Guard 2's context
EXCERPT_CHARS = 160

_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
_HIDDEN_ELEMENT = re.compile(
    r"<(\w+)[^>]*style\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0"
    r"|color\s*:\s*(?:#fff\b|#ffffff\b|white\b))[^\"']*[\"'][^>]*>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL)
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")

PATTERNS: list[tuple[str, re.Pattern]] = [(why, re.compile(rx, re.IGNORECASE)) for why, rx in [
    ("asks the reader to ignore its instructions",
     (r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|"
      r"system|original)?\s*(?:instructions?|rules|guidelines|prompts?)\b")),
    ("asks the reader to ignore its instructions (not in English)",
     r"\b(?:ignorez|ignora|ignoriere|ignorate)\b.{0,40}\b(?:instructions?|instrucciones|anweisungen|istruzioni)\b"),
    ("asks for a verdict",
     (r"\b(?:mark|label|classify|rate|treat|flag|score|return|consider)\b(?:\s+[\w-]+){0,4}?\s*(?:as|=|:)\s*['\"]?"
      r"(?:supported|approved|compliant|accurate|on-label|traced|verified)\b"
      r"|\bapprove\s+(?:this|these|all|every|each|the)\b")),
    ("imitates the reviewer's own prompt tags",
     r"<\s*/?\s*(?:claim|label_excerpts|excerpt|copy)\b[^>]*>"),
    ("claims an approval the reviewer has not given",
     (r"\bpre-?approved\b|\b(?:mlr|medical|legal|regulatory|compliance)(?:\s+team|\s+review(?:ers?)?)?\s+(?:has\s+|have\s+)?"
      r"(?:already\s+)?(?:approved|cleared|signed off on)\b|\balready\s+(?:been\s+)?(?:approved|cleared|reviewed)\s+by\s+"
      r"(?:mlr|legal|medical|regulatory|compliance)\b")),
    ("speaks as the system or the assistant",
     r"(?:^|\n)\s*(?:system|assistant|developer)\s*:|<\s*/?\s*(?:system|assistant|instructions?)\s*>|\[/?(?:system|inst)\]"),
    ("addresses the reviewer or the model",
     (r"\b(?:note|message|instructions?|reminder)\s+(?:to|for)\s+(?:the\s+)?(?:reviewer|ai|model|assistant|llm|checker|"
      r"system|grader|judge)\b")),
    ("dictates the output",
     (r"\b(?:verdict|output|respond|answer|reply)\s*(?:must be|should be|is|=|:|with)\s*['\"]?(?:supported|approved)\b"
      r"|\"verdict\"\s*:")),
    ("asks the reviewer not to flag", r"\bdo\s+not\s+(?:flag|report|mention|check|review)\b"),
    ("reassigns the reader's role", r"\byou\s+are\s+now\b|\bact\s+as\s+(?:a|an|the)\b|\bnew\s+instructions?\b"),
]]


@dataclass
class Finding:
    source: str  # "hidden" | "pattern" | "prompt_guard"
    why: str
    excerpt: str
    flags: bool = True  # False: worth showing, not enough on its own (a stray zero-width space)


@dataclass
class InjectionReport:
    flagged: bool
    findings: list[Finding] = field(default_factory=list)
    prompt_guard: float | None = None  # highest window probability; None when not run
    revealed: str = ""

    def to_dict(self) -> dict:
        return {"flagged": self.flagged, "findings": [asdict(f) for f in self.findings],
                "prompt_guard": self.prompt_guard}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1] + "…"


def _decoded(blob: str) -> str | None:
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in text)
    return text if text and printable / len(text) > 0.95 and " " in text else None


def reveal(text: str) -> tuple[str, list[Finding]]:
    """The copy as the checks read it: invisible parts made visible, encoded parts decoded."""
    findings: list[Finding] = []
    n_zero = len(_ZERO_WIDTH.findall(text))
    revealed = _ZERO_WIDTH.sub("", text)
    if n_zero:
        # Pasted web copy often carries a stray one, so they are removed (which also rejoins
        # a word split to dodge the patterns) and noted; the patterns below decide.
        findings.append(Finding("hidden", f"{n_zero} zero-width character{'s' if n_zero > 1 else ''} removed",
                                "", flags=False))
    extra: list[str] = []
    for m in _HTML_COMMENT.finditer(revealed):
        body = m.group(1).strip()
        if body and not body.startswith(("[if", "[endif")):  # Outlook conditionals in email templates
            findings.append(Finding("hidden", "an HTML comment carries text", _clip(m.group(1))))
            extra.append(m.group(1))
    for m in _HIDDEN_ELEMENT.finditer(revealed):
        if m.group(2).strip():
            findings.append(Finding("hidden", "text styled to be invisible", _clip(m.group(2))))
            extra.append(m.group(2))
    for m in _BASE64.finditer(revealed):
        plain = _decoded(m.group(0))
        if plain:
            findings.append(Finding("hidden", "base64-encoded text", _clip(plain)))
            extra.append(plain)
    return "\n".join([revealed, *extra]), findings


def windows(text: str, size: int = WINDOW_CHARS) -> list[str]:
    step = size * 3 // 4
    return [text[i : i + size] for i in range(0, max(1, len(text) - size // 4), step)] or [text]


def scan(text: str, prompt_guard: Callable[[str], float | None] | None = None) -> InjectionReport:
    revealed, findings = reveal(text)
    for why, rx in PATTERNS:
        m = rx.search(revealed)
        if m:
            lo, hi = max(0, m.start() - 40), min(len(revealed), m.end() + 40)
            findings.append(Finding("pattern", why, _clip(revealed[lo:hi])))
    score = None
    if prompt_guard is not None:
        scores = [s for s in (prompt_guard(w) for w in windows(revealed)) if s is not None]
        if scores:
            score = round(max(scores), 4)
            if score >= PROMPT_GUARD_THRESHOLD:
                findings.append(Finding("prompt_guard", f"Prompt Guard 2 scored the copy {score:.2f} for injection", ""))
    # Hidden text counts on its own: copy shown to patients has no reason to hide words.
    return InjectionReport(any(f.flags for f in findings), findings, score, revealed)


def groq_prompt_guard(client, model_id: str, timeout_s: float = 10.0) -> Callable[[str], float | None]:
    """Prompt Guard 2 through Groq's chat endpoint: the reply is the injection probability."""

    def score(text: str) -> float | None:
        try:
            r = client.chat.completions.create(model=model_id, messages=[{"role": "user", "content": text}],
                                               max_completion_tokens=10, timeout=timeout_s)
            return float((r.choices[0].message.content or "").strip())
        except Exception:  # noqa: BLE001 - the classifier is an extra layer; its absence is reported, not fatal
            return None

    return score
