"""Generator kandidat keyword dari korpus beserta scoring-nya (PRD bagian 8).

Alur:

1. **Pool.** Semua n-gram korpus (ukuran dari ``analysis.ngram.sizes``).
2. **Gate keras** sebelum scoring (keputusan desain 6): muncul di minimal
   ``min_doc_frequency`` komentar dan panjangnya minimal ``min_term_length``.
   Term yang sudah jadi keyword, sudah menunggu review, sudah disetujui, atau
   pernah ditolak (keputusan desain 7) juga dibuang di sini.
3. **Empat sinyal** per kandidat, lalu tiga yang pertama dinormalisasi min-max
   terhadap pool yang lolos gate:

   * ``frequency``    : jumlah kemunculan.
   * ``tfidf``        : skor TF-IDF agregat (lihat :mod:`ngulik.analysis.tfidf`).
   * ``cooccurrence`` : asosiasi terkuat dengan salah satu seed keyword aktif.
     Inilah sinyal "kata ini hidup di sekitar topik kita"; tanpa seed yang
     muncul di korpus, sinyal ini nol untuk semua kandidat.
   * ``ngram``        : ``ngram_bonus`` untuk frasa multi-kata, 0 untuk kata
     tunggal. Tidak dinormalisasi.

4. **Skor** = jumlah berbobot (``discovery.weights``). ``source_method``
   kandidat adalah sinyal yang menyumbang paling besar ke skornya, dan
   ``discovered_from`` mencatat angka-angkanya supaya keputusan review bisa
   ditelusuri (PRD bagian 10).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ngulik.analysis.cooccurrence import cooccurrence
from ngulik.analysis.corpus import Corpus, load_corpus
from ngulik.analysis.ngram import count_ngrams
from ngulik.analysis.tfidf import tfidf_scores
from ngulik.cleaning.normalize import normalize_text
from ngulik.cleaning.tokenize import Tokenizer
from ngulik.config import Config, get_logger
from ngulik.db import Database
from ngulik.keywords import KeywordError, validate
from ngulik.models import (
    CandidateStatus,
    KeywordCandidate,
    KeywordType,
    SourceMethod,
)

__all__ = ["DiscoveryResult", "ScoredCandidate", "discover_candidates", "seed_forms"]

logger = get_logger("discovery")

_SIGNALS = ("frequency", "tfidf", "cooccurrence", "ngram")
_METHOD_OF = {
    "frequency": SourceMethod.FREQUENCY,
    "tfidf": SourceMethod.TFIDF,
    "cooccurrence": SourceMethod.COOCCURRENCE,
    "ngram": SourceMethod.NGRAM,
}


@dataclass(slots=True)
class ScoredCandidate:
    term: str
    size: int
    count: int
    doc_freq: int
    raw: dict[str, float]
    norm: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    method: SourceMethod = SourceMethod.TFIDF
    seed: str | None = None

    @property
    def keyword_type(self) -> KeywordType:
        return KeywordType.PHRASE if self.size > 1 else KeywordType.KEYWORD

    def explain(self, metric: str) -> str:
        """Ringkasan sinyal untuk kolom ``discovered_from``."""
        parts = [f"docs={self.doc_freq}", f"count={self.count}",
                 f"tfidf={self.raw['tfidf']:.2f}"]
        if self.seed:
            parts.append(f"near seed '{self.seed}' ({metric} {self.raw['cooccurrence']:.2f})")
        return "; ".join(parts)


@dataclass(slots=True)
class DiscoveryResult:
    iteration: int
    documents: int
    seeds_in_corpus: int
    pool: int
    created: int = 0
    candidates: list[ScoredCandidate] = field(default_factory=list)
    dry_run: bool = False


def seed_forms(config: Config, terms: Iterable[str]) -> dict[str, str]:
    """Bentuk token tiap seed, diproses seperti komentar: ``bentuk -> term asli``.

    Seed yang seluruhnya stopword hilang di sini, sama seperti di korpus.
    """
    tokenizer = Tokenizer(config)
    settings = config.section("cleaning")
    forms: dict[str, str] = {}
    for term in terms:
        form = " ".join(tokenizer(normalize_text(term, settings)))
        if form:
            forms.setdefault(form, term)
    return forms


def discover_candidates(
    config: Config,
    db: Database,
    *,
    max_candidates: int | None = None,
    dry_run: bool = False,
    corpus: Corpus | None = None,
) -> DiscoveryResult:
    """Skor kandidat dari korpus dan tulis yang teratas sebagai PENDING."""
    settings = config.section("discovery")
    sizes = tuple(int(n) for n in config.get("analysis.ngram.sizes", [1, 2, 3]))
    min_df = int(settings.get("min_doc_frequency", 3))
    min_len = int(settings.get("min_term_length", 3))
    limit = max_candidates or int(settings.get("max_candidates", 50))
    weights = {name: float(settings.get("weights", {}).get(name, 0.0)) for name in _SIGNALS}
    bonus = float(settings.get("ngram_bonus", 1.0))
    respect = bool(settings.get("respect_previous_rejections", True))
    metric = str(config.get("analysis.cooccurrence.metric", "pmi"))

    corpus = corpus if corpus is not None else load_corpus(db)
    iteration = db.current_iteration()

    keyword_terms = [row["term"] for row in db.query(
        "SELECT term FROM keywords WHERE status = 'ACTIVE'")]
    seeds = seed_forms(config, keyword_terms)
    blocked = set(seeds) | {row["term"] for row in db.query("SELECT term FROM keywords")}
    for row in db.query("SELECT term, status FROM keyword_candidates"):
        if row["status"] != CandidateStatus.REJECTED or respect:
            blocked.add(row["term"])

    counts = count_ngrams(corpus, sizes)
    seed_tokens = {tok for form in seeds for tok in form.split()}
    result = DiscoveryResult(
        iteration, len(corpus),
        seeds_in_corpus=sum(1 for form in seeds if form in counts),
        pool=0, dry_run=dry_run,
    )

    pool: list[ScoredCandidate] = []
    for term, (count, df) in counts.items():
        if df < min_df or len(term) < min_len or term in blocked:
            continue
        if term.replace(" ", "").isdigit():
            continue
        size = term.count(" ") + 1
        pool.append(ScoredCandidate(term, size, count, df, raw={
            "frequency": float(count), "tfidf": 0.0, "cooccurrence": 0.0,
            "ngram": bonus if size > 1 else 0.0,
        }))
    result.pool = len(pool)
    if not pool:
        return result

    tfidf = {s.term: s.score for s in tfidf_scores(
        corpus, sizes,
        sublinear_tf=bool(config.get("analysis.tfidf.sublinear_tf", True)),
        smooth_idf=bool(config.get("analysis.tfidf.smooth_idf", True)),
    )}
    association = _seed_association(config, corpus, seed_tokens, metric)
    for candidate in pool:
        candidate.raw["tfidf"] = tfidf.get(candidate.term, 0.0)
        best = max(
            (association[tok] for tok in candidate.term.split()
             if tok in association and tok not in seed_tokens),
            default=None,
        )
        if best is not None:
            candidate.raw["cooccurrence"], seed_token = best
            candidate.seed = _seed_label(seed_token, seeds)

    _score(pool, weights)
    pool.sort(key=lambda c: (-c.score, -c.count, c.term))

    for candidate in pool:
        if len(result.candidates) >= limit:
            break
        # Skor nol = terendah di semua sinyal; hanya menambah beban review.
        if candidate.score <= 0:
            continue
        try:
            validate(candidate.term, candidate.keyword_type)
        except KeywordError:
            continue
        result.candidates.append(candidate)

    if not dry_run:
        result.created = _store(db, result.candidates, iteration, metric)
    logger.info(
        "Discovery: %d candidates scored from a pool of %d, %d new stored",
        len(result.candidates), result.pool, result.created,
    )
    return result


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _seed_association(
    config: Config, corpus: Corpus, seed_tokens: set[str], metric: str
) -> dict[str, tuple[float, str]]:
    """``token -> (nilai asosiasi terkuat dengan seed, token seed-nya)``.

    Hanya asosiasi positif yang dihitung: PMI negatif berarti keduanya justru
    saling menghindar, bukan "berada di sekitar topik".
    """
    if not seed_tokens:
        return {}
    best: dict[str, tuple[float, str]] = {}
    for pair in cooccurrence(
        corpus,
        window=int(config.get("analysis.cooccurrence.window", 5)),
        min_pair_frequency=int(config.get("analysis.cooccurrence.min_pair_frequency", 3)),
        metric=metric,
    ):
        value = pair.value(metric)
        if value <= 0:
            continue
        for other, seed in ((pair.left, pair.right), (pair.right, pair.left)):
            if seed in seed_tokens and other not in seed_tokens:
                if value > best.get(other, (0.0, ""))[0]:
                    best[other] = (value, seed)
    return best


def _seed_label(token: str, seeds: dict[str, str]) -> str:
    """Term seed asli yang memuat ``token``, untuk ditampilkan ke reviewer."""
    for form, original in seeds.items():
        if token in form.split():
            return original
    return token


def _score(pool: list[ScoredCandidate], weights: dict[str, float]) -> None:
    for name in ("frequency", "tfidf", "cooccurrence"):
        values = [c.raw[name] for c in pool]
        low, high = min(values), max(values)
        span = high - low
        for c in pool:
            # Sinyal yang sama untuk semua kandidat tidak membedakan apa pun.
            c.norm[name] = (c.raw[name] - low) / span if span > 0 else 0.0
    for c in pool:
        c.norm["ngram"] = c.raw["ngram"]
        contributions = {name: weights[name] * c.norm[name] for name in _SIGNALS}
        c.score = sum(contributions.values())
        c.method = _METHOD_OF[max(contributions, key=contributions.__getitem__)]


def _store(
    db: Database, candidates: list[ScoredCandidate], iteration: int, metric: str
) -> int:
    created = 0
    with db.transaction():
        for c in candidates:
            row = KeywordCandidate(
                term=c.term, source_method=str(c.method), frequency=c.doc_freq,
                score=round(c.score, 4), type=c.keyword_type,
                discovered_from=c.explain(metric), iteration=iteration,
            )
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO keyword_candidates
                    (term, type, source_method, frequency, score, discovered_from,
                     iteration, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row.term, str(row.type), row.source_method, row.frequency, row.score,
                 row.discovered_from, row.iteration, str(row.status), row.created_at),
            )
            created += cursor.rowcount
    return created
