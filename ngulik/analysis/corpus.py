"""Korpus analisis: token komentar yang layak (PRD bagian 7).

Semua metode analisis membaca sumber yang sama: kolom ``tokens`` di
``cleaned_comments`` untuk baris yang bukan duplikat dan bukan spam. Token itu
sudah melewati normalisasi, kamus slang, dan penyaringan stopword, sehingga
analisis tidak perlu menokenisasi ulang dan hasilnya konsisten dengan
cleaning. Satu komentar = satu dokumen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ngulik.db import Database, loads

__all__ = ["Corpus", "load_corpus", "ngrams"]


@dataclass(slots=True)
class Corpus:
    """Dokumen berupa daftar token, sejajar dengan ``comment_ids``."""

    comment_ids: list[int] = field(default_factory=list)
    docs: list[list[str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.docs)

    @property
    def token_count(self) -> int:
        return sum(len(doc) for doc in self.docs)


def load_corpus(db: Database) -> Corpus:
    """Muat token semua komentar layak analisis, urut ``comment_id``."""
    corpus = Corpus()
    for row in db.query(
        "SELECT comment_id, tokens FROM cleaned_comments "
        "WHERE is_duplicate = 0 AND is_spam = 0 ORDER BY comment_id"
    ):
        tokens = loads(row["tokens"], [])
        if tokens:
            corpus.comment_ids.append(row["comment_id"])
            corpus.docs.append(tokens)
    return corpus


def ngrams(tokens: list[str], size: int) -> list[str]:
    """N-gram berurutan, digabung spasi: ``["a", "b", "c"], 2 -> ["a b", "b c"]``."""
    if size <= 1:
        return list(tokens)
    return [" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)]
