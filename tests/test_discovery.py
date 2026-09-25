"""Test generator kandidat dari korpus (AC-010) memakai kata karangan.

Kata karangan dipakai supaya tidak bentrok dengan kamus slang atau stopword.
"""

from __future__ import annotations

import pytest

from ngulik.cleaning import CleaningPipeline
from ngulik.discovery import discover_candidates, find_pending, seed_forms, set_status
from ngulik.keywords import KeywordManager
from ngulik.models import CandidateStatus
from tests.conftest import insert_comments

NAMES = ("alfa", "bravo", "charlie", "delta", "echo", "foxtrot")


@pytest.fixture
def corpus_db(config, db):
    """6 komentar dengan seed 'zorbak' dekat 'plenger', 5 tentang 'kliwon', 2 'jarang'."""
    insert_comments(db, [f"zorbak plenger {w} tempo" for w in NAMES])
    insert_comments(db, [f"kliwon rumah {w} sepi" for w in NAMES[:5]])
    insert_comments(db, [f"jarang {w} muncul" for w in NAMES[:2]])
    CleaningPipeline(config, db).run()
    KeywordManager(db).add("#Zorbak")
    return db


def by_term(result):
    return {c.term: c for c in result.candidates}


def test_seed_forms_follow_the_cleaning_pipeline(config):
    assert seed_forms(config, ["#Zorbak", "ZORBAK   Plenger"]) == {
        "zorbak": "#Zorbak", "zorbak plenger": "ZORBAK   Plenger"}


def test_candidates_near_the_seed_get_the_cooccurrence_signal(config, corpus_db):
    found = by_term(discover_candidates(config, corpus_db, dry_run=True, max_candidates=100))

    assert found["plenger"].seed == "#zorbak"
    assert found["plenger"].raw["cooccurrence"] > 0
    assert found["kliwon"].seed is None
    assert found["plenger"].score > found["kliwon"].score


def test_gate_excludes_seeds_and_rare_terms(config, corpus_db):
    found = by_term(discover_candidates(config, corpus_db, dry_run=True, max_candidates=100))

    assert "zorbak" not in found           # sudah jadi keyword
    assert "jarang" not in found           # hanya di 2 komentar < min_doc_frequency
    assert "zorbak plenger" not in found or found["zorbak plenger"].size == 2


def test_phrases_are_typed_and_explained(config, corpus_db):
    found = by_term(discover_candidates(config, corpus_db, dry_run=True, max_candidates=100))

    phrase = found["kliwon rumah"]
    assert phrase.keyword_type == "PHRASE"
    assert phrase.raw["ngram"] == 1.0
    assert "docs=5" in phrase.explain("pmi")
    assert "near seed '#zorbak'" in found["plenger"].explain("pmi")


def test_dry_run_saves_nothing_and_real_run_is_idempotent(config, corpus_db):
    discover_candidates(config, corpus_db, dry_run=True)
    assert corpus_db.scalar("SELECT COUNT(*) FROM keyword_candidates") == 0

    first = discover_candidates(config, corpus_db)
    second = discover_candidates(config, corpus_db)

    assert first.created > 0
    assert second.created == 0
    row = corpus_db.query_one("SELECT * FROM keyword_candidates WHERE term = 'plenger'")
    assert row["status"] == "PENDING" and row["frequency"] == 6
    assert row["source_method"] in {"FREQUENCY", "TFIDF", "COOCCURRENCE", "NGRAM"}


def test_rejected_candidates_are_not_proposed_again(config, corpus_db):
    discover_candidates(config, corpus_db)
    set_status(corpus_db, find_pending(corpus_db, "kliwon").id, CandidateStatus.REJECTED)
    corpus_db.execute("DELETE FROM keyword_candidates WHERE status = 'PENDING'")
    corpus_db.commit()

    found = by_term(discover_candidates(config, corpus_db, dry_run=True, max_candidates=100))

    assert "kliwon" not in found
    assert "plenger" in found


def test_empty_corpus_returns_nothing(config, db):
    result = discover_candidates(config, db)
    assert (result.documents, result.pool, result.created) == (0, 0, 0)
