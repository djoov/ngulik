"""Dataclass yang memetakan tabel database (PRD bagian 11).

Dipakai sebagai kontrak antar-modul: collector menghasilkan
:class:`RawComment`, cleaning menghasilkan :class:`CleanedComment`, discovery
menghasilkan :class:`KeywordCandidate`. Tidak ada modul yang saling mengoper
dict mentah, sehingga penambahan sumber baru tidak merembet ke NLP pipeline
(NFR-004).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now_iso() -> str:
    """Timestamp UTC ISO-8601 dengan presisi detik.

    Semua kolom waktu disimpan sebagai TEXT dalam format ini. Adapter datetime
    bawaan sqlite3 sengaja tidak dipakai karena sudah deprecated sejak
    Python 3.12.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class KeywordType(StrEnum):
    """Tipe keyword sesuai PRD FR-001."""

    KEYWORD = "KEYWORD"
    PHRASE = "PHRASE"
    HASHTAG = "HASHTAG"


class KeywordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CandidateStatus(StrEnum):
    """Status kandidat sesuai PRD bagian 8."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SourceMethod(StrEnum):
    """Metode analisis yang memunculkan sebuah kandidat (PRD bagian 8)."""

    FREQUENCY = "FREQUENCY"
    NGRAM = "NGRAM"
    TFIDF = "TFIDF"
    COOCCURRENCE = "COOCCURRENCE"
    #: Istilah dari kamus/glosarium slang di internet (CLAUDE.md Prioritas 8).
    LEXICON = "LEXICON"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Keyword:
    """Baris tabel ``keywords``.

    ``iteration`` dan ``discovered_from`` adalah tambahan di luar daftar
    minimum PRD 11.1, diperlukan agar asal-usul keyword bisa ditelusuri
    sebagaimana diwajibkan PRD bagian 10.
    """

    term: str
    type: KeywordType = KeywordType.KEYWORD
    status: KeywordStatus = KeywordStatus.ACTIVE
    iteration: int = 0
    discovered_from: str | None = None
    id: int | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Keyword":
        return cls(
            id=row["id"],
            term=row["term"],
            type=KeywordType(row["type"]),
            status=KeywordStatus(row["status"]),
            iteration=row["iteration"],
            discovered_from=row["discovered_from"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class RawComment:
    """Schema seragam yang WAJIB dihasilkan setiap collector (PRD FR-002).

    Inilah satu-satunya kontrak antara lapisan collection dan lapisan
    pemrosesan. Menambah sumber baru berarti menghasilkan bentuk ini — tidak
    ada bagian lain dari pipeline yang perlu berubah.

    ``author_id`` default ``None``: PRD bagian 16 mewajibkan data minimization,
    dan identitas komentator tidak dibutuhkan untuk analisis pola bahasa.
    """

    source: str
    source_id: str
    text: str
    author_id: str | None = None
    created_at: str | None = None
    url: str | None = None
    keyword: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("RawComment.source_id must not be empty")
        if self.text is None:
            raise ValueError("RawComment.text must not be None")


@dataclass(slots=True)
class CleanedComment:
    """Baris tabel ``cleaned_comments`` (PRD 11.3)."""

    comment_id: int
    text_clean: str
    tokens: list[str]
    language: str | None = None
    is_duplicate: bool = False
    duplicate_of: int | None = None
    is_spam: bool = False
    spam_reason: str | None = None
    norm_hash: str | None = None
    simhash: str | None = None
    id: int | None = None
    processed_at: str = field(default_factory=utc_now_iso)

    @property
    def is_usable(self) -> bool:
        """Apakah baris ini layak masuk analisis.

        Duplikat dan spam tetap DISIMPAN (agar rasionya bisa dilaporkan
        sebagai metrik kualitas data, PRD bagian 22) tetapi dikeluarkan dari
        korpus analisis supaya tidak mendominasi frequency.
        """
        return not self.is_duplicate and not self.is_spam


@dataclass(slots=True)
class CollectionRun:
    """Baris tabel ``collection_runs`` (PRD 11.4) — audit trail NFR-005."""

    source: str
    iteration: int = 0
    status: RunStatus = RunStatus.RUNNING
    keyword_count: int = 0
    comments_collected: int = 0
    quota_used: int = 0
    error: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None


@dataclass(slots=True)
class LexiconEntry:
    """Baris tabel ``lexicon_entries``: satu entri kamus slang dari internet.

    Sengaja tidak punya field kontributor. Nama pengusul entri adalah data
    identitas yang tidak dibutuhkan (PRD bagian 16).
    """

    source: str
    entry_key: str
    url: str
    term: str | None = None
    category: str | None = None
    definition: str | None = None
    example: str | None = None
    excluded: bool = False
    id: int | None = None
    fetched_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class KeywordCandidate:
    """Baris tabel ``keyword_candidates`` (PRD 11.5)."""

    term: str
    source_method: str
    frequency: int = 0
    score: float = 0.0
    type: KeywordType = KeywordType.KEYWORD
    discovered_from: str | None = None
    iteration: int = 0
    status: CandidateStatus = CandidateStatus.PENDING
    id: int | None = None
    reviewed_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "KeywordCandidate":
        return cls(
            id=row["id"],
            term=row["term"],
            type=KeywordType(row["type"]),
            source_method=row["source_method"],
            frequency=row["frequency"],
            score=row["score"],
            discovered_from=row["discovered_from"],
            iteration=row["iteration"],
            status=CandidateStatus(row["status"]),
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
        )
