"""Antarmuka baris perintah: ``python -m ngulik`` atau ``ngulik``.

Setiap perintah adalah satu langkah dari loop inti (PRD bagian 25)::

    SEED -> COLLECT -> CLEAN -> ANALYZE -> DISCOVER -> REVIEW -> EXPAND

Tanpa subperintah, ``python -m ngulik`` membuka konsol interaktif bergaya
msfconsole (:mod:`ngulik.console`).

Seluruh output lewat :mod:`ngulik.report` supaya tampilannya seragam.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ngulik import __version__, report, ui
from ngulik.analysis import METHODS as ANALYSIS_METHODS
from ngulik.analysis import run_analysis
from ngulik.cleaning import CleaningPipeline
from ngulik.collectors import (
    CollectorError,
    available,
    describe,
    get_collector,
    parse_video_id,
    run_collection,
)
from ngulik.config import KEYWORDS_FILE, Config, setup_logging
from ngulik.db import Database, loads
from ngulik.discovery import (
    discover_candidates,
    find_pending,
    list_candidates,
    promote_approved,
    set_status,
)
from ngulik.keywords import KeywordError, KeywordManager
from ngulik.lexicon import (
    LexiconError,
    fetch_lexicon,
    get_source,
    propose_candidates,
)
from ngulik.lexicon import available as lexicon_sources
from ngulik.matching import MatchStats, match_keywords
from ngulik.models import (
    CandidateStatus,
    KeywordCandidate,
    KeywordStatus,
    KeywordType,
    SourceMethod,
)

__all__ = ["cli", "main"]

#: Label ramah-baca untuk kunci dari :meth:`Database.stats`.
_STAT_LABELS = {
    "iteration": "Current iteration",
    "keywords": "Active keywords",
    "keywords_total": "Total keywords",
    "comments": "Raw comments",
    "cleaned": "Cleaned comments",
    "usable": "Usable for analysis",
    "duplicates": "Duplicates",
    "spam": "Spam",
    "candidates_pending": "Candidates pending review",
    "candidates_approved": "Candidates approved",
    "candidates_rejected": "Candidates rejected",
    "runs": "Collection runs",
    "videos_cached": "Cached videos",
    "keyword_matched": "Comments with known keywords",
    "lexicon_entries": "Lexicon entries",
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


@contextmanager
def open_db(config: Config) -> Iterator[Database]:
    """Buka database dan pastikan skemanya ada. Aman dipanggil di tiap perintah."""
    with Database(config) as db:
        db.initialize()
        yield db


def _config(ctx: click.Context) -> Config:
    return ctx.obj


def _search_calls_since(db: Database, hours: int) -> int:
    """Total call ``search.list`` dalam ``hours`` jam terakhir.

    Jatah YouTube direset tengah malam waktu Pacific, jadi jendela bergulir
    24 jam ini perkiraan konservatif, bukan hitungan resmi.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).replace(microsecond=0).isoformat()
    rows = db.query(
        "SELECT params FROM collection_runs WHERE source = 'youtube' AND started_at >= ?",
        (cutoff,),
    )
    return sum(int((loads(row["params"], {}) or {}).get("search_calls", 0)) for row in rows)


# ---------------------------------------------------------------------------
# Grup utama
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True, help='Ngulik: iterative keyword discovery, fully local.')
@click.option(
    "--config", "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config file. Default: config/config.yaml",
)
@click.option("-v", "--verbose", is_flag=True, help="Show DEBUG logs in the console.")
@click.version_option(__version__, prog_name="ngulik")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None, verbose: bool) -> None:
    """Ngulik: keyword discovery iteratif, sepenuhnya lokal."""
    config = Config.load(config_path)
    ui.configure(config)
    setup_logging(config, verbose=verbose)
    ctx.obj = config
    if ctx.invoked_subcommand is None:
        ctx.invoke(console)


@cli.command(help='Create the database and data folder.')
@click.pass_context
def init(ctx: click.Context) -> None:
    """Buat database dan folder data (fase 0)."""
    config = _config(ctx)
    with Database(config) as db:
        created = db.initialize()
        click.echo(report.key_values(
            {
                "Database": str(db.path),
                "Status": "created" if created else "already exists",
                "Schema version": db.schema_version,
            },
            title="Initialize",
        ))
    if created:
        click.echo()
        ui.info("Next step: python -m ngulik keyword import")


