"""Tautkan komentar ke keyword di database yang teksnya dimuat komentar itu.

Tabel ``comment_keywords`` hanya mencatat keyword *pemicu pencarian*.
Komentar dari video pilihan atau dari berkas tidak punya pemicu, padahal
pengguna tetap ingin tahu komentar mana yang memuat kata yang sudah dikenal,
termasuk kata slang dari kamus yang sudah disetujui. Modul ini mengisi
``comment_keyword_matches`` untuk kebutuhan itu.

Pencocokan dilakukan pada teks yang dinormalisasi dengan aturan yang sama
seperti cleaning (huruf kecil, ``#gabut`` menjadi ``gabut``, spasi dirapatkan),
sebagai kata utuh: ``rek`` cocok dengan "ayo rek" tapi tidak dengan "rekam".
Teks dipecah menjadi token, lalu setiap rangkaian 1..N token dicari di
himpunan keyword. Dengan begitu kecocokan yang tumpang tindih ikut tertangkap:
"mas mas gabut" tertaut ke frasa itu sekaligus ke keyword ``gabut``, hal yang
tidak bisa dilakukan satu regex gabungan.

Tabel dibangun ulang utuh setiap kali, sehingga keyword yang baru
dipromosikan ikut tercocokkan ke komentar lama, dan keyword yang dinonaktifkan
hilang dari hasil. Komentar mentah tidak diubah (FR-003).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ngulik.cleaning.normalize import normalize_text
from ngulik.cleaning.tokenize import tokenize
from ngulik.config import Config, get_logger
from ngulik.db import Database

__all__ = ["MatchStats", "find_terms", "match_keywords"]

logger = get_logger("matching")


@dataclass(slots=True)
class MatchStats:
    keywords: int = 0
    comments_scanned: int = 0
    comments_matched: int = 0
    links: int = 0


def find_terms(tokens: list[str], terms: set[str], max_words: int) -> set[str]:
    """Semua term (bentuk token dipisah spasi) yang muncul sebagai n-gram di ``tokens``."""
    found: set[str] = set()
    for size in range(1, max_words + 1):
        for start in range(len(tokens) - size + 1):
            gram = " ".join(tokens[start:start + size])
            if gram in terms:
                found.add(gram)
    return found


def match_keywords(config: Config, db: Database) -> MatchStats:
    """Bangun ulang ``comment_keyword_matches`` dari seluruh komentar."""
    settings = config.section("cleaning")
    by_text: dict[str, list[int]] = defaultdict(list)
    for row in db.query("SELECT id, term FROM keywords WHERE status = 'ACTIVE'"):
        # Hashtag dicocokkan lewat teksnya, karena normalisasi membuang '#'.
        text = " ".join(tokenize(normalize_text(row["term"].lstrip("#"), settings)))
        if text:
            by_text[text].append(row["id"])

    stats = MatchStats(keywords=sum(len(ids) for ids in by_text.values()))
    db.execute("DELETE FROM comment_keyword_matches")

    if not by_text:
        db.commit()
        return stats
    terms = set(by_text)
    max_words = max(term.count(" ") + 1 for term in terms)

    batch: list[tuple[int, int]] = []
    for row in db.query("SELECT id, text_raw FROM comments"):
        stats.comments_scanned += 1
        tokens = tokenize(normalize_text(row["text_raw"], settings))
        found = find_terms(tokens, terms, max_words)
        if not found:
            continue
        stats.comments_matched += 1
        for text in found:
            batch.extend((row["id"], keyword_id) for keyword_id in by_text[text])

    db.executemany(
        "INSERT OR IGNORE INTO comment_keyword_matches (comment_id, keyword_id) VALUES (?, ?)",
        batch,
    )
    db.commit()
    stats.links = len(batch)
    logger.info(
        "Keyword match: %d of %d comments contain at least one of %d keywords",
        stats.comments_matched, stats.comments_scanned, stats.keywords,
    )
    return stats
