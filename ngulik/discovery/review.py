"""Review manual kandidat dan promosi ke seed keyword (PRD bagian 8 dan 10).

Tahap REVIEW dan EXPAND dari loop inti. Modul ini tidak peduli dari mana
kandidat berasal (analisis korpus atau kamus leksikon); semuanya melewati
gerbang yang sama: manusia memutuskan, baru kemudian kandidat yang disetujui
dipakai sebagai seed pada iterasi berikutnya (AC-011, AC-012).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ngulik.db import Database
from ngulik.keywords import KeywordError, KeywordManager
from ngulik.models import CandidateStatus, Keyword, KeywordCandidate, utc_now_iso

__all__ = [
    "PromotionResult",
    "find_pending",
    "list_candidates",
    "promote_approved",
    "set_status",
]


def list_candidates(
    db: Database,
    *,
    status: CandidateStatus | None = CandidateStatus.PENDING,
    method: str | None = None,
    limit: int | None = None,
) -> list[KeywordCandidate]:
    """Kandidat terurut skor lalu frekuensi, yang paling menjanjikan di atas."""
    sql = "SELECT * FROM keyword_candidates WHERE 1=1"
    params: list[object] = []
    if status is not None:
        sql += " AND status = ?"
        params.append(str(status))
    if method:
        sql += " AND source_method = ?"
        params.append(method.upper())
    sql += " ORDER BY score DESC, frequency DESC, id ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [KeywordCandidate.from_row(row) for row in db.query(sql, params)]


def find_pending(db: Database, term: str) -> KeywordCandidate | None:
    """Kandidat PENDING dengan term tertentu, dari iterasi mana pun."""
    row = db.query_one(
        "SELECT * FROM keyword_candidates WHERE term = ? AND status = 'PENDING' "
        "ORDER BY iteration DESC LIMIT 1",
        (term.strip().lower(),),
    )
    return KeywordCandidate.from_row(row) if row else None


def set_status(db: Database, candidate_id: int, status: CandidateStatus) -> None:
    """Catat keputusan review beserta waktunya."""
    db.execute(
        "UPDATE keyword_candidates SET status = ?, reviewed_at = ? WHERE id = ?",
        (str(status), utc_now_iso(), candidate_id),
    )
    db.commit()


@dataclass(slots=True)
class PromotionResult:
    iteration: int
    promoted: list[Keyword] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def promote_approved(db: Database) -> PromotionResult:
    """Jadikan kandidat APPROVED sebagai seed keyword di iterasi berikutnya.

    Keyword baru mendapat ``iteration`` = iterasi saat ini + 1 dan
    ``discovered_from`` yang menunjuk balik ke kandidat asalnya, sehingga
    jejak asal-usulnya bisa ditelusuri (PRD bagian 10). Kandidat yang
    term-nya sudah menjadi keyword dilewati, jadi aman dijalankan berulang.
    """
    next_iteration = db.current_iteration() + 1
    result = PromotionResult(iteration=next_iteration)
    manager = KeywordManager(db)

    for candidate in list_candidates(db, status=CandidateStatus.APPROVED):
        provenance = f"{candidate.source_method} kandidat#{candidate.id}"
        if candidate.discovered_from:
            provenance += f" {candidate.discovered_from}"
        try:
            keyword, created = manager.add(
                candidate.term,
                candidate.type,
                iteration=next_iteration,
                discovered_from=provenance,
            )
        except KeywordError:
            result.skipped.append(candidate.term)
            continue
        if created:
            result.promoted.append(keyword)
        else:
            result.skipped.append(candidate.term)

    if not result.promoted:
        result.iteration = db.current_iteration()
    return result
