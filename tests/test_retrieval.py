from onlabel.data.chunk import section_chunks
from onlabel.data.parse_spl import parse_spl
from onlabel.retrieval.bm25 import BM25, tokenize
from onlabel.retrieval.index import LabelIndex
from tests.fixtures import SPL, HashEncoder


def test_tokenizer_keeps_numbers_whole_and_drops_signs():
    assert tokenize("lost 14.9% vs ‑2.4 at 68 weeks") == ["lost", "14.9", "vs", "2.4", "68", "weeks"]
    assert "c-cell" in tokenize("thyroid C‑cell tumors")


def test_percent_claim_matches_a_signed_table_cell():
    # The regression from the first skeleton run: "14.9%" in a claim vs "-14.9" in a table.
    bm = BM25.build(["% change from baseline | -2.4 | -14.9", "statistically significant reduction"])
    s = bm.scores("lost an average of 14.9% of body weight")
    assert s[0] > 0 and s[0] > s[1]


def test_bm25_round_trips(tmp_path):
    bm = BM25.build(["semaglutide 2.4 mg weekly", "placebo arm", "weekly injection"])
    bm.save(tmp_path)
    again = BM25.load(tmp_path)
    assert (again.scores("weekly 2.4") == bm.scores("weekly 2.4")).all()


def _index():
    label = parse_spl(SPL)
    chunks = section_chunks(label, "testadrug", "testaglutide", max_words=12)
    return LabelIndex.build(chunks, HashEncoder(), meta={"strategy": "section"})


def test_search_filters_by_label_and_section():
    idx = _index()
    enc = HashEncoder()
    hits = idx.search("thyroid tumors", enc.encode_query("thyroid tumors"), k=3, top_codes=["34066-1"])
    assert hits and all(h.chunk.top_code == "34066-1" for h in hits)
    assert idx.search("x", enc.encode_query("x"), labels=["no-such-label"]) == []


def test_chunk_holding_a_claims_rare_figure_is_pinned_first():
    idx = _index()
    enc = HashEncoder()
    q = "patients lost 14.9% of their weight"
    hits = idx.search(q, enc.encode_query(q), k=2, use_dense=True, use_bm25=True)
    assert "14.9" in hits[0].chunk.text and hits[0].number_rank == 1


def test_index_round_trips(tmp_path):
    idx = _index()
    idx.save(tmp_path)
    again = LabelIndex.load(tmp_path)
    assert [c.chunk_id for c in again.chunks] == [c.chunk_id for c in idx.chunks]
    assert again.embeddings.shape == idx.embeddings.shape
