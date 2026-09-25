"""Jalankan analisis dan simpan hasilnya ke ``analysis_results`` (PRD 5.1).

Hasil disimpan per ``(iteration, method)``. Menjalankan ulang metode yang sama
di iterasi yang sama menggantikan hasil lamanya, jadi tabel ini selalu
mencerminkan korpus terbaru dan tidak menumpuk duplikat. Hanya ``top_n``
teratas per metode yang disimpan (per ukuran untuk n-gram): cukup untuk
laporan, tanpa membengkakkan database dengan ekor panjang term yang muncul
sekali.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ngulik.analysis.cooccurrence import PairStat, cooccurrence
from ngulik.analysis.corpus import Corpus, load_corpus
from ngulik.analysis.frequency import TermFrequency, term_frequency
from ngulik.analysis.ngram import NgramStat, ngram_counts
from ngulik.analysis.tfidf import TfidfScore, tfidf_scores
from ngulik.config import Config, get_logger
from ngulik.db import Database, dumps
from ngulik.models import SourceMethod, utc_now_iso

__all__ = ["METHODS", "AnalysisReport", "run_analysis"]

logger = get_logger("analysis")

METHODS = ("frequency", "ngram", "tfidf", "cooccurrence")


@dataclass(slots=True)
class AnalysisReport:
    iteration: int
    documents: int
    tokens: int
    frequency: list[TermFrequency] = field(default_factory=list)
    ngrams: list[NgramStat] = field(default_factory=list)
    tfidf: list[TfidfScore] = field(default_factory=list)
    pairs: list[PairStat] = field(default_factory=list)
    metric: str = "pmi"
    stored: int = 0


def run_analysis(
    config: Config,
    db: Database,
    methods: tuple[str, ...] = METHODS,
    *,
    corpus: Corpus | None = None,
) -> AnalysisReport:
    """Jalankan ``methods`` atas korpus layak analisis dan simpan hasilnya."""
    settings = config.section("analysis")
    top_n = int(settings.get("top_n", 100))
    sizes = tuple(int(n) for n in config.get("analysis.ngram.sizes", [1, 2, 3]))
    corpus = corpus if corpus is not None else load_corpus(db)
    iteration = db.current_iteration()
    report = AnalysisReport(iteration, len(corpus), corpus.token_count,
                            metric=str(config.get("analysis.cooccurrence.metric", "pmi")))

    if "frequency" in methods:
        report.frequency = term_frequency(corpus)
        report.stored += _save(db, iteration, SourceMethod.FREQUENCY, [
            (t.term, t.count, {"doc_freq": t.doc_freq, "relative": t.relative})
            for t in report.frequency[:top_n]
        ])

    if "ngram" in methods:
        report.ngrams = ngram_counts(
            corpus, sizes, int(config.get("analysis.ngram.min_frequency", 3))
        )
        kept = [s for size in sizes for s in [g for g in report.ngrams if g.size == size][:top_n]]
        report.stored += _save(db, iteration, SourceMethod.NGRAM, [
            (g.term, g.count, {"size": g.size, "doc_freq": g.doc_freq}) for g in kept
        ])

    if "tfidf" in methods:
        report.tfidf = tfidf_scores(
            corpus, sizes,
            sublinear_tf=bool(config.get("analysis.tfidf.sublinear_tf", True)),
            smooth_idf=bool(config.get("analysis.tfidf.smooth_idf", True)),
        )
        report.stored += _save(db, iteration, SourceMethod.TFIDF, [
            (s.term, s.score, {"doc_freq": s.doc_freq, "max_weight": s.max_weight})
            for s in report.tfidf[:top_n]
        ])

    if "cooccurrence" in methods:
        report.pairs = cooccurrence(
            corpus,
            window=int(config.get("analysis.cooccurrence.window", 5)),
            min_pair_frequency=int(config.get("analysis.cooccurrence.min_pair_frequency", 3)),
            metric=report.metric,
        )
        report.stored += _save(db, iteration, SourceMethod.COOCCURRENCE, [
            (p.label, p.value(report.metric),
             {"left": p.left, "right": p.right, "count": p.count, "pmi": p.pmi,
              "npmi": p.npmi, "metric": report.metric})
            for p in report.pairs[:top_n]
        ])

    logger.info(
        "Analysis of %d comments (%d tokens): %d results stored for iteration %d",
        report.documents, report.tokens, report.stored, iteration,
    )
    return report


def _save(
    db: Database,
    iteration: int,
    method: SourceMethod,
    rows: list[tuple[str, float, dict]],
) -> int:
    """Ganti hasil ``method`` di ``iteration`` dengan ``rows``."""
    now = utc_now_iso()
    with db.transaction():
        db.execute(
            "DELETE FROM analysis_results WHERE iteration = ? AND method = ?",
            (iteration, str(method)),
        )
        db.executemany(
            "INSERT INTO analysis_results (iteration, method, term, value, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(iteration, str(method), term, float(value), dumps(meta), now)
             for term, value, meta in rows],
        )
    return len(rows)
