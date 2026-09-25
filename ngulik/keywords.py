"""Manajemen seed keyword (FR-001) — AC-001.

Keyword hidup di dua tempat yang saling melengkapi:

* ``config/keywords.yaml`` — seed awal yang ditulis manusia, ramah untuk
  di-commit dan di-review.
* tabel ``keywords`` — sumber kebenaran saat runtime, tempat keyword hasil
  approve dari iterasi berikutnya ikut tersimpan lengkap dengan jejak
  ``discovered_from`` dan ``iteration`` (PRD bagian 10).

Import dari YAML bersifat idempoten sehingga aman dijalankan berulang.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ngulik.config import get_logger
from ngulik.db import Database
from ngulik.models import Keyword, KeywordStatus, KeywordType, utc_now_iso

logger = get_logger("keywords")

MAX_TERM_LENGTH = 120
_WHITESPACE = re.compile(r"\s+")
# Karakter kontrol tidak pernah sah di dalam sebuah keyword.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class KeywordError(ValueError):
    """Keyword tidak lolos validasi."""


# ---------------------------------------------------------------------------
# Validasi & normalisasi
# ---------------------------------------------------------------------------


def normalize_term(term: str) -> str:
    """Rapikan sebuah term menjadi bentuk kanonik untuk disimpan.

    Di-lowercase agar konsisten dengan pipeline cleaning (yang juga
    lowercase), sehingga pencocokan keyword tidak pernah meleset hanya karena
    beda kapitalisasi.
    """
    if term is None:
        raise KeywordError("Keyword must not be None")
    cleaned = _CONTROL_CHARS.sub("", str(term))
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned.lower()


def infer_type(term: str) -> KeywordType:
    """Tebak tipe keyword dari bentuknya.

    Diawali ``#`` berarti hashtag; mengandung spasi berarti frasa; selain itu
    keyword biasa.
    """
    normalized = normalize_term(term)
    if normalized.startswith("#"):
        return KeywordType.HASHTAG
    if " " in normalized:
        return KeywordType.PHRASE
    return KeywordType.KEYWORD


def validate(term: str, keyword_type: KeywordType) -> str:
    """Validasi sebuah term terhadap tipenya, kembalikan bentuk kanonik.

    Melempar :class:`KeywordError` bila tidak lolos.
    """
    normalized = normalize_term(term)

    if not normalized:
        raise KeywordError("Keyword must not be empty")
    if len(normalized) > MAX_TERM_LENGTH:
        raise KeywordError(
            f"Keyword too long ({len(normalized)} characters, "
            f"maximum {MAX_TERM_LENGTH})"
        )

    match keyword_type:
        case KeywordType.HASHTAG:
            if not normalized.startswith("#"):
                normalized = f"#{normalized}"
            if " " in normalized:
                raise KeywordError(f"Hashtag must not contain spaces: {normalized!r}")
            if len(normalized) < 2:
                raise KeywordError("Hashtag needs text after '#'")
        case KeywordType.PHRASE:
            if " " not in normalized:
                raise KeywordError(
                    f"A PHRASE must have several words: {normalized!r}. "
                    f"Use type KEYWORD for a single word."
                )
        case KeywordType.KEYWORD:
            if " " in normalized:
                raise KeywordError(
                    f"A KEYWORD must not contain spaces: {normalized!r}. "
                    f"Use type PHRASE for phrases."
                )
            if normalized.startswith("#"):
                raise KeywordError(
                    f"A term starting with '#' should be a HASHTAG: {normalized!r}"
                )

    return normalized


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class KeywordManager:
    """Operasi CRUD atas tabel ``keywords``."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -- create -------------------------------------------------------------

    def add(
        self,
        term: str,
        keyword_type: KeywordType | str | None = None,
        *,
        iteration: int = 0,
        discovered_from: str | None = None,
        status: KeywordStatus = KeywordStatus.ACTIVE,
    ) -> tuple[Keyword, bool]:
        """Tambah satu keyword.

        Mengembalikan ``(keyword, created)``. Bila term sudah ada, baris lama
        dikembalikan apa adanya tanpa menimpa provenance-nya — jejak penemuan
        pertama lebih berharga daripada yang terakhir.
        """
        resolved_type = (
            infer_type(term)
            if keyword_type is None
            else KeywordType(str(keyword_type).upper())
        )
        normalized = validate(term, resolved_type)

        existing = self.get(normalized, resolved_type)
        if existing is not None:
            return existing, False

        now = utc_now_iso()
        cursor = self.db.execute(
            """
            INSERT INTO keywords
                (term, type, status, iteration, discovered_from, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized,
                str(resolved_type),
                str(status),
                iteration,
                discovered_from,
                now,
                now,
            ),
        )
        self.db.commit()

        keyword = Keyword(
            id=cursor.lastrowid,
            term=normalized,
            type=resolved_type,
            status=status,
            iteration=iteration,
            discovered_from=discovered_from,
            created_at=now,
            updated_at=now,
        )
        logger.debug("Keyword added: %s (%s)", normalized, resolved_type)
        return keyword, True

    def add_many(self, terms: list[str]) -> tuple[int, int]:
        """Tambah banyak keyword sekaligus, tipe ditebak otomatis.

        Mengembalikan ``(jumlah_baru, jumlah_dilewati)``.
        """
        created = skipped = 0
        for term in terms:
            try:
                _, was_created = self.add(term)
            except KeywordError as exc:
                logger.warning("Skipping %r: %s", term, exc)
                skipped += 1
                continue
            created += was_created
            skipped += not was_created
        return created, skipped

    # -- read ---------------------------------------------------------------

    def get(self, term: str, keyword_type: KeywordType | None = None) -> Keyword | None:
        normalized = normalize_term(term)
        if keyword_type is None:
            row = self.db.query_one(
                "SELECT * FROM keywords WHERE term = ?", (normalized,)
            )
        else:
            row = self.db.query_one(
                "SELECT * FROM keywords WHERE term = ? AND type = ?",
                (normalized, str(keyword_type)),
            )
        return Keyword.from_row(row) if row else None

    def list(
        self,
        *,
        status: KeywordStatus | None = KeywordStatus.ACTIVE,
        keyword_type: KeywordType | None = None,
        iteration: int | None = None,
    ) -> list[Keyword]:
        sql = "SELECT * FROM keywords WHERE 1=1"
        params: list[object] = []
        if status is not None:
            sql += " AND status = ?"
            params.append(str(status))
        if keyword_type is not None:
            sql += " AND type = ?"
            params.append(str(keyword_type))
        if iteration is not None:
            sql += " AND iteration = ?"
            params.append(iteration)
        sql += " ORDER BY iteration ASC, type ASC, term ASC"
        return [Keyword.from_row(row) for row in self.db.query(sql, params)]

    def active_terms(self) -> list[str]:
        """Term aktif saja — inilah yang dipakai collector sebagai query."""
        return [k.term for k in self.list(status=KeywordStatus.ACTIVE)]

    def count(self, *, status: KeywordStatus | None = KeywordStatus.ACTIVE) -> int:
        if status is None:
            return int(self.db.scalar("SELECT COUNT(*) FROM keywords", default=0))
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM keywords WHERE status = ?",
                (str(status),),
                default=0,
            )
        )

    # -- update -------------------------------------------------------------

    def rename(self, old_term: str, new_term: str) -> Keyword:
        keyword = self.get(old_term)
        if keyword is None:
            raise KeywordError(f"Keyword not found: {old_term!r}")

        new_type = infer_type(new_term)
        normalized = validate(new_term, new_type)
        if self.get(normalized, new_type) is not None:
            raise KeywordError(f"Keyword {normalized!r} already exists")

        now = utc_now_iso()
        self.db.execute(
            "UPDATE keywords SET term = ?, type = ?, updated_at = ? WHERE id = ?",
            (normalized, str(new_type), now, keyword.id),
        )
        self.db.commit()
        keyword.term, keyword.type, keyword.updated_at = normalized, new_type, now
        return keyword

    def set_status(self, term: str, status: KeywordStatus) -> Keyword:
        keyword = self.get(term)
        if keyword is None:
            raise KeywordError(f"Keyword not found: {term!r}")
        now = utc_now_iso()
        self.db.execute(
            "UPDATE keywords SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), now, keyword.id),
        )
        self.db.commit()
        keyword.status, keyword.updated_at = status, now
        return keyword

    # -- delete -------------------------------------------------------------

    def remove(self, term: str, *, hard: bool = False) -> bool:
        """Hapus keyword.

        Default-nya soft delete (status ``INACTIVE``) agar komentar yang sudah
        terkumpul tetap punya jejak keyword asalnya. ``hard=True`` menghapus
        barisnya sungguhan.
        """
        keyword = self.get(term)
        if keyword is None:
            return False
        if hard:
            self.db.execute("DELETE FROM keywords WHERE id = ?", (keyword.id,))
        else:
            self.db.execute(
                "UPDATE keywords SET status = 'INACTIVE', updated_at = ? WHERE id = ?",
                (utc_now_iso(), keyword.id),
            )
        self.db.commit()
        return True

    # -- YAML ---------------------------------------------------------------

    def import_yaml(self, path: Path) -> dict[str, int]:
        """Muat ``config/keywords.yaml`` ke database. Idempoten.

        Struktur yang diharapkan (PRD FR-001)::

            keywords:  [kata_a, kata_b]
            phrases:   ["frasa tertentu"]
            hashtags:  ["#contoh"]
        """
        if not path.is_file():
            raise FileNotFoundError(f"Keyword file not found: {path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise KeywordError(f"{path} must be a YAML mapping")

        sections: list[tuple[str, KeywordType]] = [
            ("keywords", KeywordType.KEYWORD),
            ("phrases", KeywordType.PHRASE),
            ("hashtags", KeywordType.HASHTAG),
        ]

        summary = {"created": 0, "existing": 0, "invalid": 0}
        for section, keyword_type in sections:
            entries = raw.get(section) or []
            if not isinstance(entries, list):
                logger.warning("Section %r in %s is not a list, skipped", section, path.name)
                continue
            for entry in entries:
                try:
                    _, created = self.add(str(entry), keyword_type)
                except KeywordError as exc:
                    logger.warning("Skipping %r: %s", entry, exc)
                    summary["invalid"] += 1
                    continue
                summary["created" if created else "existing"] += 1

        logger.info(
            "Keyword import from %s: %d new, %d existing, %d invalid",
            path.name,
            summary["created"],
            summary["existing"],
            summary["invalid"],
        )
        return summary

    def export_yaml(self, path: Path) -> dict[str, int]:
        """Tulis keyword aktif kembali ke berkas YAML.

        Berguna setelah beberapa iterasi: keyword hasil approve ikut turun ke
        berkas sehingga seed bisa di-commit dan dibagikan.
        """
        buckets: dict[str, list[str]] = {"keywords": [], "phrases": [], "hashtags": []}
        section_of = {
            KeywordType.KEYWORD: "keywords",
            KeywordType.PHRASE: "phrases",
            KeywordType.HASHTAG: "hashtags",
        }
        for keyword in self.list(status=KeywordStatus.ACTIVE):
            buckets[section_of[keyword.type]].append(keyword.term)

        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Seed keywords — dihasilkan oleh `ngulik keyword export`.\n"
            "# Memuat seed awal dan keyword hasil approve dari iterasi berikutnya.\n\n"
        )
        body = yaml.safe_dump(buckets, allow_unicode=True, sort_keys=False, width=100)
        path.write_text(header + body, encoding="utf-8")

        return {name: len(items) for name, items in buckets.items()}
