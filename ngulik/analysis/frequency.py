"""Frekuensi term (AC-006, PRD bagian 7)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ngulik.analysis.corpus import Corpus

__all__ = ["TermFrequency", "term_frequency"]


@dataclass(slots=True)
class TermFrequency:
    term: str
    count: int
    doc_freq: int
    relative: float


def term_frequency(corpus: Corpus) -> list[TermFrequency]:
    """Jumlah kemunculan tiap token, dokumen yang memuatnya, dan porsinya.

    ``relative`` adalah porsi terhadap seluruh token korpus. Diurutkan dari
    yang paling sering; seri diurutkan abjad supaya hasilnya deterministik.
    """
    counts: Counter[str] = Counter()
    doc_freq: Counter[str] = Counter()
    for doc in corpus.docs:
        counts.update(doc)
        doc_freq.update(set(doc))

    total = sum(counts.values()) or 1
    return sorted(
        (TermFrequency(term, n, doc_freq[term], n / total) for term, n in counts.items()),
        key=lambda item: (-item.count, item.term),
    )
