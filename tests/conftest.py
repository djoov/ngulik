"""Fixture bersama: konfigurasi proyek dan database SQLite sementara."""

from __future__ import annotations

import pytest

from ngulik.config import Config
from ngulik.db import Database


@pytest.fixture
def config() -> Config:
    return Config.load()


@pytest.fixture
def db(tmp_path, config):
    with Database(path=tmp_path / "test.db") as database:
        database.initialize()
        yield database


def insert_comments(db: Database, texts: list[str], *, source: str = "test") -> None:
    """Masukkan komentar mentah langsung, tanpa collector."""
    start = db.scalar("SELECT COUNT(*) FROM comments", default=0)
    db.executemany(
        "INSERT INTO comments (source, source_id, text_raw, collected_at) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00')",
        [(source, f"c{start + i}", text) for i, text in enumerate(texts)],
    )
    db.commit()
