"""Orkestrasi pengambilan leksikon dan pengusulan kandidat (CLAUDE.md Prioritas 8).

Dua langkah yang sengaja dipisah:

1. :func:`fetch_lexicon` mengambil entri dari satu sumber ke tabel
   ``lexicon_entries``. Entri yang masih segar dilewati, entri dari kategori
   yang dikecualikan hanya dicatat kuncinya.
2. :func:`propose_candidates` mengubah entri menjadi ``keyword_candidates``
   berstatus PENDING. Istilah yang sudah jadi keyword, sudah pernah
   diusulkan, atau pernah ditolak tidak diusulkan lagi (keputusan desain 7).

Frekuensi kandidat diisi dengan jumlah komentar layak analisis yang memuat
istilah itu, supaya reviewer bisa melihat apakah istilah kamus benar-benar
dipakai di data yang terkumpul.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ngulik.config import Config, get_logger
from ngulik.db import Database
from ngulik.keywords import KeywordError, infer_type, validate
from ngulik.lexicon.base import LexiconError, LexiconSource
from ngulik.models import (
    CandidateStatus,
    KeywordCandidate,
    LexiconEntry,
    SourceMethod,
    utc_now_iso,
)

__all__ = ["FetchStats", "ProposeStats", "fetch_lexicon", "propose_candidates"]

logger = get_logger("lexicon.runner")

#: ``progress(selesai, total)`` untuk bilah progres di CLI.
ProgressCallback = Callable[[int, int], None]


@dataclass(slots=True)
class FetchStats:
    listed: int = 0
    fetched: int = 0
    fresh_skipped: int = 0
    excluded: int = 0
    failed: int = 0
    stored: int = 0


@dataclass(slots=True)
class ProposeStats:
    created: int = 0
    already_keyword: int = 0
    already_candidate: int = 0
    invalid: int = 0


def fetch_lexicon(
    config: Config,
    db: Database,
    source: LexiconSource,
    *,
    limit: int | None = None,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
) -> FetchStats:
    """Ambil entri dari ``source`` ke ``lexicon_entries``."""
    settings = config.section("lexicon")
    limit = limit or int(settings.get("max_entries_per_run", 200))
    excluded_categories = {
        str(c).casefold() for c in settings.get("exclude_categories", []) or []
    }
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=float(settings.get("refetch_after_days", 30)))
    ).replace(microsecond=0).isoformat()

    stats = FetchStats()
    urls = source.list_entry_urls()
    stats.listed = len(urls)

    fetched_at = {
        row["entry_key"]: row["fetched_at"]
        for row in db.query(
            "SELECT entry_key, fetched_at FROM lexicon_entries WHERE source = ?",
            (source.name,),
        )
    }

    todo: list[str] = []
    for url in urls:
        key = source.entry_key(url)
        last = fetched_at.get(key) or fetched_at.get(_hashed_key(key))
        if not refresh and last is not None and last >= cutoff:
            stats.fresh_skipped += 1
        else:
            todo.append(url)
    todo = todo[:limit]

    logger.info(
        "Lexicon %s: %d entries listed, %d still fresh, %d to fetch",
        source.name, stats.listed, stats.fresh_skipped, len(todo),
    )

    for index, url in enumerate(todo, start=1):
        try:
            entry = source.fetch_entry(url)
        except LexiconError as exc:
            stats.failed += 1
            logger.warning("%s", exc)
            entry = None
        else:
            stats.fetched += 1

        if entry is not None:
            if (entry.category or "").casefold() in excluded_categories:
                # Entri yang dulu tersimpan utuh lalu pindah kategori.
                db.execute(
                    "DELETE FROM lexicon_entries WHERE source = ? AND entry_key = ?",
                    (entry.source, entry.entry_key),
                )
                entry = _excluded_stub(entry)
                stats.excluded += 1
            _store_entry(db, entry)
            stats.stored += not entry.excluded
            if index % 20 == 0:
                db.commit()

        if progress is not None:
            progress(index, len(todo))

    db.commit()
    return stats


def propose_candidates(
    config: Config,
    db: Database,
    *,
    source: str | None = None,
    iteration: int | None = None,
) -> ProposeStats:
    """Usulkan entri leksikon sebagai kandidat keyword berstatus PENDING."""
    iteration = db.current_iteration() if iteration is None else iteration
    respect_rejections = bool(
        config.get("discovery.respect_previous_rejections", True)
    )

    sql = "SELECT * FROM lexicon_entries WHERE excluded = 0 AND term IS NOT NULL"
    params: list[object] = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    entries = db.query(sql + " ORDER BY id", params)

    keywords = {row["term"] for row in db.query("SELECT term FROM keywords")}
    candidate_status: dict[str, set[str]] = {}
    for row in db.query("SELECT term, status FROM keyword_candidates"):
        candidate_status.setdefault(row["term"], set()).add(row["status"])

    corpus = [
        row["text_clean"]
        for row in db.query(
            "SELECT text_clean FROM cleaned_comments "
            "WHERE is_duplicate = 0 AND is_spam = 0"
        )
    ]

    stats = ProposeStats()
    for row in entries:
        try:
            keyword_type = infer_type(row["term"])
            term = validate(row["term"], keyword_type)
        except KeywordError as exc:
            logger.debug("Lexicon term skipped %r: %s", row["term"], exc)
            stats.invalid += 1
            continue

        if term in keywords:
            stats.already_keyword += 1
            continue
        statuses = candidate_status.get(term, set())
        if statuses - {str(CandidateStatus.REJECTED)} or (
            respect_rejections and statuses
        ):
            stats.already_candidate += 1
            continue

        candidate = KeywordCandidate(
            term=term,
            type=keyword_type,
            source_method=str(SourceMethod.LEXICON),
            frequency=_document_frequency(term, corpus),
            discovered_from=row["url"],
            iteration=iteration,
        )
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO keyword_candidates
                (term, type, source_method, frequency, score, discovered_from,
                 iteration, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate.term, str(candidate.type), candidate.source_method,
             candidate.frequency, candidate.score, candidate.discovered_from,
             candidate.iteration, str(candidate.status), candidate.created_at),
        )
        if cursor.rowcount:
            stats.created += 1
            candidate_status.setdefault(term, set()).add(str(CandidateStatus.PENDING))
        else:
            stats.already_candidate += 1

    db.commit()
    logger.info(
        "Lexicon candidates: %d new, %d already keywords, %d already proposed",
        stats.created, stats.already_keyword, stats.already_candidate,
    )
    return stats


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _hashed_key(entry_key: str) -> str:
    return "sha1:" + hashlib.sha1(entry_key.encode("utf-8"), usedforsecurity=False).hexdigest()


def _excluded_stub(entry: LexiconEntry) -> LexiconEntry:
    """Buang semua isi entri yang dikecualikan, sisakan hash kunci dan kategori.

    Slug dan URL entri "Nama Orang" memuat nama orang itu sendiri, jadi ikut
    di-hash. Yang tersisa cukup untuk tahu entri ini sudah pernah dilihat.
    """
    hashed = _hashed_key(entry.entry_key)
    return LexiconEntry(
        source=entry.source,
        entry_key=hashed,
        url=hashed,
        category=entry.category,
        excluded=True,
    )


def _store_entry(db: Database, entry: LexiconEntry) -> None:
    db.execute(
        """
        INSERT INTO lexicon_entries
            (source, entry_key, url, term, category, definition, example,
             excluded, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, entry_key) DO UPDATE SET
            url = excluded.url,
            term = excluded.term,
            category = excluded.category,
            definition = excluded.definition,
            example = excluded.example,
            excluded = excluded.excluded,
            fetched_at = excluded.fetched_at
        """,
        (entry.source, entry.entry_key, entry.url, entry.term, entry.category,
         entry.definition, entry.example, int(entry.excluded), utc_now_iso()),
    )


def _document_frequency(term: str, corpus: list[str]) -> int:
    """Jumlah komentar yang memuat ``term`` sebagai kata utuh."""
    if not corpus:
        return 0
    pattern = re.compile(rf"(?<!\w){re.escape(term.lstrip('#'))}(?!\w)")
    return sum(1 for text in corpus if pattern.search(text))