@cli.command(help='Summary of the database and the latest collection runs.')
@click.pass_context
def status(ctx: click.Context) -> None:
    """Ringkasan isi database dan collection run terakhir."""
    config = _config(ctx)
    with open_db(config) as db:
        stats = db.stats()
        click.echo(report.key_values(
            {label: stats[key] for key, label in _STAT_LABELS.items()},
            title="Ngulik status",
        ))

        click.echo(report.section("YouTube quota"))
        click.echo(report.key_values({
            "search.list calls, last 24h": _search_calls_since(db, 24),
            "Daily search.list quota": int(
                config.get("collection.youtube.daily_search_quota", 100)
            ),
        }))

        runs = db.query(
            """
            SELECT id, source, iteration, status, comments_collected, quota_used,
                   started_at
              FROM collection_runs ORDER BY id DESC LIMIT 5
            """
        )
        click.echo(report.section("Latest collection runs"))
        click.echo(report.table(
            ["#", "Source", "Iteration", "Status", "New", "Quota", "Started"],
            [tuple(row) for row in runs],
        ))


# ---------------------------------------------------------------------------
# keyword
# ---------------------------------------------------------------------------


@cli.group(help='Manage seed keywords (FR-001).')
def keyword() -> None:
    """Kelola seed keyword (FR-001)."""


def _report_matches(stats: MatchStats) -> None:
    """Satu baris ringkasan hasil pencocokan keyword."""
    ui.good(
        f"{stats.comments_matched} of {stats.comments_scanned} comments contain "
        f"known keywords ({stats.keywords} active keywords checked)"
    )


@keyword.command("match", help="Re-link every comment to the active keywords it contains.")
@click.option("--top", type=click.IntRange(min=1), default=20, show_default=True,
              help="How many keywords to show in the summary.")
@click.pass_context
def keyword_match(ctx: click.Context, top: int) -> None:
    """Bangun ulang pencocokan komentar-keyword (lihat ngulik.matching)."""
    config = _config(ctx)
    with open_db(config) as db:
        _report_matches(match_keywords(config, db))
        rows = db.query(
            """
            SELECT k.term, k.type, COUNT(*) AS n
              FROM comment_keyword_matches m JOIN keywords k ON k.id = m.keyword_id
             GROUP BY k.id ORDER BY n DESC, k.term LIMIT ?
            """,
            (top,),
        )
        click.echo()
        click.echo(report.table(["Keyword", "Type", "Comments"],
                                [tuple(r) for r in rows], title="Most matched keywords"))


