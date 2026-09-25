"""Penyaringan spam (FR-004, PRD bagian 22).

Dua tingkat pemeriksaan:

**Per komentar** (:class:`SpamFilter`). Aturan murah yang cukup melihat satu
komentar: jumlah URL, mention, hashtag, nomor telepon, deret karakter
identik, jumlah token, dan keragaman token. Hitungan URL/mention/hashtag
dilakukan pada teks MENTAH, karena normalisasi sudah membuang semuanya.

**Lintas korpus** (:func:`mark_copypasta`). Teks identik yang dikirim dari
banyak ``source_id`` berbeda adalah pola spam bot, dan hanya bisa dikenali
setelah seluruh komentar punya ``norm_hash``.

Hasilnya adalah alasan yang spesifik, bukan sekadar boolean, supaya kolom
``spam_reason`` bisa diaudit dan ambangnya bisa disetel dari data.
"""

from __future__ import annotations

from collections.abc import Sequence

from ngulik.cleaning.normalize import (
    count_hashtags,
    count_mentions,
    count_urls,
    has_phone_number,
    longest_char_run,
)
from ngulik.config import Config, get_logger
from ngulik.db import Database

__all__ = ["COPYPASTA_REASON", "SpamFilter", "mark_copypasta", "reason_codes"]

logger = get_logger("cleaning.spam")

#: Kode alasan untuk copypasta; dipakai juga oleh laporan CLI.
COPYPASTA_REASON = "copypasta"

#: Pemisah bila satu komentar memicu beberapa aturan sekaligus.
_REASON_SEPARATOR = "; "


def reason_codes(spam_reason: str | None) -> list[str]:
    """Pecah ``spam_reason`` menjadi daftar kode aturan, mis. ``["too_many_urls"]``."""
    if not spam_reason:
        return []
    return [
        part.split(" ", 1)[0]
        for part in spam_reason.split(_REASON_SEPARATOR)
        if part
    ]


class SpamFilter:
    """Aturan spam per komentar, terkonfigurasi sekali dari section ``spam``."""

    def __init__(self, config: Config) -> None:
        settings = config.section("spam")
        self.enabled = bool(settings.get("enabled", True))
        self.max_urls = int(settings.get("max_urls", 2))
        self.max_mentions = int(settings.get("max_mentions", 5))
        self.max_hashtags = int(settings.get("max_hashtags", 5))
        self.min_tokens = int(settings.get("min_tokens_after_clean", 2))
        self.min_diversity = float(settings.get("min_token_diversity", 0.35))
        self.max_char_run = int(settings.get("max_char_run", 10))
        self.detect_phone = bool(settings.get("detect_phone_numbers", True))

    def check(
        self,
        text_raw: str,
        raw_tokens: Sequence[str],
        tokens: Sequence[str],
    ) -> str | None:
        """Kembalikan alasan spam, atau ``None`` bila komentar lolos.

        ``raw_tokens`` adalah token sebelum stopword dibuang (untuk rasio
        keragaman), ``tokens`` adalah token akhir yang masuk analisis.
        """
        if not self.enabled:
            return None

        reasons: list[str] = []

        if self.detect_phone and has_phone_number(text_raw):
            reasons.append("phone_number")

        if (urls := count_urls(text_raw)) > self.max_urls:
            reasons.append(f"too_many_urls ({urls} > {self.max_urls})")
        if (mentions := count_mentions(text_raw)) > self.max_mentions:
            reasons.append(f"too_many_mentions ({mentions} > {self.max_mentions})")
        if (hashtags := count_hashtags(text_raw)) > self.max_hashtags:
            reasons.append(f"too_many_hashtags ({hashtags} > {self.max_hashtags})")

        # Dihitung pada teks mentah: setelah normalisasi "aaaaaaaaaaaa" sudah
        # diringkas menjadi "aa" dan tidak lagi terlihat mencurigakan.
        if (run := longest_char_run(text_raw)) > self.max_char_run:
            reasons.append(f"char_run ({run} > {self.max_char_run})")

        if len(tokens) < self.min_tokens:
            reasons.append(f"too_few_tokens ({len(tokens)} < {self.min_tokens})")

        # Keragaman diukur pada token mentah. Token akhir sudah kehilangan
        # stopword, sehingga komentar pendek yang wajar akan tampak repetitif.
        if raw_tokens:
            diversity = len(set(raw_tokens)) / len(raw_tokens)
            if diversity < self.min_diversity:
                reasons.append(
                    f"low_diversity ({diversity:.2f} < {self.min_diversity:.2f})"
                )

        return _REASON_SEPARATOR.join(reasons) if reasons else None


def mark_copypasta(db: Database, config: Config) -> int:
    """Tandai teks identik dari banyak ``source_id`` berbeda sebagai spam.

    Semua salinan ikut ditandai, termasuk yang pertama muncul. Baris yang
    sudah berstatus spam tidak ditimpa alasannya. Aman dijalankan berulang.
    Mengembalikan jumlah baris yang baru ditandai.
    """
    settings = config.section("spam")
    if not settings.get("enabled", True):
        return 0
    min_authors = int(settings.get("copypasta_min_authors", 5))
    if min_authors < 2:
        return 0

    groups = db.query(
        """
        SELECT cc.norm_hash, COUNT(DISTINCT c.source_id) AS authors
          FROM cleaned_comments cc
          JOIN comments c ON c.id = cc.comment_id
         WHERE cc.norm_hash IS NOT NULL AND cc.text_clean != ''
         GROUP BY cc.norm_hash
        HAVING COUNT(DISTINCT c.source_id) >= ?
        """,
        (min_authors,),
    )

    marked = 0
    for group in groups:
        cursor = db.execute(
            """
            UPDATE cleaned_comments
               SET is_spam = 1, spam_reason = ?
             WHERE norm_hash = ? AND is_spam = 0
            """,
            (f"{COPYPASTA_REASON} ({group['authors']} >= {min_authors})",
             group["norm_hash"]),
        )
        marked += cursor.rowcount
    db.commit()

    if marked:
        logger.info(
            "Copypasta: %d comments marked as spam across %d identical texts",
            marked, len(groups),
        )
    return marked
