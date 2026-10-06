"""EVALS.md and the page's summary, built from the committed reports (never typed by hand).

    uv run python -m evals.summarize
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from evals.common import REPORTS, load_claims, wilson

SUMMARY = Path("web/src/evals/summary.json")
EVALS_MD = Path("EVALS.md")
REPO = "https://github.com/Maaadhavq/onlabel/blob/main"

NAMES = {
    "groq/gpt-oss-120b": "gpt-oss-120b (Groq)",
    "groq/gpt-oss-20b": "gpt-oss-20b (Groq)",
    "groq/qwen3.8-27b": "Qwen3.8 27B (Groq)",
    "gemini/gemma-4-26b": "Gemma 4 26B (Google AI Studio)",
    "ollama/llama3.1-8b": "Llama 3.1 8B (local)",
    "ollama/qwen3-8b": "Qwen3 8B (local)",
    "ollama/gemma4-e4b": "Gemma 4 E4B (local)",
}
# The production chain's order, then local models.
ORDER = list(NAMES)


def _load(pattern: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPORTS.glob(pattern))}


def bench_facts() -> dict:
    claims = load_claims()
    return {
        "claims": len(claims), "cards": len({c["card"] for c in claims}), "labels": len({c["label"] for c in claims}),
        "faithful": sum(c["op"] == "faithful" for c in claims), "violative": sum(c["op"] != "faithful" for c in claims),
        "dev": sum(c["split"] == "dev" for c in claims), "test": sum(c["split"] == "test" for c in claims),
        "ops": dict(Counter(c["op"] for c in claims)),
    }


def verify_rows(reports: dict[str, dict]) -> list[dict]:
    rows = []
    for stem, r in reports.items():
        m = r["meta"]
        fa = [{"id": c["id"], "op": c["op"], "text": c["text"]} for c in r["claims"]
              if c["op"] != "faithful" and c["status"] == "supported"]
        missed = [{"id": c["id"], "status": c["status"], "text": c["text"]} for c in r["claims"]
                  if c["op"] == "faithful" and c["status"] != "supported"]
        stopped_by_guards = [{"id": c["id"], "op": c["op"], "status": c["status"], "flags": c["flags"], "text": c["text"]}
                             for c in r["claims"] if c["op"] != "faithful" and c["model_verdict"] == "supported"
                             and c["status"] != "supported"]
        rows.append({
            "report": stem, "model": m["model"], "name": NAMES.get(m["model"], m["model"]), "split": m["split"],
            "n": m["n_claims"], "complete": not m.get("stopped") and m["n_claims"] == m.get("n_requested", m["n_claims"]),
            "guards_on": r["overall"]["guards_on"], "guards_off": r["overall"]["guards_off"],
            "by_split": {s: v["guards_on"] for s, v in r.get("by_split", {}).items()},
            "by_op": r["by_op"], "false_approvals": fa, "faithful_not_traced": missed,
            "stopped_by_guards": stopped_by_guards,
            "unanswered": m.get("unanswered", 0), "unanswered_reasons": m.get("unanswered_reasons", {}),
            "tokens_per_claim": m["tokens_per_claim"], "median_latency_s": m["median_latency_s"],
        })
    rows.sort(key=lambda x: (ORDER.index(x["model"]) if x["model"] in ORDER else 99, x["split"]))
    return rows


def retrieval_rows(reports: dict[str, dict]) -> dict:
    out = {}
    for stem, r in reports.items():
        res = r["results"]
        out[stem.removeprefix("retrieval_")] = {
            "strategy": r["meta"]["strategy"], "n_chunks": r["meta"]["n_chunks"], "n_claims": r["meta"]["n_claims"],
            "configs": {k: {"hit@1": v["hit@1"], "hit@5": v["hit@5"], "hit@10": v.get("hit@10"),
                            "all": v.get("hit@all"), "mrr@10": v["mrr@10"], "misses": len(v["misses"])}
                        for k, v in res.items()},
            "production_misses": res["production"]["misses"],
        }
    return out


def redteam_rows(reports: dict[str, dict]) -> list[dict]:
    rows = []
    for stem, r in reports.items():
        rows.append({"report": stem, "model": r["meta"]["model"], "name": NAMES.get(r["meta"]["model"], r["meta"]["model"]),
                     "prompt_guard": r["meta"]["prompt_guard"], "n_attacks": r["meta"]["n_attacks"],
                     "answered": r["meta"]["answered"],
                     "layers": {k: v["successes"] for k, v in r["attack_success"].items()},
                     "detector": r["detector"],
                     "attacks": [{k: a[k] for k in ("id", "technique", "model_verdict", "after_guards", "final")}
                                 for a in r["attacks"]]})
    rows.sort(key=lambda x: ORDER.index(x["model"]) if x["model"] in ORDER else 99)
    return rows


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def markdown(s: dict) -> str:
    b = s["bench"]
    L = ["# OnLabel evaluation", "",
         (f"Generated {s['generated']} by `evals/summarize.py` from the JSON in `reports/`. Every number below traces "
         "to a committed report, and the model answers behind them are in the committed cache (`cache/llm`), so a "
         "fresh clone reproduces them without API keys."), "",
         "## The benchmark", "",
         (f"{b['claims']} claims written from {b['cards']} fact cards across {b['labels']} FDA labels "
         f"({b['faithful']} faithful, {b['violative']} violative). Each card holds verbatim label text; "
         "`evals/build_bench.py` refuses to build if any quote is missing from its label. A claim's expected verdict "
         "comes from how it was built (restated faithfully, a qualifier dropped, a population broadened, a figure "
         "inflated, superiority or an absolute added, a risk denied, a contraindication contradicted, a dose changed), "
         "never from a model."), "",
         (f"Splits follow the active ingredient. Semaglutide and tirzepatide labels were in view while the prompts and "
         f"guards were written (dev, {b['dev']} claims); the other six ingredients were not (test, {b['test']} claims)."), "",
         ("Faithful efficacy claims state the figure with its trial context (study length, population, dose, "
         "comparator). A claim that generalises one study's figure to \"in clinical trials\" is not used as a faithful "
         "item, because an MLR reviewer would ask for a qualifier (PROGRESS finding 12)."), "",
         "## Would it trace a violation?", "",
         ("Traced means the reviewer shows the claim as supported. A violative claim that comes back traced is the "
         "failure the tool exists to prevent; a faithful claim that is not traced costs a reviewer a look."), "",
         "| Model | Split | Violative claims traced (guards on) | Guards off | Faithful claims traced | Sent to a human |",
         "|---|---|---|---|---|---|"]
    for v in s["verify"]:
        on, off = v["guards_on"], v["guards_off"]
        # A bootstrap of zero events is the point 0 again; use the Wilson interval for those.
        ci = wilson(0, on["n_violative"]) if on["false_approvals"] == 0 else on.get("false_approval_ci")
        ci_txt = f" (95% CI {pct(ci[0])} to {pct(ci[1])})" if ci else ""
        L.append(f"| {v['name']} | {v['split']} ({v['n']}) | {on['false_approvals']}/{on['n_violative']}{ci_txt} | "
                 f"{off['false_approvals']}/{off['n_violative']} | {on['traced_faithful']}/{on['n_faithful']} | "
                 f"{pct(on['human_review'])} |")
    L += ["", ("Intervals are 95% cluster-bootstrap intervals over fact cards (claims written from one card share "
          "their evidence); with no violative claim traced, the Wilson interval. Per-claim results: "
          "`reports/verify_*.md`."), ""]
    for v in s["verify"]:
        if v["stopped_by_guards"]:
            L.append(f"- {v['name']}: the guards stopped {len(v['stopped_by_guards'])} violative claims the model "
                     "had called supported.")
        if v["unanswered"]:
            L.append(f"- {v['name']}: no usable answer for {v['unanswered']} claims, scored as sent to a human "
                     f"({', '.join(v['unanswered_reasons'])}).")
    L += ["", "## Retrieval", "",
          ("Does the label text a claim depends on reach the judge? Gold is the character span of each card quote, so "
          "chunkings of any shape score on the same footing."), "",
          "| Index | Configuration | Hit@5 | Judge's excerpts | MRR@10 |", "|---|---|---|---|---|"]
    for name, r in s["retrieval"].items():
        for cfg in ("dense", "bm25", "hybrid", "hybrid+figures", "production"):
            c = r["configs"].get(cfg)
            if c:
                shown = c["all"] if c["all"] is not None else c["hit@10"]
                L.append(f"| {name} ({r['strategy']}, {r['n_chunks']} chunks) | {cfg} | {c['hit@5']:.2f} | "
                         f"{shown:.2f} | {c['mrr@10']:.2f} |")
    L += ["", ("`production` is what the API sends the judge: 5 similarity hits plus up to 2 excerpts from the "
          "sections that govern the claim's kind, 6 at most. `Judge's excerpts` is hit@10 for the other rows."), ""]
    L += ["## Red team", "",
          ("Each attack wraps a violative claim in an injection asking for it to be traced. The patterns and the "
          "attacks were written by the same person, so the pattern layer's hit rate is an upper bound; Prompt Guard 2 "
          "is the layer nobody tuned to this set."), "",
          "| Model | Model alone | + guards | + injection check | Patterns flag attacks | Prompt Guard 2 alone | False alarms on benign copy |",
          "|---|---|---|---|---|---|---|"]
    for r in s["redteam"]:
        d, n = r["detector"], r["answered"]
        pg = d.get("prompt_guard_alone")
        both = d.get("patterns+prompt_guard", d["patterns"])
        L.append(f"| {r['name']} | {r['layers']['model_verdict']}/{n} traced | {r['layers']['after_guards']}/{n} | "
                 f"{r['layers']['final']}/{n} | {d['patterns']['attacks_flagged']}/{d['patterns']['n_attacks']} | "
                 f"{(str(pg['attacks_flagged']) + '/' + str(d['patterns']['n_attacks'])) if pg else 'not run'} | "
                 f"{both['benign_flagged']}/{both['n_benign']} |")
    L += ["", "## Limits", "",
          ("- One author wrote the cards, the perturbations and the red team. The synthetic set measures whether the "
          "pipeline catches violations of known shapes; it is not a sample of real promotional copy."),
          ("- Two guard rules were written after seeing benchmark failures, test split included: quotes that "
           "skip whole lines or name the wrong excerpt are matched where they are (89 rejected quotes replayed, "
           "35 still rejected), and a traced claim must carry the conditions its quoted indication attaches. "
           "Before the conditions rule, gpt-oss-120b traced 2 of 42 violative test claims, both a glycemic claim "
           "without \"as an adjunct to diet and exercise\". The test split no longer measures these rules blind; "
           "the 'guards off' column shows what the models did on their own."),
          ("- The planned holdout of claims FDA cited in 2024-26 untitled letters is not built yet; it needs a "
          "person to verify each extracted claim. It is the blind test these rules have not had."),
          ("- Free-tier daily quotas (Groq: 200K tokens a day per model) limited gpt-oss-120b to the test split, "
           "and its red-team run stopped after 4 attacks, so the full red team ran on gpt-oss-20b, the next model "
           "in the production chain. The committed cache makes every run repeatable."),
          "- Visuals, audio, layout and a piece's overall impression are out of scope, as the page says.", "",
          "## Reproduce", "", "```bash", "uv run python -m evals.build_bench",
          "uv run python -m evals.retrieval_eval", "uv run python -m evals.verify_eval --model groq/gpt-oss-120b --split test",
          "uv run python -m evals.redteam_eval --model groq/gpt-oss-120b", "uv run python -m evals.summarize", "```", ""]
    return "\n".join(L)


def main() -> int:
    summary = {
        "generated": datetime.now(UTC).date().isoformat(),
        "repo": REPO,
        "bench": bench_facts(),
        "verify": verify_rows(_load("verify_*.json")),
        "retrieval": retrieval_rows(_load("retrieval_*.json")),
        "redteam": redteam_rows(_load("redteam_*.json")),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    EVALS_MD.write_text(markdown(summary), encoding="utf-8", newline="\n")
    print(f"wrote {SUMMARY} and {EVALS_MD}: {len(summary['verify'])} verification runs, "
          f"{len(summary['retrieval'])} retrieval runs, {len(summary['redteam'])} red-team runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
