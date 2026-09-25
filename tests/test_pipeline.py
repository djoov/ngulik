"""Test orkestrator cleaning (AC-004, AC-005)."""

from __future__ import annotations

import pytest

from ngulik.cleaning import CleaningPipeline
from ngulik.db import loads
from tests.conftest import insert_comments

ORIGINAL = "Penjelasan di video ini jelas dan runtut sekali"


def _rows(db):
    return db.query("SELECT * FROM cleaned_comments ORDER BY comment_id")


def test_every_comment_gets_a_cleaned_row(config, db):
    insert_comments(db, [ORIGINAL, "Suara narasinya enak didengar, semoga konsisten"])

    stats = CleaningPipeline(config, db).run()

    rows = _rows(db)
    assert stats.processed == len(rows) == 2
    assert rows[0]["text_clean"] == ORIGINAL.lower()
    assert "runtut" in loads(rows[0]["tokens"])
    assert rows[0]["norm_hash"] and rows[0]["simhash"]


def test_exact_duplicate_after_normalization(config, db):
    insert_comments(db, [ORIGINAL, ORIGINAL.upper() + "   "])

    CleaningPipeline(config, db).run()

    first, second = _rows(db)
    assert not first["is_duplicate"]
    assert second["is_duplicate"] and second["duplicate_of"] == first["comment_id"]


def test_incremental_run_detects_duplicate_of_earlier_run(config, db):
    insert_comments(db, [ORIGINAL])
    CleaningPipeline(config, db).run()

    insert_comments(db, [ORIGINAL])
    stats = CleaningPipeline(config, db).run()

    assert stats.processed == 1
    assert stats.duplicates == 1


def test_raw_text_is_never_modified(config, db):
    insert_comments(db, ["TEKS Asli   dengan https://contoh.id tautan"])
    before = db.scalar("SELECT text_raw FROM comments")

    CleaningPipeline(config, db).run(reprocess=True)

    assert db.scalar("SELECT text_raw FROM comments") == before


def test_reprocess_rebuilds_from_scratch(config, db):
    insert_comments(db, [ORIGINAL, ORIGINAL])
    CleaningPipeline(config, db).run()

    stats = CleaningPipeline(config, db).run(reprocess=True)

    assert stats.reprocessed
    assert stats.processed == 2
    assert stats.duplicates == 1
    assert len(_rows(db)) == 2


@pytest.mark.parametrize("reprocess", [False, True])
def test_second_run_is_idempotent(config, db, reprocess):
    insert_comments(db, [ORIGINAL, "komentar kedua yang juga cukup panjang"])
    pipeline = CleaningPipeline(config, db)
    pipeline.run()

    CleaningPipeline(config, db).run(reprocess=reprocess)

    assert len(_rows(db)) == 2
