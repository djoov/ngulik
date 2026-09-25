"""Kontrak collector dan orkestrasi collection run (FR-002, FR-003).

Seluruh sumber data mengimplementasikan :class:`Collector` dan menghasilkan
:class:`~ngulik.models.RawComment` dengan bentuk yang sama. Inilah batas yang
menjaga NFR-004: menambah sumber baru cukup menulis satu adapter, tanpa
menyentuh apa pun di lapisan cleaning maupun analisis.

:func:`run_collection` menangani hal-hal yang berlaku untuk semua sumber —
pencatatan run, penyimpanan raw yang idempoten, penautan ke seed keyword, dan
penanganan kuota habis — supaya tiap adapter tetap tipis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ngulik.config import Config, get_logger
from ngulik.db import Database, dumps
from ngulik.models import CollectionRun, RawComment, RunStatus, utc_now_iso

if TYPE_CHECKING:
    from ngulik.keywords import KeywordManager

logger = get_logger("collectors")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CollectorError(RuntimeError):
    """Kegagalan umum pada collector."""


class CollectorNotConfigured(CollectorError):
    """Collector belum siap dipakai (mis. API key belum diisi)."""


class QuotaExceeded(CollectorError):
    """Kuota API habis.

    Dibedakan dari error lain karena artinya bukan "gagal", melainkan
    "berhenti lebih awal": data yang sudah terkumpul tetap sah dan run
    ditandai PARTIAL, bukan FAILED.
    """


# ---------------------------------------------------------------------------
# Kontrak
# ---------------------------------------------------------------------------


class Collector(ABC):
    """Basis untuk semua adapter sumber data.

    Kewajiban subclass hanya dua: mengisi atribut kelas :attr:`name`, dan
    mengimplementasikan :meth:`collect` sebagai generator
    :class:`~ngulik.models.RawComment`.

    Bentuk generator dipilih agar komentar bisa disimpan secara bertahap.
    Kalau kuota habis atau jaringan putus di tengah jalan, apa yang sudah
    sempat ditarik tidak ikut hilang.
    """

    name: str = "base"
    #: Ditampilkan di `ngulik collect --help` dan `ngulik status`.
    description: str = ""
    #: False bila collector bisa jalan tanpa seed keyword (mis. video pilihan).
    needs_keywords: bool = True

    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db
        self.quota_used = 0

    @abstractmethod
    def collect(self, keywords: list[str], limit: int) -> Iterator[RawComment]:
        """Hasilkan komentar untuk ``keywords``, maksimum ``limit`` buah."""
        raise NotImplementedError

    def check_ready(self) -> None:
        """Pastikan collector siap dipakai.

        Lempar :class:`CollectorNotConfigured` bila belum. Dipanggil sebelum
        run dibuat, supaya konfigurasi yang salah tidak meninggalkan run
        gantung berstatus RUNNING.
        """
        return None

    def run_params(self) -> dict[str, object]:
        """Parameter yang disimpan ke ``collection_runs.params`` (NFR-002)."""
        return {}

    def run_stats(self) -> dict[str, object]:
        """Statistik akhir run, digabung ke ``collection_runs.params`` saat run ditutup.

        Berbeda dari :meth:`run_params` yang diambil di awal, nilai di sini baru
        diketahui setelah collect selesai, mis. jumlah call ``search.list``.
        """
        return {}

    def __repr__(self) -> str:  # pragma: no cover - diagnostik
        return f"<{type(self).__name__} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Orkestrasi
# ---------------------------------------------------------------------------


def run_collection(
    config: Config,
    db: Database,
    collector: Collector,
    keywords: list[str],
    *,
    limit: int = 500,
    iteration: int = 0,
    keyword_manager: "KeywordManager | None" = None,
) -> CollectionRun:
    """Jalankan satu collection run dari ujung ke ujung.

    Menangani: pembuatan baris run, penyimpanan raw yang idempoten, penautan
    komentar ke seed keyword, penghitungan kuota, dan penutupan run dengan
    status yang tepat.

    Komentar disimpan dengan ``INSERT OR IGNORE`` pada ``UNIQUE(source,
    source_id)``, sehingga menjalankan collection dua kali dengan keyword yang
    sama tidak menggandakan data.
    """
    collector.check_ready()

    if not keywords and collector.needs_keywords:
        raise CollectorError(
            "No active keywords. Add some first with "
            "`ngulik keyword add` or `ngulik keyword import`."
        )

    run = CollectionRun(
        source=collector.name,
        iteration=iteration,
        keyword_count=len(keywords),
        params={"limit": limit, "keywords": keywords, **collector.run_params()},
    )
    cursor = db.execute(
        """
        INSERT INTO collection_runs
            (source, iteration, started_at, keyword_count, status, params)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run.source, run.iteration, run.started_at, run.keyword_count,
         str(RunStatus.RUNNING), dumps(run.params)),
    )
    run.id = cursor.lastrowid
    db.commit()

    logger.info(
        "Collection run #%d started — source=%s, keywords=%d, limit=%d",
        run.id, collector.name, len(keywords), limit,
    )

    keyword_ids = _keyword_id_map(db) if keyword_manager is not None else {}
    stored = duplicates = 0
    status = RunStatus.SUCCESS
    error: str | None = None

    try:
        for comment in collector.collect(keywords, limit):
            was_new = _store_comment(db, comment, run.id, keyword_ids)
            stored += was_new
            duplicates += not was_new
            if stored and stored % 100 == 0:
                db.commit()
                logger.debug("… %d new comments stored", stored)

    except QuotaExceeded as exc:
        status = RunStatus.PARTIAL
        error = str(exc)
        logger.warning("Quota exhausted, run stopped early: %s", exc)

    except KeyboardInterrupt:
        status = RunStatus.PARTIAL
        error = "Stopped by user (Ctrl+C)"
        logger.warning("Collection stopped by user")

    except Exception as exc:  # noqa: BLE001 - dicatat lalu dilaporkan ke CLI
        status = RunStatus.FAILED
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("Collection run #%d failed", run.id)

    finally:
        db.commit()

    run.comments_collected = stored
    run.quota_used = collector.quota_used
    run.status = status
    run.error = error
    run.finished_at = utc_now_iso()
    run.params.update(collector.run_stats())

    db.execute(
        """
        UPDATE collection_runs
           SET finished_at = ?, comments_collected = ?, status = ?,
               error = ?, quota_used = ?, params = ?
         WHERE id = ?
        """,
        (run.finished_at, stored, str(status), error, collector.quota_used,
         dumps(run.params), run.id),
    )
    db.commit()

    logger.info(
        "Collection run #%d finished — status=%s, new=%d, duplicates skipped=%d, quota=%d",
        run.id, status, stored, duplicates, collector.quota_used,
    )
    return run


