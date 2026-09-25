"""TF-IDF manual, tanpa scikit-learn (AC-008, keputusan desain 1).

Satu komentar = satu dokumen. Untuk tiap dokumen::

    tf'  = 1 + log(tf)          bila sublinear_tf, selain itu tf
    idf  = log(1 + N / df)      bila smooth_idf, selain itu log(N / df)
    w    = tf' * idf, lalu dinormalisasi L2 per dokumen

Skor tingkat korpus sebuah term adalah jumlah bobot ``w`` di semua dokumen.
Normalisasi L2 membuat komentar panjang tidak mendominasi, dan penjumlahan
membuat skor tertinggi jatuh ke term yang *cukup sering* tapi *tidak ada di
mana-mana*: term di hampir semua komentar punya idf mendekati nol, term di
satu-dua komentar hanya menyumbang sedikit. Profil itulah yang dicari
keyword discovery.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from ngulik.analysis.corpus import Corpus, ngrams

__all__ = ["TfidfScore", "tfidf_scores"]


@dataclass(slots=True)
class TfidfScore:
    term: str
    score: float
    doc_freq: int
    max_weight: float


def tfidf_scores(
    corpus: Corpus,
    sizes: Iterable[int] = (1,),
    *,
    sublinear_tf: bool = True,
    smooth_idf: bool = True,
) -> list[TfidfScore]:
    """Skor TF-IDF agregat per term, dari yang tertinggi."""
    sizes = tuple(sizes)
    docs = [Counter(g for size in sizes for g in ngrams(doc, size)) for doc in corpus.docs]
    n_docs = len(docs)
    if not n_docs:
        return []

    doc_freq: Counter[str] = Counter()
    for counts in docs:
        doc_freq.update(counts.keys())

    idf = {
        term: math.log(1 + n_docs / df) if smooth_idf else math.log(n_docs / df)
        for term, df in doc_freq.items()
    }

    total: dict[str, float] = {}
    peak: dict[str, float] = {}
    for counts in docs:
        weights = {
            term: ((1 + math.log(tf)) if sublinear_tf else tf) * idf[term]
            for term, tf in counts.items()
        }
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        for term, weight in weights.items():
            value = weight / norm
            total[term] = total.get(term, 0.0) + value
            peak[term] = max(peak.get(term, 0.0), value)

    return sorted(
        (TfidfScore(term, score, doc_freq[term], peak[term]) for term, score in total.items()),
        key=lambda s: (-s.score, s.term),
    )
