from onlabel.agent.evidence import present
from onlabel.agent.guards import CheckedEvidence, check_verdict, checks_for
from onlabel.agent.verdict import EvidenceQuote, JudgeOutput
from onlabel.data.chunk import Chunk


def _chunk(text, top_code="34067-9", context="", start=100):
    return Chunk("w:v19:3:0", "wegovy", "set-1", 19, "WEGOVY", "semaglutide", 3, "1 INDICATIONS AND USAGE",
                 top_code, "1", start, start + len(text), start, start + len(text), text, context=context)


def _ev(chunk, quote):
    i = chunk.text.index(quote)
    return CheckedEvidence(chunk.chunk_id, quote, "exact", chunk.section_path, chunk.set_id,
                           chunk.start + i, chunk.start + i + len(quote))


def test_text_quote_comes_with_the_label_text_around_it():
    c = _chunk("WEGOVY is indicated with diet: to reduce excess body weight in adults. More text follows here.")
    out = present(_ev(c, "to reduce excess body weight in adults."), c, {"effective_time": "20260618"})
    assert out["kind"] == "text" and out["before"] == "WEGOVY is indicated with diet: "
    assert out["after"] == " More text follows here." and out["effective_time"] == "20260618"
    assert out["url"].endswith("setid=set-1") and out["label_version"] == 19


def test_long_context_is_clipped_at_word_boundaries():
    c = _chunk(("word " * 100) + "the quote itself here. " + ("tail " * 100))
    out = present(_ev(c, "the quote itself here."), c)
    assert out["before"].startswith("…") and out["after"].endswith("…")
    assert len(out["before"]) <= 242 and not out["before"][1:].startswith(" ")


def test_boxed_warning_quotes_are_marked_boxed():
    c = _chunk("- In rodents, semaglutide causes thyroid C-cell tumors.", top_code="34066-1")
    assert present(_ev(c, "semaglutide causes thyroid C-cell tumors."), c)["kind"] == "boxed"


def test_table_quote_returns_the_table_with_the_row_marked():
    text = ("- Baseline mean (kg) | 105.2 | 105.4\n"
            "- % change from baseline (LSMean) | -2.4 | -14.9\n"
            "Body Weight | | |")
    ctx = "- Table 8. Changes in Body Weight at Week 68\n| Study 2 placebo | Study 2 WEGOVY"
    c = _chunk(text, top_code="34092-7", context=ctx)
    out = present(_ev(c, "% change from baseline (LSMean) | -2.4 | -14.9"), c)
    assert out["kind"] == "table"
    t = out["table"]
    assert t["caption"] == "Table 8. Changes in Body Weight at Week 68"
    assert t["header"] == [["", "Study 2 placebo", "Study 2 WEGOVY"]]
    assert t["rows"][1] == ["% change from baseline (LSMean)", "-2.4", "-14.9"]
    assert t["rows"][2] == ["Body Weight", "", "", ""]  # empty cells survive whitespace collapsing
    assert t["highlight"] == [1]


def _judge(verdict, quotes, violations=()):
    return JudgeOutput(reasoning="r", verdict=verdict, violations=list(violations),
                       evidence=[EvidenceQuote(chunk_id="w:v19:3:0", quote=q) for q in quotes])


def test_checks_read_as_plain_sentences():
    c = _chunk("After 68 weeks, mean change was -14.9% with WEGOVY and -2.4% with placebo.")
    chunks = {c.chunk_id: c}
    out = _judge("supported", ["mean change was -14.9% with WEGOVY", "a quote that is not there at all"])
    res = check_verdict(out, chunks, claim="lost 14.9% at 68 weeks")
    texts = [k["text"] for k in checks_for("lost 14.9% at 68 weeks", out, res)]
    assert texts[0] == "1 of 2 quotes found word for word in the label."
    assert texts[1] == "1 quote dropped: the wording is not in the label text."
    assert any(t.startswith("Figures in the claim missing from every quote: 68") for t in texts)


def test_checks_when_no_model_answered():
    assert checks_for("x", None, None) == [{"ok": False, "text": "No model was available, so a reviewer decides."}]


def test_unsupported_needs_no_quote():
    c = _chunk("Irrelevant label text for this claim.")
    out = _judge("unsupported", [])
    res = check_verdict(out, {c.chunk_id: c}, claim="cures obesity")
    assert checks_for("cures obesity", out, res)[0]["ok"] is True


def test_a_stitched_table_quote_marks_only_the_rows_it_quoted():
    text = ("- Baseline mean (kg) | 105.2 | 105.4\n"
            "- Absolute change (kg) | -2.6 | -15.3\n"
            "- % change from baseline (LSMean) | -2.4 | -14.9")
    c = _chunk(text, top_code="34092-7", context="- Table 8. Changes in Body Weight at Week 68\n| PLACEBO | WEGOVY")
    out = JudgeOutput(reasoning="r", verdict="supported", violations=[], evidence=[EvidenceQuote(
        chunk_id=c.chunk_id, quote="Baseline mean (kg) | 105.2 | 105.4 % change from baseline (LSMean) | -2.4 | -14.9")])
    res = check_verdict(out, {c.chunk_id: c}, claim="lost 14.9%")
    assert res.evidence[0].match == "stitched"
    table = present(res.evidence[0], c)["table"]
    assert table["highlight"] == [0, 2]  # the skipped "Absolute change" row is not marked
