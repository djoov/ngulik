"""Test analisis korpus (AC-006 sampai AC-009) dengan korpus kecil yang dihitung tangan."""

from __future__ import annotations

import math

import pytest

from ngulik.analysis import (
    Corpus,
    cooccurrence,
    ngram_counts,
    run_analysis,
    term_frequency,
    tfidf_scores,
)
from ngulik.cleaning import CleaningPipeline
from tests.conftest import insert_comments


def corpus(*docs: str) -> Corpus:
    return Corpus(comment_ids=list(range(len(docs))), docs=[d.split() for d in docs])


def test_term_frequency_counts_tokens_and_documents():
    result = {t.term: t for t in term_frequency(corpus("a b a", "a c"))}

    assert (result["a"].count, result["a"].doc_freq) == (3, 2)
    assert result["a"].relative == pytest.approx(3 / 5)
    assert list(result)[0] == "a"


def test_ngrams_respect_sizes_and_min_frequency():
    stats = ngram_counts(corpus("x y z", "x y", "x y q"), sizes=[2, 3], min_frequency=2)

    assert [(s.term, s.size, s.count, s.doc_freq) for s in stats] == [("x y", 2, 3, 3)]


def test_tfidf_matches_the_documented_formula():
    scores = {s.term: s.score for s in tfidf_scores(corpus("x y", "x"))}

    idf_x, idf_y = math.log(1 + 2 / 2), math.log(1 + 2 / 1)
    norm = math.hypot(idf_x, idf_y)
    assert scores["x"] == pytest.approx(idf_x / norm + 1.0)
    assert scores["y"] == pytest.approx(idf_y / norm)


def test_cooccurrence_window_and_pmi():
    docs = corpus(*["kopi pagi hujan"] * 3, "hujan deras", "kopi susu")

    pairs = {p.label: p for p in cooccurrence(docs, window=2, min_pair_frequency=3)}

    # window=2: hanya tetangga langsung, jadi "kopi ~ hujan" tidak pernah terhitung.
    assert set(pairs) == {"kopi ~ pagi", "hujan ~ pagi"}
    assert pairs["kopi ~ pagi"].count == 3
    assert pairs["kopi ~ pagi"].pmi > 0
    assert -1 <= pairs["kopi ~ pagi"].npmi <= 1


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError):
        cooccurrence(corpus("a b"), metric="magic")


def test_run_analysis_saves_and_replaces_results(config, db):
    insert_comments(db, [f"zorbak plenger {w} tempo" for w in
                         ("alfa", "bravo", "charlie", "delta")])
    CleaningPipeline(config, db).run()

    first = run_analysis(config, db)
    second = run_analysis(config, db)

    assert first.documents == 4
    assert first.stored == second.stored > 0
    assert db.scalar("SELECT COUNT(*) FROM analysis_results") == second.stored
    methods = {r["method"] for r in db.query("SELECT DISTINCT method FROM analysis_results")}
    assert methods == {"FREQUENCY", "NGRAM", "TFIDF", "COOCCURRENCE"}


def test_npmi_stays_within_bounds_on_random_text():
    import random

    rng = random.Random(7)
    vocab = [f"w{i}" for i in range(12)]
    docs = corpus(*(" ".join(rng.choices(vocab, k=rng.randint(3, 15))) for _ in range(200)))

    pairs = cooccurrence(docs, window=5, min_pair_frequency=1)

    assert pairs
    assert all(-1.0 - 1e-9 <= p.npmi <= 1.0 + 1e-9 for p in pairs)
