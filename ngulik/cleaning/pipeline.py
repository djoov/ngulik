"""Orkestrator cleaning: ``comments`` -> ``cleaned_comments`` (FR-004, FR-005).

Menutup AC-004 dan AC-005. Urutan per komentar::

    normalize -> tokenize -> spam -> dedup -> simpan CleanedComment

lalu satu langkah lintas korpus di akhir: :func:`~ngulik.cleaning.spam.mark_copypasta`.

Mode default bersifat inkremental: hanya komentar yang belum punya baris di
``cleaned_comments`` yang diproses, dan state deteksi duplikat dimuat dari
hasil sebelumnya. Mode ``reprocess`` mengosongkan ``cleaned_comments`` lalu
memproses ulang semuanya dari raw dataset (NFR-002), misalnya setelah kamus
slang atau ambang spam diubah.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ngulik.cleaning.dedup import DuplicateDetector
from ngulik.cleaning.normalize import normalize_text
from ngulik.cleaning.spam import SpamFilter, mark_copypasta, reason_codes
from ngulik.cleaning.tokenize import Tokenizer
from ngulik.config import Config, get_logger
from ngulik.db import Database, dumps
from ngulik.models import CleanedComment

__all__ = ["CleaningPipeline", "CleaningStats"]

logger = get_logger("cleaning.pipeline")


@dataclass(slots=True)
class CleaningStats:
    """Ringkasan satu kali jalan cleaning, untuk laporan CLI."""

    processed: int = 0
    duplicates: int = 0
    spam: int = 0
    copypasta: int = 0
    reprocessed: bool = False
    spam_by_rule: dict[str, int] = field(default_factory=dict)


class CleaningPipeline:
    """Menjalankan cleaning atas komentar mentah dan menyimpan hasilnya."""

    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db
        self.normalize_settings = config.section("cleaning")
        self.tokenizer = Tokenizer(config)
        self.spam_filter = SpamFilter(config)
        self.detector = DuplicateDetector(config)
        self.batch_size = int(config.get("cleaning.batch_size", 500))

    # -- publik -------------------------------------------------------------

    def run(self, *, reprocess: bool = False) -> CleaningStats:
        """Proses komentar yang belum dibersihkan. ``reprocess`` memulai dari nol."""
        stats = CleaningStats(reprocessed=reprocess)

        if reprocess:
            self.db.execute("DELETE FROM cleaned_comments")
            self.db.commit()
            self.detector.reset()
            logger.info("Reprocess mode: cleaned_comments cleared")
        else:
            self._prime_detector()

        # Diambil sekaligus, bukan lewat kursor yang terbuka, karena tabel
        # cleaned_comments ditulisi selama iterasi dan ikut ter-JOIN di query.
        rows = self.db.query(
            """
            SELECT c.id, c.text_raw
              FROM comments c
              LEFT JOIN cleaned_comments cc ON cc.comment_id = c.id
             WHERE cc.id IS NULL
             ORDER BY c.id
            """
        )
        logger.info("Cleaning %d comments", len(rows))

        batch: list[CleanedComment] = []
        for row in rows:
            cleaned = self.clean_one(row["id"], row["text_raw"])
            stats.processed += 1
            if cleaned.is_duplicate:
                stats.duplicates += 1
            if cleaned.is_spam:
                stats.spam += 1
                for code in reason_codes(cleaned.spam_reason):
                    stats.spam_by_rule[code] = stats.spam_by_rule.get(code, 0) + 1
            batch.append(cleaned)
            if len(batch) >= self.batch_size:
                self._write(batch)
                batch.clear()
        if batch:
            self._write(batch)

        stats.copypasta = mark_copypasta(self.db, self.config)
        logger.info(
            "Cleaning done: %d processed, %d duplicates, %d spam, %d copypasta",
            stats.processed, stats.duplicates, stats.spam, stats.copypasta,
        )
        return stats

    def clean_one(self, comment_id: int, text_raw: str) -> CleanedComment:
        """Bersihkan satu komentar tanpa menyentuh database.

        Komentar spam tetap diperiksa duplikasinya supaya ``norm_hash`` terisi;
        hash itulah yang dipakai deteksi copypasta.
        """
        text_clean = normalize_text(text_raw, self.normalize_settings)
        tokens = self.tokenizer(text_clean)
        raw_tokens = self.tokenizer.raw_tokens(text_clean)
        spam_reason = self.spam_filter.check(text_raw, raw_tokens, tokens)
        is_duplicate, duplicate_of, norm_hash, simhash_hex = self.detector.check(
            comment_id, text_clean, tokens
        )
        return CleanedComment(
            comment_id=comment_id,
            text_clean=text_clean,
            tokens=tokens,
            is_duplicate=is_duplicate,
            duplicate_of=duplicate_of,
            is_spam=spam_reason is not None,
            spam_reason=spam_reason,
            norm_hash=norm_hash,
            simhash=simhash_hex,
        )

    # -- internal -----------------------------------------------------------

    def _prime_detector(self) -> None:
        """Muat komentar asli dari run sebelumnya ke detektor duplikat."""
        rows = self.db.query(
            """
            SELECT comment_id, norm_hash, simhash
              FROM cleaned_comments
             WHERE is_duplicate = 0 AND norm_hash IS NOT NULL
             ORDER BY comment_id
            """
        )
        for row in rows:
            self.detector.register(row["comment_id"], row["norm_hash"], row["simhash"])
        if rows:
            logger.debug("Duplicate detector primed with %d earlier comments", len(rows))

    def _write(self, batch: list[CleanedComment]) -> None:
        with self.db.transaction():
            self.db.executemany(
                """
                INSERT INTO cleaned_comments
                    (comment_id, text_clean, tokens, language, is_duplicate,
                     duplicate_of, is_spam, spam_reason, norm_hash, simhash,
                     processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.comment_id,
                        item.text_clean,
                        dumps(item.tokens),
                        item.language,
                        int(item.is_duplicate),
                        item.duplicate_of,
                        int(item.is_spam),
                        item.spam_reason,
                        item.norm_hash,
                        item.simhash,
                        item.processed_at,
                    )
                    for item in batch
                ],
            )
