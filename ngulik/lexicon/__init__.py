"""Sumber leksikon: kamus slang dari internet (CLAUDE.md Prioritas 8).

Menambah situs baru cukup dengan menulis satu subclass
:class:`~ngulik.lexicon.base.LexiconSource` lalu mendaftarkannya di
:data:`SOURCES`.
"""

from __future__ import annotations

from ngulik.config import Config
from ngulik.lexicon.base import LexiconError, LexiconSource, PoliteFetcher
from ngulik.lexicon.kbbj import KbbjSource
from ngulik.lexicon.runner import (
    FetchStats,
    ProposeStats,
    fetch_lexicon,
    propose_candidates,
)

SOURCES: dict[str, type[LexiconSource]] = {
    KbbjSource.name: KbbjSource,
}


def available() -> list[str]:
    """Nama sumber leksikon yang terdaftar."""
    return sorted(SOURCES)


def get_source(name: str, config: Config) -> LexiconSource:
    """Buat instance sumber leksikon berdasarkan nama."""
    source_cls = SOURCES.get((name or "").strip().lower())
    if source_cls is None:
        raise LexiconError(
            f"Unknown lexicon source: {name!r}. Available: {', '.join(available())}"
        )
    source = source_cls(config)
    if not source.enabled:
        raise LexiconError(
            f"Source {name!r} is disabled in config (lexicon.sources.{name}.enabled)"
        )
    return source


__all__ = [
    "SOURCES",
    "FetchStats",
    "KbbjSource",
    "LexiconError",
    "LexiconSource",
    "PoliteFetcher",
    "ProposeStats",
    "available",
    "fetch_lexicon",
    "get_source",
    "propose_candidates",
]
