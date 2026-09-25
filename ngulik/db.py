"""Lapisan database SQLite: skema, koneksi, dan helper query.

Skema di sini adalah SUPERSET dari daftar minimum PRD bagian 11. Kolom dan
tabel tambahan ditandai komentar beserta requirement yang memerlukannya —
terutama tabel ``videos`` (cache hasil pencarian, penting karena kuota
``search.list`` YouTube hanya 100 call/hari) dan ``analysis_results`` (PRD 5.1
mewajibkan hasil analisis disimpan, tetapi bagian 11 tidak mendefinisikan
tabelnya).

Jaminan penting: tabel ``comments`` bersifat append-only. Sebuah trigger
menolak setiap UPDATE terhadap ``text_raw``, menegakkan FR-003 ("raw data
dipisahkan dari cleaned data") dan NFR-002 ("pipeline dapat dijalankan kembali
menggunakan raw dataset") di level database, bukan sekadar konvensi.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ngulik.config import Config, get_logger
from ngulik.models import utc_now_iso

logger = get_logger("db")

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Versi skema, untuk migrasi di masa depan.
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

-- PRD 11.1 --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keywords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    term            TEXT    NOT NULL,
    type            TEXT    NOT NULL DEFAULT 'KEYWORD'
                    CHECK (type IN ('KEYWORD','PHRASE','HASHTAG')),
    status          TEXT    NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE','INACTIVE')),
    -- Dua kolom berikut di luar daftar PRD 11.1, diperlukan oleh bagian 10
    -- agar asal-usul tiap keyword dapat ditelusuri.
    iteration       INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE (term, type)
);

-- PRD 11.2 — RAW, append-only. Jangan pernah di-UPDATE/DELETE. ------------
CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    source_id    TEXT    NOT NULL,
    text_raw     TEXT    NOT NULL,
    -- PRD 16 data minimization: default NULL, hanya terisi bila pengguna
    -- secara eksplisit menyalakan collection.privacy.store_author_id.
    author_id    TEXT,
    url          TEXT,
    created_at   TEXT,
    collected_at TEXT    NOT NULL,
    run_id       INTEGER REFERENCES collection_runs(id) ON DELETE SET NULL,
    UNIQUE (source, source_id)   -- collect ulang bersifat idempoten
);

-- Penegakan FR-003 / NFR-002 di level database.
CREATE TRIGGER IF NOT EXISTS comments_raw_is_immutable
BEFORE UPDATE OF text_raw ON comments
BEGIN
    SELECT RAISE(ABORT,
        'comments.text_raw bersifat immutable (FR-003): raw dataset tidak boleh diubah');
END;

-- PRD 11.3 ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cleaned_comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id   INTEGER NOT NULL UNIQUE
                 REFERENCES comments(id) ON DELETE CASCADE,
    text_clean   TEXT    NOT NULL,
    tokens       TEXT    NOT NULL DEFAULT '[]',  -- + JSON, hindari re-tokenize
    language     TEXT,
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    duplicate_of INTEGER REFERENCES comments(id) ON DELETE SET NULL,
    is_spam      INTEGER NOT NULL DEFAULT 0,
    spam_reason  TEXT,
    norm_hash    TEXT,     -- + exact duplicate (FR-005)
    simhash      TEXT,     -- + near duplicate  (FR-005)
    processed_at TEXT    NOT NULL
);

-- PRD 11.4 ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collection_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT    NOT NULL,
    iteration          INTEGER NOT NULL DEFAULT 0,
    started_at         TEXT    NOT NULL,
    finished_at        TEXT,
    keyword_count      INTEGER NOT NULL DEFAULT 0,
    comments_collected INTEGER NOT NULL DEFAULT 0,
    status             TEXT    NOT NULL DEFAULT 'RUNNING'
                       CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED')),
    error              TEXT,
    params             TEXT,     -- + snapshot JSON parameter, NFR-002
    quota_used         INTEGER NOT NULL DEFAULT 0   -- + jaga jatah search.list
);

-- PRD 11.5 ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keyword_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    term            TEXT    NOT NULL,
    type            TEXT    NOT NULL DEFAULT 'KEYWORD'
                    CHECK (type IN ('KEYWORD','PHRASE','HASHTAG')),
    source_method   TEXT    NOT NULL,
    frequency       INTEGER NOT NULL DEFAULT 0,
    score           REAL    NOT NULL DEFAULT 0.0,
    discovered_from TEXT,
    iteration       INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    reviewed_at     TEXT,
    created_at      TEXT    NOT NULL,
    UNIQUE (term, iteration)
);

-- Tambahan: cache hasil search.list. ------------------------------------
-- Kuota search.list hanya 100 call/hari dan terpisah dari pool 10.000 unit,
-- jadi hasil pencarian video WAJIB dipakai ulang lintas iterasi.
CREATE TABLE IF NOT EXISTS videos (
    video_id         TEXT PRIMARY KEY,
    keyword          TEXT,
    title            TEXT,
    channel_id       TEXT,
    published_at     TEXT,
    discovered_at    TEXT NOT NULL,
    comments_fetched INTEGER NOT NULL DEFAULT 0
);

-- Tambahan: seed keyword mana yang memunculkan sebuah komentar. ----------
CREATE TABLE IF NOT EXISTS comment_keywords (
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (comment_id, keyword_id)
);

-- Tambahan: komentar mana yang MEMUAT keyword mana. -----------------------
-- Beda dari comment_keywords (keyword pemicu pencarian): tabel ini diisi
-- dengan mencocokkan teks komentar ke seluruh keyword aktif, sehingga
-- komentar dari video pilihan dan dari berkas pun ikut tertaut. Dibangun
-- ulang utuh oleh ngulik.matching, jadi aman dihapus kapan saja.
CREATE TABLE IF NOT EXISTS comment_keyword_matches (
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (comment_id, keyword_id)
);

-- Tambahan: PRD 5.1 mewajibkan "analysis results" disimpan, tetapi ------
-- bagian 11 tidak mendefinisikan tabelnya.
CREATE TABLE IF NOT EXISTS analysis_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration  INTEGER NOT NULL DEFAULT 0,
    method     TEXT    NOT NULL,   -- FREQUENCY | NGRAM | TFIDF | COOCCURRENCE
    term       TEXT    NOT NULL,
    value      REAL    NOT NULL,
    metadata   TEXT,               -- JSON: df, n, pasangan co-occurrence, dst.
    created_at TEXT    NOT NULL
);

-- Tambahan: entri kamus slang dari internet (CLAUDE.md Prioritas 8). -----
-- Sekaligus berfungsi sebagai cache: entri yang masih segar tidak diambil
-- ulang. Tidak ada kolom kontributor (PRD 16). Entri dari kategori yang
-- dikecualikan disimpan dengan term NULL dan excluded = 1, hanya agar tidak
-- diunduh ulang.
CREATE TABLE IF NOT EXISTS lexicon_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT    NOT NULL,
    entry_key  TEXT    NOT NULL,
    url        TEXT    NOT NULL,
    term       TEXT,
    category   TEXT,
    definition TEXT,
    example    TEXT,
    excluded   INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT    NOT NULL,
    UNIQUE (source, entry_key)
);

-- Indeks -----------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_comments_source      ON comments(source);
CREATE INDEX IF NOT EXISTS idx_comments_run         ON comments(run_id);
CREATE INDEX IF NOT EXISTS idx_cleaned_comment_id   ON cleaned_comments(comment_id);
CREATE INDEX IF NOT EXISTS idx_cleaned_norm_hash    ON cleaned_comments(norm_hash);
CREATE INDEX IF NOT EXISTS idx_cleaned_usable       ON cleaned_comments(is_duplicate, is_spam);
CREATE INDEX IF NOT EXISTS idx_candidates_status    ON keyword_candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_iteration ON keyword_candidates(iteration);
CREATE INDEX IF NOT EXISTS idx_candidates_term      ON keyword_candidates(term);
CREATE INDEX IF NOT EXISTS idx_keywords_status      ON keywords(status);
CREATE INDEX IF NOT EXISTS idx_analysis_lookup      ON analysis_results(iteration, method);
CREATE INDEX IF NOT EXISTS idx_videos_keyword       ON videos(keyword);
CREATE INDEX IF NOT EXISTS idx_lexicon_term         ON lexicon_entries(term);
CREATE INDEX IF NOT EXISTS idx_matches_keyword      ON comment_keyword_matches(keyword_id);
"""


