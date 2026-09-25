"""Registry collector — pemetaan nama sumber ke kelas adapter.

Satu-satunya tempat yang tahu daftar sumber yang tersedia. Menambah sumber
baru (PRD bagian 15 menyebut reddit, tiktok, x, web sebagai kemungkinan) cukup
menulis satu adapter lalu mendaftarkannya di :data:`COLLECTORS` — tidak ada
bagian lain dari sistem yang perlu berubah (NFR-004).
"""

from __future__ import annotations

from ngulik.collectors.base import Collector, CollectorError
from ngulik.collectors.file_import import FileCollector
from ngulik.collectors.youtube import YouTubeCollector
from ngulik.config import Config
from ngulik.db import Database

COLLECTORS: dict[str, type[Collector]] = {
    YouTubeCollector.name: YouTubeCollector,
    FileCollector.name: FileCollector,
}


def available() -> list[str]:
    """Nama sumber yang terdaftar."""
    return sorted(COLLECTORS)


def describe() -> dict[str, str]:
    """Nama sumber beserta deskripsi singkatnya, untuk teks bantuan CLI."""
    return {name: cls.description for name, cls in sorted(COLLECTORS.items())}


def get_collector(name: str, config: Config, db: Database, **kwargs) -> Collector:
    """Buat instance collector berdasarkan nama.

    ``kwargs`` diteruskan ke konstruktor adapter (mis. ``path=`` untuk
    :class:`~ngulik.collectors.file_import.FileCollector`).
    """
    key = (name or "").strip().lower()
    collector_cls = COLLECTORS.get(key)
    if collector_cls is None:
        raise CollectorError(
            f"Unknown source: {name!r}. "
            f"Available: {', '.join(available())}"
        )
    return collector_cls(config, db, **kwargs)


__all__ = ["COLLECTORS", "available", "describe", "get_collector"]
