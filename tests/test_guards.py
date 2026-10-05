from onlabel.agent.ground import locate
from onlabel.agent.guards import check_verdict, figures
from onlabel.agent.verdict import EvidenceQuote, JudgeOutput
from onlabel.data.chunk import Chunk

TEXT = (
    "WEGOVY is indicated in combination with a reduced calorie diet:\n"
    "- to reduce excess body weight in:\n"
    "  - adults and pediatric patients aged 12 years and older with obesity.\n"
    "% change from baseline | -2.4 | ‑14.9"
)


def test_exact_and_normalized_matches():
    assert locate(TEXT, "indicated in combination with a reduced calorie diet").match == "exact"
    g = locate(TEXT, "to reduce excess body weight in: adults and pediatric patients aged 12 years")
    assert g.match == "normalized"  # bullet markers folded away
    assert locate(TEXT, "% change from baseline -2.4 -14.9").match == "normalized"  # pipes and dashes


def test_numbers_never_match_fuzzily():
    assert not locate(TEXT, "% change from baseline | -2.4 | -19.4").ok


def test_wording_drift_matches_fuzzily_without_digits():
    assert locate(TEXT, "WEGOVY is indicated in combination with a reduced-calorie diet").ok


def test_elided_quotes_match_when_every_fragment_appears_in_order():
    g = locate(TEXT, "WEGOVY is indicated ... adults and pediatric patients aged 12 years and older")
    assert g.match == "elided"
    assert "to reduce excess body weight" in g.located  # the reviewer sees the elided middle


def test_elided_quotes_fail_on_wrong_order_wrong_figure_or_too_long_a_span():
    assert not locate(TEXT, "adults and pediatric patients ... WEGOVY is indicated").ok
    assert not locate(TEXT, "WEGOVY is indicated ... aged 10 years and older").ok
    long_text = "Start of a sentence. " + "filler words here " * 60 + "and the end of it."
    assert not locate(long_text, "Start of a sentence ... the end of it").ok


def test_short_or_absent_quotes_fail():
    assert not locate(TEXT, "WEGOVY").ok
    assert not locate(TEXT, "cures type 2 diabetes in children").ok


def test_figures_normalise_and_skip_small_integers():
    assert figures("lost 14.90% (1,306 patients) over 68 weeks in type 2 diabetes") == {"14.9", "1306", "68"}


def _chunk(text: str) -> Chunk:
    return Chunk("d:v1:0:0", "d", "set", 1, "D", "x", 0, "14 CLINICAL STUDIES", "34092-7", "14",
                 0, len(text), 0, len(text), text)


def _out(verdict, quotes, violations=()):
    return JudgeOutput(reasoning="r", verdict=verdict, violations=list(violations),
                       evidence=[EvidenceQuote(chunk_id="d:v1:0:0", quote=q) for q in quotes])


CHUNK = {"d:v1:0:0": _chunk("After 68 weeks, mean change was -14.9% with WEGOVY and -2.4% with placebo.")}


def test_supported_with_matching_quote_stands():
    res = check_verdict(_out("supported", ["mean change was -14.9% with WEGOVY"]), CHUNK,
                        claim="patients lost 14.9% of body weight")
    assert res.status == "supported" and res.flags == []


def test_hallucinated_quote_cannot_support_a_claim():
    res = check_verdict(_out("supported", ["mean change was -20.1% with WEGOVY"]), CHUNK, claim="lost 20.1%")
    assert res.status == "needs_human_review"
    assert "quote_not_found_in_excerpt" in res.flags and "supported_without_grounded_quote" in res.flags


def test_supported_on_a_real_but_different_figure_goes_to_a_human():
    # The second skeleton regression: claim says 14.9, the quote is real but says 2.4.
    res = check_verdict(_out("supported", ["-2.4% with placebo"]), CHUNK, claim="patients lost 14.9%")
    assert res.status == "needs_human_review"
    assert any(f.startswith("claim_figures_not_in_quotes:14.9") for f in res.flags)


def test_supported_that_lists_violations_goes_to_a_human():
    res = check_verdict(_out("supported", ["mean change was -14.9% with WEGOVY"], ["overstated_efficacy"]),
                        CHUNK, claim="lost 14.9%")
    assert res.status == "needs_human_review" and "supported_but_lists_violations" in res.flags


def test_violation_without_evidence_is_a_handoff_and_unsupported_needs_none():
    assert check_verdict(_out("contradicted", []), CHUNK).status == "needs_human_review"
    assert check_verdict(_out("unsupported", []), CHUNK).status == "unsupported"


def _table_chunk() -> Chunk:
    text = "- % change from baseline (LSMean) | -2.4 | -14.9"
    return Chunk("t:v1:0:1", "t", "set", 1, "D", "x", 0,
                 "14 CLINICAL STUDIES > 14.2 Weight Reduction in Patients Aged 12 Years", "34092-7", "14.2",
                 900, 900 + len(text), 900, 900 + len(text), text,
                 context="Table 8. Changes in Body Weight at Week 68\n| PLACEBO N=655 | WEGOVY N=1,306")


def test_table_caption_vouches_for_a_figure_the_row_lacks():
    out = JudgeOutput(reasoning="r", verdict="supported", violations=[],
                      evidence=[EvidenceQuote(chunk_id="t:v1:0:1", quote="% change from baseline (LSMean) | -2.4 | -14.9")])
    res = check_verdict(out, {"t:v1:0:1": _table_chunk()}, claim="lost 14.9% of body weight at 68 weeks")
    assert res.status == "supported" and res.flags == []


def test_a_quoted_title_vouches_only_for_its_own_figures():
    out = JudgeOutput(reasoning="r", verdict="supported", violations=[],
                      evidence=[EvidenceQuote(chunk_id="t:v1:0:1", quote="Weight Reduction in Patients Aged 12 Years")])
    res = check_verdict(out, {"t:v1:0:1": _table_chunk()}, claim="approved from age 12, lost 14.9%")
    assert res.evidence and res.evidence[0].start == 900  # a title quote highlights the excerpt start
    assert res.status == "needs_human_review"
    assert "claim_figures_not_in_quotes:14.9" in res.flags  # "12" was quoted; "14.9" was not


def test_an_unquoted_title_vouches_for_nothing():
    out = JudgeOutput(reasoning="r", verdict="supported", violations=[],
                      evidence=[EvidenceQuote(chunk_id="t:v1:0:1", quote="% change from baseline (LSMean) | -2.4 | -14.9")])
    res = check_verdict(out, {"t:v1:0:1": _table_chunk()}, claim="from age 12, lost 14.9%")
    assert "claim_figures_not_in_quotes:12" in res.flags


def test_unknown_excerpt_id_is_flagged():
    out = JudgeOutput(reasoning="r", verdict="supported", violations=[],
                      evidence=[EvidenceQuote(chunk_id="nope", quote="mean change was -14.9% with WEGOVY")])
    res = check_verdict(out, CHUNK, claim="lost 14.9%")
    assert res.status == "needs_human_review" and "cited_unknown_excerpt" in res.flags
