"""Co-occurrence dengan PMI/NPMI (AC-009, PRD bagian 7).

Dua token dihitung muncul bersama bila jaraknya kurang dari ``window`` di
dalam satu komentar: dengan ``window = 5``, tiap token dipasangkan dengan
empat token sesudahnya. Pasangan tidak berarah, jadi ``(a, b)`` dan ``(b, a)``
dihitung sebagai satu pasangan.

Metrik:

* ``raw``  : jumlah kemunculan bersama.
* ``pmi``  : ``log2( p(x,y) / (p(x) p(y)) )``. Positif berarti keduanya muncul
  bersama lebih sering daripada kebetulan.
* ``npmi`` : PMI dibagi ``-log2 p(x,y)``, jadi rentangnya -1..1 dan bisa
  dibandingkan antarkorpus.

Semua peluang dihitung di ruang pasangan yang sama: tiap pasangan dihitung
dua arah (``2T`` pasangan berarah), ``p(x,y) = c(x,y) / 2T``, dan ``p(x)`` adalah
jumlah pasangan yang melibatkan ``x`` dibagi ``2T``. Memakai jumlah token untuk
``p(x)`` sementara ``p(x,y)`` dari jumlah pasangan akan mencampur dua basis dan
membuat NPMI bisa melewati 1; dengan satu basis, ``p(x,y) <= p(x)`` selalu
berlaku dan NPMI terjamin di -1..1.

PMI terkenal melebih-lebihkan pasangan langka, karena itu pasangan dengan
kemunculan di bawah ``min_pair_frequency`` dibuang sebelum dihitung.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ngulik.analysis.corpus import Corpus

__all__ = ["METRICS", "PairStat", "cooccurrence"]

METRICS = ("pmi", "npmi", "raw")


@dataclass(slots=True)
class PairStat:
    left: str
    right: str
    count: int
    pmi: float
    npmi: float

    def value(self, metric: str) -> float:
        return {"pmi": self.pmi, "npmi": self.npmi, "raw": float(self.count)}[metric]

    @property
    def label(self) -> str:
        return f"{self.left} ~ {self.right}"


def cooccurrence(
    corpus: Corpus,
    *,
    window: int = 5,
    min_pair_frequency: int = 3,
    metric: str = "pmi",
) -> list[PairStat]:
    """Pasangan token yang sering muncul berdekatan, diurutkan menurut ``metric``."""
    if metric not in METRICS:
        raise ValueError(f"Unknown co-occurrence metric {metric!r}; use one of {METRICS}")

    pairs: Counter[tuple[str, str]] = Counter()
    for doc in corpus.docs:
        for i, left in enumerate(doc):
            for right in doc[i + 1:i + window]:
                if left != right:
                    pairs[(left, right) if left < right else (right, left)] += 1

    # Marginal di ruang pasangan: berapa kali tiap token ikut dalam pasangan.
    marginals: Counter[str] = Counter()
    for (left, right), count in pairs.items():
        marginals[left] += count
        marginals[right] += count
    directed_total = 2 * sum(pairs.values())
    if not directed_total:
        return []

    stats: list[PairStat] = []
    for (left, right), count in pairs.items():
        if count < min_pair_frequency:
            continue
        p_xy = count / directed_total
        p_x = marginals[left] / directed_total
        p_y = marginals[right] / directed_total
        pmi = math.log2(p_xy / (p_x * p_y))
        denominator = -math.log2(p_xy)
        npmi = pmi / denominator if denominator > 0 else 1.0
        stats.append(PairStat(left, right, count, pmi, npmi))

    return sorted(stats, key=lambda s: (-s.value(metric), -s.count, s.label))