def _keyword_id_map(db: Database) -> dict[str, int]:
    """Peta term -> id untuk menautkan komentar ke seed keyword."""
    return {row["term"]: row["id"] for row in db.query("SELECT id, term FROM keywords")}


def _store_comment(
    db: Database,
    comment: RawComment,
    run_id: int | None,
    keyword_ids: dict[str, int],
) -> bool:
    """Simpan satu komentar mentah. ``True`` bila benar-benar baru.

    Tabel ``comments`` bersifat append-only (FR-003): tidak ada jalur kode di
    sini yang meng-UPDATE atau meng-DELETE-nya.
    """
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO comments
            (source, source_id, text_raw, author_id, url, created_at, collected_at, run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            comment.source,
            comment.source_id,
            comment.text,
            comment.author_id,
            comment.url,
            comment.created_at,
            utc_now_iso(),
            run_id,
        ),
    )

    is_new = cursor.rowcount > 0
    if is_new:
        comment_id = cursor.lastrowid
    else:
        row = db.query_one(
            "SELECT id FROM comments WHERE source = ? AND source_id = ?",
            (comment.source, comment.source_id),
        )
        comment_id = row["id"] if row else None

    # Tautkan ke seed keyword yang memunculkannya, termasuk untuk komentar
    # yang sudah ada — satu komentar bisa ditemukan oleh beberapa keyword.
    if comment_id is not None and comment.keyword:
        keyword_id = keyword_ids.get(comment.keyword)
        if keyword_id is not None:
            db.execute(
                "INSERT OR IGNORE INTO comment_keywords (comment_id, keyword_id) "
                "VALUES (?, ?)",
                (comment_id, keyword_id),
            )

    return is_new