# ---------------------------------------------------------------------------
# Koneksi
# ---------------------------------------------------------------------------


class Database:
    """Pembungkus tipis di atas :mod:`sqlite3`.

    Dipakai sebagai context manager::

        with Database(config) as db:
            db.execute("SELECT 1")
    """

    def __init__(self, config: Config | None = None, path: Path | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        elif config is not None:
            self.path = config.database_path
        else:
            raise ValueError("Database needs `config` or `path`")
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    # -- skema --------------------------------------------------------------

    def initialize(self) -> bool:
        """Buat skema bila belum ada. Aman dijalankan berulang.

        Mengembalikan ``True`` bila database baru dibuat pada pemanggilan ini.
        """
        conn = self.conn
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        is_new = existing is None

        conn.executescript(SCHEMA_SQL)
        if is_new:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now_iso()),
            )
            logger.info("Database schema created (version %d) at %s", SCHEMA_VERSION, self.path)
        conn.commit()
        return is_new

    @property
    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0

    # -- query --------------------------------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, [tuple(p) for p in seq])

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    def commit(self) -> None:
        self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transaksi eksplisit: commit bila sukses, rollback bila gagal."""
        conn = self.conn
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()

    # -- ringkasan ----------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Hitungan cepat untuk ``ngulik status``."""
        usable = "is_duplicate = 0 AND is_spam = 0"
        return {
            "keywords": self.scalar(
                "SELECT COUNT(*) FROM keywords WHERE status='ACTIVE'", default=0
            ),
            "keywords_total": self.scalar("SELECT COUNT(*) FROM keywords", default=0),
            "comments": self.scalar("SELECT COUNT(*) FROM comments", default=0),
            "cleaned": self.scalar("SELECT COUNT(*) FROM cleaned_comments", default=0),
            "duplicates": self.scalar(
                "SELECT COUNT(*) FROM cleaned_comments WHERE is_duplicate=1", default=0
            ),
            "spam": self.scalar(
                "SELECT COUNT(*) FROM cleaned_comments WHERE is_spam=1", default=0
            ),
            "usable": self.scalar(
                f"SELECT COUNT(*) FROM cleaned_comments WHERE {usable}", default=0
            ),
            "candidates_pending": self.scalar(
                "SELECT COUNT(*) FROM keyword_candidates WHERE status='PENDING'",
                default=0,
            ),
            "candidates_approved": self.scalar(
                "SELECT COUNT(*) FROM keyword_candidates WHERE status='APPROVED'",
                default=0,
            ),
            "candidates_rejected": self.scalar(
                "SELECT COUNT(*) FROM keyword_candidates WHERE status='REJECTED'",
                default=0,
            ),
            "runs": self.scalar("SELECT COUNT(*) FROM collection_runs", default=0),
            "videos_cached": self.scalar("SELECT COUNT(*) FROM videos", default=0),
            "keyword_matched": self.scalar(
                "SELECT COUNT(DISTINCT comment_id) FROM comment_keyword_matches",
                default=0,
            ),
            "lexicon_entries": self.scalar(
                "SELECT COUNT(*) FROM lexicon_entries WHERE excluded = 0", default=0
            ),
            "iteration": self.current_iteration(),
        }

    def current_iteration(self) -> int:
        """Nomor iterasi tertinggi yang tercatat (PRD bagian 10)."""
        values = [
            self.scalar("SELECT MAX(iteration) FROM keywords", default=0) or 0,
            self.scalar("SELECT MAX(iteration) FROM keyword_candidates", default=0) or 0,
            self.scalar("SELECT MAX(iteration) FROM collection_runs", default=0) or 0,
        ]
        return max(int(v) for v in values)


# ---------------------------------------------------------------------------
# Helper JSON
# ---------------------------------------------------------------------------


def dumps(value: Any) -> str:
    """Serialisasi untuk kolom TEXT berisi JSON."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    """Deserialisasi kolom JSON secara defensif."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Invalid JSON column, using default: %r", value[:80])
        return default