@keyword.command("import", help='Load seed keywords from YAML into the database. Idempotent.')
@click.option(
    "--file", "file_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="YAML file. Default: config/keywords.yaml",
)
@click.pass_context
def keyword_import(ctx: click.Context, file_path: Path | None) -> None:
    """Muat seed keyword dari YAML ke database. Idempoten."""
    config = _config(ctx)
    path = config.resolve(file_path) if file_path else KEYWORDS_FILE
    with open_db(config) as db:
        try:
            summary = KeywordManager(db).import_yaml(path)
        except (FileNotFoundError, KeywordError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(report.key_values(
            {
                "File": str(path),
                "New": summary["created"],
                "Existing": summary["existing"],
                "Invalid": summary["invalid"],
            },
            title="Keyword import",
        ))


@keyword.command("list", help='Show keywords and where they came from.')
@click.option("--all", "show_all", is_flag=True, help="Include INACTIVE keywords.")
@click.option(
    "--type", "keyword_type",
    type=click.Choice([t.value for t in KeywordType], case_sensitive=False),
    default=None,
)
@click.pass_context
def keyword_list(ctx: click.Context, show_all: bool, keyword_type: str | None) -> None:
    """Tampilkan keyword beserta asal-usulnya (PRD bagian 10)."""
    config = _config(ctx)
    with open_db(config) as db:
        keywords = KeywordManager(db).list(
            status=None if show_all else KeywordStatus.ACTIVE,
            keyword_type=KeywordType(keyword_type.upper()) if keyword_type else None,
        )
        click.echo(report.table(
            ["#", "Term", "Type", "Status", "Iteration", "Origin"],
            [
                (k.id, k.term, k.type, k.status, k.iteration, k.discovered_from or "seed")
                for k in keywords
            ],
            title=f"Keywords ({len(keywords)})",
        ))


@keyword.command("add", help='Add one or more keywords.')
@click.argument("terms", nargs=-1, required=True)
@click.option(
    "--type", "keyword_type",
    type=click.Choice([t.value for t in KeywordType], case_sensitive=False),
    default=None,
    help="Default: inferred from the term.",
)
@click.pass_context
def keyword_add(ctx: click.Context, terms: tuple[str, ...], keyword_type: str | None) -> None:
    """Tambah satu atau beberapa keyword."""
    config = _config(ctx)
    with open_db(config) as db:
        manager = KeywordManager(db)
        rows = []
        for term in terms:
            try:
                item, created = manager.add(
                    term, KeywordType(keyword_type.upper()) if keyword_type else None
                )
            except KeywordError as exc:
                rows.append((term, "-", f"rejected: {exc}"))
                continue
            rows.append((item.term, item.type, "added" if created else "already exists"))
        click.echo(report.table(["Term", "Type", "Result"], rows))


@keyword.command("export", help="Write active keywords (seeds + approved) to a YAML file.")
@click.option(
    "--file", "file_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("data/exports/keywords.yaml"), show_default=True,
    help="Target file. Same format as config/keywords.yaml, so it can be imported back.",
)
@click.pass_context
def keyword_export(ctx: click.Context, file_path: Path) -> None:
    """Ekspor keyword aktif; default-nya tidak menimpa config/keywords.yaml."""
    config = _config(ctx)
    path = config.resolve(file_path)
    with open_db(config) as db:
        counts = KeywordManager(db).export_yaml(path)
    click.echo(report.key_values(
        {"File": str(path), "Keywords": counts["keywords"], "Phrases": counts["phrases"],
         "Hashtags": counts["hashtags"]},
        title="Keyword export",
    ))


@keyword.command("remove", help='Deactivate (or delete) keywords.')
@click.argument("terms", nargs=-1, required=True)
@click.option(
    "--hard", is_flag=True,
    help="Delete the row for real. Default: deactivate, so comments keep their keyword trail.",
)
@click.pass_context
def keyword_remove(ctx: click.Context, terms: tuple[str, ...], hard: bool) -> None:
    """Nonaktifkan (atau hapus) keyword."""
    config = _config(ctx)
    with open_db(config) as db:
        manager = KeywordManager(db)
        rows = [
            (term, ("deleted" if hard else "deactivated")
             if manager.remove(term, hard=hard) else "not found")
            for term in terms
        ]
        click.echo(report.table(["Term", "Result"], rows))


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def _source_help() -> str:
    return "Data source. " + "; ".join(f"{k}: {v}" for k, v in describe().items())


@cli.command(help='Collect comments from one source (FR-002, FR-003).')
@click.option(
    "--source",
    type=click.Choice(available(), case_sensitive=False),
    default=None,
    help=_source_help(),
)
@click.option("--limit", type=click.IntRange(min=1), default=None,
              help="Maximum comments. Default: collection.default_limit")
@click.option("--path", "file_path", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="JSON/JSONL/CSV file for --source file.")
@click.option("--iteration", type=click.IntRange(min=0), default=None,
              help="Iteration number. Default: current iteration.")
@click.option("--video", "videos", multiple=True, metavar="URL_OR_ID",
              help="Only collect from this YouTube video (URL or ID). Repeatable. "
                   "Skips video search, so it costs no search.list quota.")
@click.option("--pages", type=click.IntRange(min=1), default=None,
              help="Comment pages per video with --video (100 comments per page). "
                   "Default: collection.youtube.max_comment_pages_per_selected_video")
@click.pass_context
def collect(
    ctx: click.Context,
    source: str | None,
    limit: int | None,
    file_path: Path | None,
    iteration: int | None,
    videos: tuple[str, ...] = (),
    pages: int | None = None,
) -> None:
    """Kumpulkan komentar dari satu sumber (FR-002, FR-003)."""
    config = _config(ctx)
    if videos and source and source.lower() != "youtube":
        raise click.UsageError("--video only works with --source youtube")
    source = (source or ("youtube" if videos else
                         str(config.get("collection.default_source", "file")))).lower()
    limit = limit or int(config.get("collection.default_limit", 500))

    kwargs: dict[str, object] = {}
    if source == "file":
        kwargs["path"] = config.resolve(file_path) if file_path else None
    elif source == "youtube" and videos:
        kwargs["videos"] = list(videos)
        kwargs["max_pages"] = pages

    with open_db(config) as db:
        manager = KeywordManager(db)
        try:
            collector = get_collector(source, config, db, **kwargs)
            run = run_collection(
                config, db, collector, manager.active_terms(),
                limit=limit,
                iteration=db.current_iteration() if iteration is None else iteration,
                keyword_manager=manager,
            )
        except CollectorError as exc:
            raise click.ClickException(str(exc)) from exc

        summary = {
            "Run": f"#{run.id}",
            "Source": run.source,
            "Iteration": run.iteration,
            "Status": str(run.status),
            "New comments": run.comments_collected,
            "Quota used": run.quota_used,
        }
        if "search_calls" in run.params:
            summary["search.list calls"] = run.params["search_calls"]
        if run.error:
            summary["Note"] = run.error
        click.echo(report.key_values(summary, title="Collection"))
        if run.comments_collected:
            click.echo()
            _report_matches(match_keywords(config, db))
            ui.info("Next step: python -m ngulik clean")


# ---------------------------------------------------------------------------
# comments & videos
# ---------------------------------------------------------------------------

_MATCHED_TERMS = (
    "(SELECT group_concat(k.term, ', ') FROM comment_keyword_matches m "
    "JOIN keywords k ON k.id = m.keyword_id WHERE m.comment_id = c.id)"
)


def _comment_state(row) -> str:
    if row["is_spam"] is None:
        return "raw"
    if row["is_spam"]:
        return "spam"
    if row["is_duplicate"]:
        return "dup"
    return "ok"


@cli.group(help="Browse collected comments.")
def comments() -> None:
    """Jelajahi komentar yang sudah terkumpul."""


@comments.command("list", help="List comments, newest first, with filters.")
@click.option("--source", default=None, help="Only this source, e.g. youtube or file.")
@click.option("--video", default=None, metavar="URL_OR_ID", help="Only comments of this video.")
@click.option("--keyword", "term", default=None,
              help="Only comments containing this keyword (see 'keyword match').")
@click.option("--matched", is_flag=True, help="Only comments containing any known keyword.")
@click.option("--search", default=None, help="Only comments whose text contains this.")
@click.option("--usable", is_flag=True, help="Hide spam, duplicates and uncleaned comments.")
@click.option("--limit", type=click.IntRange(min=0), default=20, show_default=True,
              help="Rows to show; 0 = all.")
@click.option("--export", "export_path", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Also save the result as CSV.")
@click.pass_context
def comments_list(
    ctx: click.Context,
    source: str | None,
    video: str | None,
    term: str | None,
    matched: bool,
    search: str | None,
    usable: bool,
    limit: int,
    export_path: Path | None,
) -> None:
    """Daftar komentar dengan saringan; teks mentah tidak pernah diubah."""
    config = _config(ctx)
    sql = f"""
        SELECT c.id, c.source, c.text_raw, c.url, c.created_at,
               cc.is_spam, cc.is_duplicate, {_MATCHED_TERMS} AS matched
          FROM comments c
          LEFT JOIN cleaned_comments cc ON cc.comment_id = c.id
         WHERE 1=1"""
    params: list[object] = []
    if source:
        sql += " AND c.source = ?"
        params.append(source.lower())
    if video:
        try:
            video_id = parse_video_id(video)
        except CollectorError as exc:
            raise click.BadParameter(str(exc), param_hint="--video") from exc
        sql += " AND c.url LIKE ?"
        params.append(f"%v={video_id}&%")
    if term:
        sql += (" AND EXISTS (SELECT 1 FROM comment_keyword_matches m JOIN keywords k"
                " ON k.id = m.keyword_id WHERE m.comment_id = c.id AND k.term = ?)")
        params.append(term.strip().lower())
    if matched:
        sql += " AND EXISTS (SELECT 1 FROM comment_keyword_matches m WHERE m.comment_id = c.id)"
    if search:
        sql += " AND c.text_raw LIKE ?"
        params.append(f"%{search}%")
    if usable:
        sql += " AND cc.is_spam = 0 AND cc.is_duplicate = 0"
    sql += " ORDER BY c.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    with open_db(config) as db:
        rows = db.query(sql, params)
        total = db.scalar("SELECT COUNT(*) FROM comments", default=0)

    table_rows = [
        (r["id"], r["source"], _comment_state(r), r["matched"] or "-",
         " ".join(r["text_raw"].split()))
        for r in rows
    ]
    click.echo(report.table(
        ["#", "Source", "State", "Keywords", "Text"], table_rows,
        title=f"Comments ({len(rows)} shown, {total} stored)",
    ))
    click.echo()
    ui.info("Full text and details: comments show <#>")
    if export_path is not None:
        path = report.export_csv(
            config.resolve(export_path),
            ["id", "source", "state", "keywords", "url", "created_at", "text"],
            [(r["id"], r["source"], _comment_state(r), r["matched"] or "",
              r["url"] or "", r["created_at"] or "", r["text_raw"]) for r in rows],
        )
        ui.good(f"Saved {len(rows)} rows to {path}")


@comments.command("show", help="Show one comment in full: raw text, clean text, keywords.")
@click.argument("comment_id", type=int)
@click.pass_context
def comments_show(ctx: click.Context, comment_id: int) -> None:
    """Detail satu komentar."""
    config = _config(ctx)
    with open_db(config) as db:
        row = db.query_one(
            f"""
            SELECT c.*, cc.text_clean, cc.tokens, cc.is_spam, cc.is_duplicate,
                   cc.duplicate_of, cc.spam_reason, {_MATCHED_TERMS} AS matched,
                   (SELECT group_concat(k.term, ', ') FROM comment_keywords ck
                      JOIN keywords k ON k.id = ck.keyword_id
                     WHERE ck.comment_id = c.id) AS triggers
              FROM comments c
              LEFT JOIN cleaned_comments cc ON cc.comment_id = c.id
             WHERE c.id = ?
            """,
            (comment_id,),
        )
    if row is None:
        raise click.ClickException(f"No comment with id {comment_id}")

    state = _comment_state(row)
    if state == "spam":
        state += f" ({row['spam_reason']})"
    elif state == "dup":
        state += f" (of #{row['duplicate_of']})"
    click.echo(report.key_values({
        "ID": row["id"],
        "Source": row["source"],
        "Source ID": row["source_id"],
        "URL": row["url"] or "-",
        "Posted": row["created_at"] or "-",
        "Collected": row["collected_at"],
        "Run": f"#{row['run_id']}" if row["run_id"] else "-",
        "State": state,
        "Known keywords": row["matched"] or "-",
        "Found by search": row["triggers"] or "-",
    }, title=f"Comment #{row['id']}"))
    click.echo(report.section("Raw text"))
    click.echo(row["text_raw"])
    if row["text_clean"] is not None:
        click.echo(report.section("Clean text"))
        click.echo(row["text_clean"])
        click.echo(report.section("Tokens"))
        click.echo(", ".join(loads(row["tokens"], [])) or "-")


@cli.group(help="Browse YouTube videos that comments were collected from.")
def videos() -> None:
    """Jelajahi video YouTube yang tersimpan."""


@videos.command("list", help="List known videos with how many comments are stored.")
@click.option("--limit", type=click.IntRange(min=1), default=30, show_default=True)
@click.pass_context
def videos_list(ctx: click.Context, limit: int) -> None:
    """Video dari pencarian keyword dan dari --video."""
    config = _config(ctx)
    with open_db(config) as db:
        rows = db.query(
            """
            SELECT v.video_id, COALESCE(v.keyword, '(selected)') AS origin, v.title,
                   (SELECT COUNT(*) FROM comments c
                     WHERE c.source = 'youtube' AND c.url LIKE '%v=' || v.video_id || '&%')
                   AS stored
              FROM videos v ORDER BY v.discovered_at DESC LIMIT ?
            """,
            (limit,),
        )
    click.echo(report.table(
        ["Video ID", "Found via", "Comments", "Title"],
        [(r["video_id"], r["origin"], r["stored"], r["title"] or "-") for r in rows],
        title=f"Videos ({len(rows)})",
        empty_message="(no videos yet: collect --source youtube [--video URL])",
    ))
    if rows:
        click.echo()
        ui.info("Comments of one video: comments list --video <Video ID>")


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


@cli.command(help='Clean comments: normalize, tokenize, spam, duplicates (FR-004, FR-005).')
@click.option(
    "--reprocess", is_flag=True,
    help="Clear cleaned_comments and reprocess everything from raw data.",
)
@click.pass_context
def clean(ctx: click.Context, reprocess: bool) -> None:
    """Bersihkan komentar: normalisasi, token, spam, duplikat (FR-004, FR-005)."""
    config = _config(ctx)
    with open_db(config) as db:
        stats = CleaningPipeline(config, db).run(reprocess=reprocess)
        totals = db.stats()
        click.echo(report.key_values(
            {
                "Mode": "reprocess" if stats.reprocessed else "incremental",
                "Processed": stats.processed,
                "Duplicates": stats.duplicates,
                "Spam (per comment)": stats.spam,
                "Spam (copypasta)": stats.copypasta,
                "Total usable for analysis": totals["usable"],
            },
            title="Cleaning",
        ))
        if stats.spam_by_rule:
            click.echo(report.section("Spam by rule"))
            click.echo(report.table(
                ["Rule", "Count"],
                sorted(stats.spam_by_rule.items(), key=lambda item: -item[1]),
            ))


# ---------------------------------------------------------------------------
# analyze & discover
# ---------------------------------------------------------------------------


def _need_corpus(documents: int) -> bool:
    if documents:
        return True
    ui.warn("No usable comments to analyze yet.")
    ui.info("Collect and clean first: ngulik collect ... then ngulik clean")
    return False


@cli.command(help="Analyze cleaned comments: frequency, n-grams, TF-IDF, co-occurrence "
                  "(AC-006 to AC-009).")
@click.argument("method", type=click.Choice([*ANALYSIS_METHODS, "all"], case_sensitive=False),
                default="all")
@click.option("--show", type=click.IntRange(min=1), default=15, show_default=True,
              help="Rows to show per table. All top results are still saved.")
@click.pass_context
def analyze(ctx: click.Context, method: str = "all", show: int = 15) -> None:
    """Analisis korpus lalu simpan hasil teratas ke analysis_results."""
    config = _config(ctx)
    methods = ANALYSIS_METHODS if method.lower() == "all" else (method.lower(),)
    with open_db(config) as db:
        with ui.spinner("Analyzing cleaned comments..."):
            result = run_analysis(config, db, methods)
    if not _need_corpus(result.documents):
        return

    click.echo()
    click.echo(report.key_values({
        "Iteration": result.iteration,
        "Comments analyzed": result.documents,
        "Tokens": result.tokens,
        "Results saved": result.stored,
    }, title="Analysis"))

    if result.frequency:
        top = result.frequency[:show]
        peak = top[0].count
        click.echo(report.section("Top terms by frequency"))
        click.echo(report.table(
            ["Term", "Count", "Share", "Comments", ""],
            [(t.term, t.count, f"{t.relative:.2%}", t.doc_freq, report.bar(t.count, peak, 20))
             for t in top],
        ))
    for size in sorted({g.size for g in result.ngrams} - {1}):
        rows = [g for g in result.ngrams if g.size == size][:show]
        click.echo(report.section(f"Top {size}-grams"))
        click.echo(report.table(["Phrase", "Count", "Comments"],
                                [(g.term, g.count, g.doc_freq) for g in rows]))
    if result.tfidf:
        click.echo(report.section("Top terms by TF-IDF"))
        click.echo(report.table(["Term", "Score", "Comments"],
                                [(s.term, s.score, s.doc_freq) for s in result.tfidf[:show]]))
    if "cooccurrence" in methods:
        click.echo(report.section(f"Top co-occurring pairs ({result.metric})"))
        click.echo(report.table(
            ["Pair", "Together", "PMI", "NPMI"],
            [(p.label, p.count, p.pmi, p.npmi) for p in result.pairs[:show]],
            empty_message="(no pair reaches analysis.cooccurrence.min_pair_frequency yet)",
        ))
    click.echo()
    ui.info("Next step: ngulik discover")


@cli.command(help="Score new keyword candidates from the corpus and queue them for review "
                  "(AC-010).")
@click.option("--max", "max_candidates", type=click.IntRange(min=1), default=None,
              help="How many candidates to propose. Default: discovery.max_candidates")
@click.option("--dry-run", is_flag=True, help="Show the ranking without saving candidates.")
@click.pass_context
def discover(ctx: click.Context, max_candidates: int | None = None,
             dry_run: bool = False) -> None:
    """Hasilkan kandidat dari korpus; tetap wajib lewat review."""
    config = _config(ctx)
    with open_db(config) as db:
        with ui.spinner("Scoring candidates from the corpus..."):
            result = discover_candidates(config, db, max_candidates=max_candidates,
                                         dry_run=dry_run)
    if not _need_corpus(result.documents):
        return

    click.echo()
    click.echo(report.key_values({
        "Comments analyzed": result.documents,
        "Seeds found in comments": result.seeds_in_corpus,
        "Terms passing the gate": result.pool,
        "Candidates ranked": len(result.candidates),
        "New candidates saved": "dry run, nothing saved" if dry_run else result.created,
    }, title="Discovery"))
    click.echo(report.section("Top candidates"))
    click.echo(report.table(
        ["#", "Term", "Type", "Score", "Main signal", "Comments", "Near seed"],
        [(i, c.term, c.keyword_type, c.score, c.method, c.doc_freq, c.seed or "-")
         for i, c in enumerate(result.candidates, start=1)],
        empty_message="(nothing passed the gate: min_doc_frequency / min_term_length)",
    ))
    if not result.seeds_in_corpus:
        click.echo()
        ui.warn("None of your active keywords appear in the cleaned comments, so the "
                "co-occurrence signal is off. Check your seeds or collect more.")
    if result.created:
        click.echo()
        ui.info("Next step: ngulik review")


# ---------------------------------------------------------------------------
# lexicon
# ---------------------------------------------------------------------------


@cli.group(help='Fetch slang terms from online dictionaries.')
def lexicon() -> None:
    """Ambil istilah slang dari kamus slang di internet."""


@lexicon.command("sources", help='List available lexicon sources.')
@click.pass_context
def lexicon_sources_cmd(ctx: click.Context) -> None:
    """Daftar sumber leksikon yang tersedia."""
    config = _config(ctx)
    rows = []
    for name in lexicon_sources():
        settings = config.section(f"lexicon.sources.{name}")
        rows.append((name, "enabled" if settings.get("enabled", True) else "disabled",
                     settings.get("base_url", "")))
    click.echo(report.table(["Source", "Status", "URL"], rows))


@lexicon.command("fetch", help='Download dictionary entries and propose them as candidates for review.')
@click.option("--source", "source_name", type=click.Choice(lexicon_sources()),
              default=lexicon_sources()[0], show_default=True)
@click.option("--limit", type=click.IntRange(min=1), default=None,
              help="Maximum entries to download. Default: lexicon.max_entries_per_run")
@click.option("--refresh", is_flag=True,
              help="Re-download all entries, even fresh ones.")
@click.pass_context
def lexicon_fetch(
    ctx: click.Context, source_name: str, limit: int | None, refresh: bool
) -> None:
    """Unduh entri kamus lalu usulkan sebagai kandidat untuk direview."""
    config = _config(ctx)
    with open_db(config) as db:
        try:
            source = get_source(source_name, config)
            with click.progressbar(length=1, show_pos=True, fill_char="█",
                                   empty_char="░",
                                   label=ui.style("[*]", fg="blue", bold=True)
                                   + " Downloading entries") as bar:
                def progress(done: int, total: int) -> None:
                    bar.length = total
                    bar.update(done - bar.pos)

                stats = fetch_lexicon(config, db, source, limit=limit,
                                      refresh=refresh, progress=progress)
        except LexiconError as exc:
            raise click.ClickException(str(exc)) from exc

        proposed = propose_candidates(config, db, source=source_name)
        click.echo(report.key_values(
            {
                "Source": source.description,
                "Entries in sitemap": stats.listed,
                "Still fresh (skipped)": stats.fresh_skipped,
                "Downloaded": stats.fetched,
                "Failed": stats.failed,
                "Excluded (category)": stats.excluded,
                "New candidates": proposed.created,
                "Already keywords": proposed.already_keyword,
                "Already proposed": proposed.already_candidate,
            },
            title="Lexicon",
        ))
        if proposed.created:
            click.echo()
            ui.info("Next step: python -m ngulik review")


@lexicon.command("list", help='Show downloaded lexicon entries.')
@click.option("--category", default=None, help="Filter by category, e.g. Plesetan.")
@click.option("--limit", type=click.IntRange(min=1), default=50, show_default=True)
@click.pass_context
def lexicon_list(ctx: click.Context, category: str | None, limit: int) -> None:
    """Tampilkan entri leksikon yang sudah diunduh."""
    config = _config(ctx)
    sql = "SELECT term, category, definition FROM lexicon_entries WHERE excluded = 0"
    params: list[object] = []
    if category:
        sql += " AND category = ? COLLATE NOCASE"
        params.append(category)
    with open_db(config) as db:
        rows = db.query(sql + " ORDER BY term LIMIT ?", [*params, limit])
        categories = db.query(
            "SELECT COALESCE(category, '-') AS c, COUNT(*) AS n FROM lexicon_entries "
            "WHERE excluded = 0 GROUP BY category ORDER BY n DESC"
        )
    click.echo(report.table(["Term", "Category", "Definition"],
                            [tuple(r) for r in rows], title="Lexicon entries"))
    click.echo(report.section("By category"))
    click.echo(report.table(["Category", "Count"], [tuple(r) for r in categories]))


# ---------------------------------------------------------------------------
# review & iterate
# ---------------------------------------------------------------------------


def _candidate_details(db: Database, candidate: KeywordCandidate) -> dict[str, object]:
    details: dict[str, object] = {
        "Term": candidate.term,
        "Type": str(candidate.type),
        "Method": candidate.source_method,
        "Score": candidate.score,
        "Found in comments": candidate.frequency,
        "Iteration": candidate.iteration,
        "Origin": candidate.discovered_from or "-",
    }
    if candidate.source_method == SourceMethod.LEXICON and candidate.discovered_from:
        entry = db.query_one(
            "SELECT category, definition, example FROM lexicon_entries WHERE url = ?",
            (candidate.discovered_from,),
        )
        if entry:
            details["Category"] = entry["category"] or "-"
            details["Definition"] = entry["definition"] or "-"
            if entry["example"]:
                details["Example"] = entry["example"]
    for index, text in enumerate(_example_comments(db, candidate.term), start=1):
        details[f"In comment {index}"] = text
    return details


def _example_comments(db: Database, term: str, limit: int = 2) -> list[str]:
    """Potongan komentar layak analisis yang memuat ``term``, untuk konteks review."""
    rows = db.query(
        "SELECT c.text_raw FROM cleaned_comments cc JOIN comments c ON c.id = cc.comment_id "
        "WHERE cc.is_spam = 0 AND cc.is_duplicate = 0 AND (' ' || cc.text_clean || ' ') LIKE ? "
        "ORDER BY length(c.text_raw) LIMIT ?",
        (f"% {term} %", limit),
    )
    return [" ".join(r["text_raw"].split())[:160] for r in rows]


@cli.command(help='Approve or reject keyword candidates (AC-011).')
@click.option("--list", "list_only", is_flag=True, help="Only list candidates, no review.")
@click.option("--method", type=click.Choice([m.value for m in SourceMethod],
                                            case_sensitive=False), default=None)
@click.option("--limit", type=click.IntRange(min=1), default=None)
@click.option("--approve", multiple=True, metavar="TERM",
              help="Approve a term non-interactively. Repeatable.")
@click.option("--reject", multiple=True, metavar="TERM",
              help="Reject a term non-interactively. Repeatable.")
@click.pass_context
def review(
    ctx: click.Context,
    list_only: bool,
    method: str | None,
    limit: int | None,
    approve: tuple[str, ...],
    reject: tuple[str, ...],
) -> None:
    """Setujui atau tolak kandidat keyword (AC-011)."""
    config = _config(ctx)
    with open_db(config) as db:
        if approve or reject:
            rows = []
            for terms, decision in ((approve, CandidateStatus.APPROVED),
                                    (reject, CandidateStatus.REJECTED)):
                for term in terms:
                    candidate = find_pending(db, term)
                    if candidate is None:
                        rows.append((term, "no PENDING candidate"))
                        continue
                    set_status(db, candidate.id, decision)
                    rows.append((candidate.term, str(decision)))
            click.echo(report.table(["Term", "Result"], rows))
            return

        candidates = list_candidates(db, method=method, limit=limit)
        if list_only or not candidates:
            click.echo(report.table(
                ["#", "Term", "Type", "Method", "Score", "Freq", "Origin"],
                [(c.id, c.term, c.type, c.source_method, c.score, c.frequency,
                  c.discovered_from or "-") for c in candidates],
                title=f"Candidates pending review ({len(candidates)})",
            ))
            return

        click.echo("a = approve, r = reject, s = skip, q = quit\n")
        decided = {"a": 0, "r": 0}
        for index, candidate in enumerate(candidates, start=1):
            click.echo(report.key_values(
                _candidate_details(db, candidate),
                title=f"Candidate {index}/{len(candidates)}",
            ))
            choice = click.prompt("Decision", type=click.Choice(["a", "r", "s", "q"]),
                                  default="s", show_choices=True)
            click.echo()
            if choice == "q":
                break
            if choice in decided:
                set_status(db, candidate.id, CandidateStatus.APPROVED
                           if choice == "a" else CandidateStatus.REJECTED)
                decided[choice] += 1

        click.echo(report.key_values(
            {"Approved": decided["a"], "Rejected": decided["r"]}, title="Review"))
        if decided["a"]:
            click.echo()
            ui.info("Next step: python -m ngulik iterate")


@cli.command(help='Promote approved candidates to seed keywords for the next iteration (AC-012).')
@click.pass_context
def iterate(ctx: click.Context) -> None:
    """Jadikan kandidat yang disetujui sebagai seed di iterasi berikutnya (AC-012)."""
    config = _config(ctx)
    with open_db(config) as db:
        result = promote_approved(db)
        click.echo(report.table(
            ["Term", "Type", "Iteration", "Origin"],
            [(k.term, k.type, k.iteration, k.discovered_from) for k in result.promoted],
            title=f"New keywords ({len(result.promoted)})",
            empty_message="(no approved candidates left to promote)",
        ))
        if result.promoted:
            click.echo()
            _report_matches(match_keywords(config, db))
            ui.good(f"Current iteration: {result.iteration}")
            ui.info("Next step: python -m ngulik collect")


# ---------------------------------------------------------------------------
# Konsol interaktif
# ---------------------------------------------------------------------------


@cli.command(help="Start the interactive msfconsole-style shell (default when no command is given).")
@click.pass_context
def console(ctx: click.Context) -> None:
    """Konsol interaktif; logikanya ada di :mod:`ngulik.console`."""
    from ngulik.console import NgulikConsole

    NgulikConsole(ctx).loop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point ``ngulik`` dan ``python -m ngulik``."""
    # Konsol Windows dan output yang di-pipe sering memakai code page lama;
    # tanpa ini karakter kotak di tabel memicu UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        code = cli.main(prog_name="ngulik", standalone_mode=False)
    except click.UsageError as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except click.ClickException as exc:
        ui.error(exc.format_message())
        sys.exit(exc.exit_code)
    except click.Abort:
        click.echo()
        ui.warn("Aborted")
        sys.exit(1)
    sys.exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    main()
