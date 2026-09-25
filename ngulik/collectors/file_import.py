"""Collector berbasis berkas — JSON / JSONL / CSV.

Ada dua alasan collector ini penting, bukan sekadar pelengkap:

1. **Pipeline bisa dikembangkan dan diuji tanpa API key.** Cleaning, analisis,
   dan discovery (Phase 3-5) seluruhnya bisa dijalankan atas dataset lokal.
2. **Ia membuktikan abstraksi NFR-004 benar-benar bekerja.** Dua adapter
   dengan karakter yang sangat berbeda — satu jaringan berkuota, satu berkas
   lokal — masuk ke pipeline yang sama persis tanpa cabang kode khusus.

Berguna juga untuk dataset penelitian yang sudah kamu punya dari sumber lain.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ngulik.collectors.base import Collector, CollectorError
from ngulik.config import get_logger
from ngulik.models import RawComment

logger = get_logger("collectors.file")

#: Nama kolom yang diterima untuk tiap field, diperiksa berurutan.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "text": ("text", "text_raw", "comment", "komentar", "content", "body", "message"),
    "source_id": ("source_id", "id", "comment_id", "cid"),
    "created_at": ("created_at", "published_at", "date", "timestamp", "waktu"),
    "url": ("url", "link", "permalink"),
    "source": ("source", "platform", "sumber"),
    "keyword": ("keyword", "query", "kata_kunci"),
}


def _pick(record: dict[str, Any], field: str) -> Any:
    """Ambil nilai field dari record, toleran terhadap variasi nama kolom."""
    for alias in _FIELD_ALIASES[field]:
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return None


class FileCollector(Collector):
    """Muat komentar dari berkas lokal.

    Format yang didukung, dikenali dari ekstensi:

    * ``.json``  — array objek, atau objek dengan kunci ``comments``/``items``/``data``
    * ``.jsonl`` — satu objek JSON per baris
    * ``.csv``   — baris pertama sebagai header

    Nama kolom fleksibel: ``text``/``comment``/``komentar``/``body`` semuanya
    dibaca sebagai teks komentar.
    """

    name = "file"
    description = "Import comments from a local JSON/JSONL/CSV file"
    #: Berkas tidak dicari lewat keyword, jadi boleh diimpor sebelum ada seed.
    needs_keywords = False

    def __init__(self, config, db, path: str | Path | None = None) -> None:
        super().__init__(config, db)
        self.path = Path(path) if path else None

    def check_ready(self) -> None:
        if self.path is None:
            raise CollectorError(
                "The file collector needs --path. Example:\n"
                "  python -m ngulik collect --source file "
                "--path data/fixtures/sample_comments.json"
            )
        if not self.path.is_file():
            raise CollectorError(f"File not found: {self.path}")
        if self.path.suffix.lower() not in {".json", ".jsonl", ".csv"}:
            raise CollectorError(
                f"Unsupported extension: {self.path.suffix!r}. "
                f"Use .json, .jsonl, or .csv"
            )

    def run_params(self) -> dict[str, object]:
        return {"path": str(self.path)}

    # -- pembacaan ----------------------------------------------------------

    def _read_records(self) -> list[dict[str, Any]]:
        assert self.path is not None  # dijamin oleh check_ready()
        suffix = self.path.suffix.lower()
        text = self.path.read_text(encoding="utf-8")

        if suffix == ".jsonl":
            return [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]

        if suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ("comments", "items", "data", "records"):
                    if isinstance(payload.get(key), list):
                        return payload[key]
                raise CollectorError(
                    f"{self.path.name}: a JSON object must contain a "
                    f"'comments', 'items', 'data', or 'records' array"
                )
            raise CollectorError(f"{self.path.name}: JSON must be an array or an object")

        # CSV
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    # -- kontrak collector --------------------------------------------------

    def collect(self, keywords: list[str], limit: int) -> Iterator[RawComment]:
        """Hasilkan komentar dari berkas.

        ``keywords`` di sini hanya dipakai untuk menandai asal komentar bila
        berkas tidak menyertakan kolom ``keyword``; berkas TIDAK difilter
        berdasarkan keyword. Menyaring dataset lokal agar hanya memuat kata
        yang sudah diketahui akan mematikan tujuan discovery.
        """
        records = self._read_records()
        logger.info("Read %d records from %s", len(records), self.path)

        emitted = skipped = 0

        for index, record in enumerate(records):
            if emitted >= limit:
                logger.info("Limit %d reached, remaining records skipped", limit)
                break
            if not isinstance(record, dict):
                skipped += 1
                continue

            text = _pick(record, "text")
            if not text or not str(text).strip():
                skipped += 1
                continue

            source_id = _pick(record, "source_id") or f"{self.path.stem}:{index}"
            source = _pick(record, "source") or "file"

            yield RawComment(
                source=str(source),
                source_id=str(source_id),
                text=str(text),
                # author_id sengaja tidak pernah dibaca dari berkas:
                # PRD bagian 16, data minimization.
                author_id=None,
                created_at=_pick(record, "created_at"),
                url=_pick(record, "url"),
                # Hanya bila berkasnya sendiri mencatat keyword pemicu. Keyword
                # yang dimuat komentar dicatat terpisah oleh ngulik.matching.
                keyword=_pick(record, "keyword"),
            )
            emitted += 1

        if skipped:
            logger.info("%d records skipped because their text was empty or invalid", skipped)
