"""N-gram: bigram, trigram, dan seterusnya (AC-007, PRD bagian 7).

N-gram dibentuk dari token yang stopword-nya sudah dibuang. Akibatnya "gabut
banget sih" dan "gabut sih banget" sama-sama menyumbang ke "gabut banget" bila
"sih" adalah stopword. Itu disengaja: yang dicari adalah kombinasi kata
bermakna, bukan susunan kalimat persis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from ngulik.analysis.corpus import Corpus, ngrams

__all__ = ["NgramStat", "count_ngrams", "ngram_counts"]


@dataclass(slots=True)
class NgramStat:
    term: str
    size: int
    count: int
    doc_freq: int


def count_ngrams(corpus: Corpus, sizes: Iterable[int]) -> dict[str, tuple[int, int]]:
    """``term -> (count, doc_freq)`` untuk semua ukuran n-gram, tanpa penyaringan."""
    counts: Counter[str] = Counter()
    doc_freq: Counter[str] = Counter()
    for doc in corpus.docs:
        for size in sizes:
            grams = ngrams(doc, size)
            counts.update(grams)
            doc_freq.update(set(grams))
    return {term: (n, doc_freq[term]) for term, n in counts.items()}


def ngram_counts(
    corpus: Corpus, sizes: Iterable[int], min_frequency: int = 1
) -> list[NgramStat]:
    """N-gram dengan kemunculan minimal ``min_frequency``, dari yang paling sering."""
    stats = [
        NgramStat(term, term.count(" ") + 1, count, df)
        for term, (count, df) in count_ngrams(corpus, sizes).items()
        if count >= min_frequency
    ]
    return sorted(stats, key=lambda s: (-s.count, s.size, s.term))
