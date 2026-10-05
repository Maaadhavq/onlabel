from onlabel.data.chunk import fixed_chunks, label_doc, section_chunks
from onlabel.data.parse_spl import parse_spl
from tests.fixtures import SPL


def test_parse_identity_and_skips():
    label = parse_spl(SPL)
    assert label.set_id == "11111111-2222-3333-4444-555555555555"
    assert label.version == 7 and label.effective_time == "20260618"
    assert label.products == ["TESTADRUG"] and label.generic == "testaglutide"
    codes = [s.top_code for s in label.sections]
    assert "48780-1" not in codes and "51945-4" not in codes  # product data and carton skipped
    assert label.skipped_codes == []


def test_sections_are_numbered_and_pathed():
    label = parse_spl(SPL)
    sub = next(s for s in label.sections if s.number == "14.2")
    assert sub.title == "Weight Reduction Studies"
    assert sub.path == "14 CLINICAL STUDIES > 14.2 Weight Reduction Studies"
    boxed = next(s for s in label.sections if s.top_code == "34066-1")
    assert boxed.number is None


def test_bullets_are_one_line_and_nested_bullets_keep_their_indent():
    ind = next(s for s in parse_spl(SPL).sections if s.number == "1")
    lines = ind.text.splitlines()
    assert "- to reduce excess body weight in:" in lines
    assert "  - adults and pediatric patients aged 12 years and older with obesity." in lines
    assert "•" not in ind.text  # the bullet glyph caption is dropped


def test_tables_render_as_rows_and_footnote_marks_drop_but_exponents_stay():
    sub = next(s for s in parse_spl(SPL).sections if s.number == "14.2")
    assert "% change from baseline | -2.4 | ‑14.9" in sub.text
    assert "baselinea" not in sub.text  # footnote mark "a" removed
    assert "10^9/L" in sub.text


def test_section_chunks_keep_exact_offsets():
    label = parse_spl(SPL)
    for c in section_chunks(label, "testadrug", "testaglutide", max_words=12):
        sec = label.sections[c.section_index]
        assert sec.text[c.start : c.end] == c.text
        assert label_doc(label)[c.doc_start : c.doc_end] == c.text


def test_chunk_cut_mid_table_carries_the_header():
    label = parse_spl(SPL)
    chunks = section_chunks(label, "testadrug", "testaglutide", max_words=12)
    row = next(c for c in chunks if c.text.startswith("Patients losing 5%"))
    assert "TESTADRUG N=1,306" in row.context


def test_fixed_chunks_cover_the_document():
    label = parse_spl(SPL)
    doc = label_doc(label)
    chunks = fixed_chunks(label, "testadrug", "testaglutide", window=10, overlap=3)
    assert chunks[0].doc_start == 0
    assert max(c.doc_end for c in chunks) == len(doc)
    for c in chunks:
        assert doc[c.doc_start : c.doc_end] == c.text
