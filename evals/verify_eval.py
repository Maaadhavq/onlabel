"""Claim-verification eval (Set B): the full reviewer, one model at a time.

    uv run python -m evals.verify_eval --model groq/gpt-oss-120b --split test
    uv run python -m evals.verify_eval --model ollama/llama3.1-8b --split all

Each claim goes through `Reviewer.review_claim` exactly as the API runs it (retrieval,
routing, judge, guards) against its own label, with the kind written on its card. The
model is the only one in its chain, so every verdict comes from the model under test; in
eval mode the client waits out per-minute limits instead of moving on. Answers land in the
committed cache (cache/llm), so a rerun reproduces the report without keys.

Scored twice from the same answers: with the guards (the status the reviewer shows) and
without them (the model's own verdict), which is the guard ablation at no extra cost.

The number that matters most is the false-approval rate: a claim built to be violative
that comes back traced. A faithful claim that is not traced costs a reviewer a look; a
violative claim that is traced is the failure the tool exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from onlabel.env import load_env

load_env()

from evals.common import cluster_bootstrap, load_claims, write_report
from onlabel.llm.cache import ResponseCache
from onlabel.llm.client import LLMClient
from onlabel.llm.registry import MODELS
from onlabel.models import BGE_SMALL_INT8
from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder
from onlabel.retrieval.index import LabelIndex
from onlabel.review import Reviewer

VERDICTS = ["supported", "needs_qualifier", "unsupported", "contradicted", "off_label", "needs_human_review"]
OPS = ["faithful", "drop_qualifier", "broaden", "inflate", "superiority", "absolute", "deny_risk",
       "contradict", "wrong_dose"]
TRANSIENT_RETRIES = 3


def run(model: str, claims: list[dict], timeout_s: float, offline: bool = False,
        earlier: dict[str, str] | None = None) -> tuple[list[dict], str | None]:
    """`offline` replays cached answers only (a guard change re-scored with no new model
    calls); a claim with no cached answer keeps the reason `earlier` recorded for it."""
    index = LabelIndex.load(Path("data/index"))
    encoder = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path, query_prefix=BGE_QUERY_PREFIX)
    llm = LLMClient([model], ResponseCache("cache/llm"), wait_for_budget=True, timeout_s=timeout_s, offline=offline)
    reviewer = Reviewer(index, encoder, llm)
    rows, stopped = [], None
    t0 = time.perf_counter()
    for i, c in enumerate(claims, 1):
        for attempt in range(TRANSIENT_RETRIES + 1):
            r = reviewer.review_claim(c["text"], [c["label"]], kind=c["kind"])
            if "no_llm_available" not in r.flags:
                break
            judge = next((s for s in r.trace if s["step"] == "judge"), {})
            errors = " ".join(str(a.get("error", a.get("skipped", ""))) for a in judge.get("attempts", []))
            # A 500 or a timeout passes; a quota or key problem does not, so stop there.
            if attempt == TRANSIENT_RETRIES or not any(s in errors for s in ("500", "502", "503", "Timeout")):
                break
            time.sleep(15 * (attempt + 1))
        unanswered = None
        if "no_llm_available" in r.flags:
            # Quota or key trouble ends the run (rerun later: the cache keeps what was done).
            # Anything else is the model's own failure to answer, which the reviewer turns into
            # human review; it is kept and counted.
            if any(s in errors for s in ("429", "401", "403", "no api key", "budget")):
                stopped = f"claim {i} ({c['id']}): no answer from {model}: {judge.get('attempts')}"
                break
            unanswered = (earlier or {}).get(c["id"]) if offline else None
            unanswered = unanswered or errors.strip() or "no answer"
        rows.append({
            "id": c["id"], "card": c["card"], "label": c["label"], "split": c["split"], "kind": c["kind"],
            "op": c["op"], "gold": c["gold"], "accept": c["accept"], "expected_violations": c["violations"],
            "text": c["text"], "status": r.status, "model_verdict": r.model_verdict, "violations": r.violations,
            "flags": r.flags, "quotes_kept": len(r.evidence), "reasoning": r.reasoning, "tokens": r.tokens,
            "latency_s": r.latency_s, "source": r.source, "unanswered": unanswered,
        })
        print(f"[{i:3}/{len(claims)}] {c['op']:14} gold {c['gold']:16} -> {r.status:18} "
              f"(model {r.model_verdict}) {r.source} {r.latency_s:.1f}s  {time.perf_counter() - t0:.0f}s total",
              flush=True)
    return rows, stopped


def outcome(row: dict, guards: bool) -> str:
    return row["status"] if guards else (row["model_verdict"] or "needs_human_review")


def rates(rows: list[dict], guards: bool) -> dict:
    faithful = [r for r in rows if r["op"] == "faithful"]
    bad = [r for r in rows if r["op"] != "faithful"]

    def traced(r: dict) -> bool:
        return outcome(r, guards) == "supported"

    def far(sample: list[dict]) -> float | None:
        b = [r for r in sample if r["op"] != "faithful"]
        return sum(traced(r) for r in b) / len(b) if b else None

    def recall(sample: list[dict]) -> float | None:
        f = [r for r in sample if r["op"] == "faithful"]
        return sum(traced(r) for r in f) / len(f) if f else None

    out = {
        "n": len(rows), "n_faithful": len(faithful), "n_violative": len(bad),
        "false_approvals": sum(traced(r) for r in bad),
        "false_approval_rate": round(far(rows), 3) if bad else None,
        "false_approval_ci": cluster_bootstrap(rows, far),
        "traced_faithful": sum(traced(r) for r in faithful),
        "supported_recall": round(recall(rows), 3) if faithful else None,
        "supported_recall_ci": cluster_bootstrap(rows, recall),
        "violative_named": round(sum(outcome(r, guards) in r["accept"] for r in bad) / len(bad), 3) if bad else None,
        "human_review": round(sum(outcome(r, guards) == "needs_human_review" for r in rows) / len(rows), 3) if rows else None,
    }
    tagged = [r for r in bad if r["expected_violations"]]
    out["violation_tag_match"] = (round(sum(bool(set(r["violations"]) & set(r["expected_violations"]))
                                            for r in tagged) / len(tagged), 3) if tagged else None)
    return out


def by_op(rows: list[dict]) -> dict:
    table = {}
    for op in OPS:
        sub = [r for r in rows if r["op"] == op]
        if sub:
            table[op] = {"n": len(sub), **{v: sum(r["status"] == v for r in sub) for v in VERDICTS},
                         "named": sum(r["status"] in r["accept"] for r in sub)}
    return table


def markdown(name: str, model: str, report: dict) -> str:
    intro = (f"Run `{name}`, {report['meta']['n_claims']} claims ({report['meta']['split']} split). "
             "Traced = the reviewer shows the claim as supported. Intervals are 95% cluster-bootstrap "
             "intervals over fact cards.")
    lines = [f"# Claim verification: {model}", "", intro, ""]
    lines += ["| | Guards on (what the reviewer shows) | Guards off (model verdict) |", "|---|---|---|"]
    on, off = report["overall"]["guards_on"], report["overall"]["guards_off"]

    def fmt(r: dict, key: str, ci: str | None = None) -> str:
        v = r.get(key)
        if v is None:
            return "n/a"
        s = f"{v:.2f}"
        if ci and r.get(ci):
            s += f" ({r[ci][0]:.2f}-{r[ci][1]:.2f})"
        return s

    lines.append(f"| False-approval rate (violative claims traced) | {fmt(on, 'false_approval_rate', 'false_approval_ci')} "
                 f"[{on['false_approvals']}/{on['n_violative']}] | {fmt(off, 'false_approval_rate', 'false_approval_ci')} "
                 f"[{off['false_approvals']}/{off['n_violative']}] |")
    lines.append(f"| Faithful claims traced | {fmt(on, 'supported_recall', 'supported_recall_ci')} "
                 f"[{on['traced_faithful']}/{on['n_faithful']}] | {fmt(off, 'supported_recall', 'supported_recall_ci')} "
                 f"[{off['traced_faithful']}/{off['n_faithful']}] |")
    lines.append(f"| Violative claims given an expected verdict | {fmt(on, 'violative_named')} | {fmt(off, 'violative_named')} |")
    lines.append(f"| Expected violation tag listed | {fmt(on, 'violation_tag_match')} | {fmt(off, 'violation_tag_match')} |")
    lines.append(f"| Sent to a human | {fmt(on, 'human_review')} | {fmt(off, 'human_review')} |")
    for split in ("dev", "test"):
        if split in report["by_split"]:
            s = report["by_split"][split]["guards_on"]
            lines.append(f"\n{split}: false approvals {s['false_approvals']}/{s['n_violative']}, "
                         f"faithful traced {s['traced_faithful']}/{s['n_faithful']} (guards on).")
    lines += ["", "## By construction (guards on)", "",
              "| Built as | n | supported | needs qualifier | unsupported | contradicted | off-label | human | expected verdict |",
              "|---|---|---|---|---|---|---|---|---|"]
    for op, t in report["by_op"].items():
        lines.append(f"| {op} | {t['n']} | {t['supported']} | {t['needs_qualifier']} | {t['unsupported']} | "
                     f"{t['contradicted']} | {t['off_label']} | {t['needs_human_review']} | {t['named']} |")
    rows = report["claims"]
    fa = [r for r in rows if r["op"] != "faithful" and r["status"] == "supported"]
    lines += ["", f"## False approvals ({len(fa)})", ""]
    lines += [f"- `{r['id']}` ({r['op']}): {r['text']}" for r in fa] or ["None."]
    caught = [r for r in rows if r["op"] != "faithful" and r["model_verdict"] == "supported" and r["status"] != "supported"]
    lines += ["", f"## Model said supported, the guards stopped it ({len(caught)})", ""]
    lines += [f"- `{r['id']}` ({r['op']}) -> {r['status']} [{', '.join(r['flags'])}]: {r['text']}" for r in caught] or ["None."]
    missed = [r for r in rows if r["op"] == "faithful" and r["status"] != "supported"]
    lines += ["", f"## Faithful claims not traced ({len(missed)})", ""]
    lines += [f"- `{r['id']}` -> {r['status']}{(' [' + ', '.join(r['flags']) + ']') if r['flags'] else ''}: {r['text']}"
              for r in missed] or ["None."]
    m = report["meta"]
    cost = (f"Tokens: {m['tokens']:,} ({m['tokens_per_claim']:,} a claim). Live calls {m['live']}, "
            f"cached {m['cached']}. Median latency {m['median_latency_s']} s a claim.")
    lines += ["", cost]
    if m.get("unanswered"):
        lines += ["", (f"The model gave no usable answer for {m['unanswered']} claims; the reviewer sent them to a "
                       f"human, and they are scored that way: {m['unanswered_reasons']}")]
    if m.get("stopped"):
        lines += ["", f"Run stopped early: {m['stopped']}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--name", default="")
    ap.add_argument("--offline", action="store_true", help="replay cached answers only")
    args = ap.parse_args()

    claims = load_claims(args.split)
    if args.limit:
        claims = claims[: args.limit]
    name = args.name or f"{args.model.split('/')[-1]}_{args.split}"
    earlier: dict[str, str] = {}
    previous = Path("reports") / f"verify_{name}.json"
    if args.offline and previous.exists():
        earlier = {c["id"]: c["unanswered"] for c in json.loads(previous.read_text(encoding="utf-8"))["claims"]
                   if c.get("unanswered")}
    rows, stopped = run(args.model, claims, args.timeout, args.offline, earlier)
    if not rows:
        print(f"no results: {stopped}")
        return 1
    lat = sorted(r["latency_s"] for r in rows)
    report = {
        "meta": {"model": args.model, "split": args.split, "n_claims": len(rows), "n_requested": len(claims),
                 "stopped": stopped, "tokens": sum(r["tokens"] for r in rows),
                 "tokens_per_claim": round(sum(r["tokens"] for r in rows) / len(rows)),
                 "live": sum(r["source"] == "live" for r in rows), "cached": sum(r["source"] == "cache" for r in rows),
                 "unanswered": sum(bool(r["unanswered"]) for r in rows),
                 "unanswered_reasons": dict(Counter(r["unanswered"][:80] for r in rows if r["unanswered"])),
                 "median_latency_s": lat[len(lat) // 2]},
        "overall": {"guards_on": rates(rows, True), "guards_off": rates(rows, False)},
        "by_split": {s: {"guards_on": rates([r for r in rows if r["split"] == s], True),
                         "guards_off": rates([r for r in rows if r["split"] == s], False)}
                     for s in ("dev", "test") if any(r["split"] == s for r in rows)},
        "by_op": by_op(rows),
        "confusion": dict(Counter(f"{r['op']} -> {r['status']}" for r in rows)),
        "claims": rows,
    }
    write_report(f"verify_{name}", report, markdown(name, args.model, report))
    on = report["overall"]["guards_on"]
    off = report["overall"]["guards_off"]
    print(f"\n{args.model} on {len(rows)} claims: false approvals {on['false_approvals']}/{on['n_violative']} "
          f"with guards ({off['false_approvals']} without), faithful traced {on['traced_faithful']}/{on['n_faithful']}")
    if stopped:
        print(f"stopped early: {stopped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
