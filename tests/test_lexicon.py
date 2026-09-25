"""Test sumber leksikon, pengusulan kandidat, review, dan promosi. Tanpa jaringan."""

from __future__ import annotations

import pytest

from ngulik.discovery import find_pending, promote_approved, set_status
from ngulik.lexicon import KbbjSource, fetch_lexicon, propose_candidates
from ngulik.lexicon.kbbj import parse_sitemap
from ngulik.models import CandidateStatus

BASE = "https://kbbj.web.id/kata/"

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://kbbj.web.id/kata/kata-uji</loc></url>
  <url><loc>https://kbbj.web.id/kata/tokoh-uji</loc></url>
  <url><loc>https://kbbj.web.id/kata/sendiri</loc></url>
  <url><loc>https://kbbj.web.id/contributors</loc></url>
</urlset>"""


def entry_html(term: str, category: str) -> str:
    """Tiruan struktur halaman entri KBBJ, termasuk bagian kontributor."""
    return f"""<html><body><article class="word-card">
      <header class="word-header">
        <a href="/?kategori=x" class="word-category"> {category} </a>
        <h1 class="word-title"> {term} </h1>
      </header>
      <section class="word-section"><div class="definition">
        Definisi <a href="{BASE}lain">tautan</a> &amp; lanjutan.<br>Baris dua.
      </div></section>
      <section class="word-section"><div class="example">“contoh {term}”</div></section>
      <section class="contributor"><h2>Diusulkan oleh</h2>
        <img src="x" alt="NamaKontributor"><div class="contributor-info">NamaKontributor</div>
      </section>
    </article></body></html>"""


PAGES = {
    f"{BASE}kata-uji": entry_html("Kata Uji", "Istilah"),
    f"{BASE}tokoh-uji": entry_html("Tokoh Uji", "Nama Orang"),
    f"{BASE}sendiri": entry_html("Sendiri", "Ungkapan"),
}


class FakeFetcher:
    """Pengganti PoliteFetcher: menyajikan halaman dari memori, mencatat request."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        return SITEMAP if url.endswith(".xml") else PAGES[url]


@pytest.fixture
def source(config) -> KbbjSource:
    return KbbjSource(config, fetcher=FakeFetcher())


def test_parse_entry_reads_fields_and_ignores_contributor(source):
    entry = source.parse_entry(f"{BASE}kata-uji", PAGES[f"{BASE}kata-uji"])

    assert entry.term == "Kata Uji"
    assert entry.category == "Istilah"
    assert entry.definition == "Definisi tautan & lanjutan. Baris dua."
    assert entry.example == "“contoh Kata Uji”"
    assert entry.entry_key == "kata-uji"
    assert "NamaKontributor" not in repr(entry)


def test_sitemap_keeps_only_entry_urls(source):
    assert len(parse_sitemap(SITEMAP)) == 4
    assert source.list_entry_urls() == list(PAGES)


def test_fetch_excludes_person_names_without_keeping_them(config, db, source):
    stats = fetch_lexicon(config, db, source)

    assert (stats.fetched, stats.excluded, stats.stored) == (3, 1, 2)
    dump = " ".join(str(tuple(r)) for r in db.query("SELECT * FROM lexicon_entries"))
    assert "tokoh" not in dump.lower()


def test_fresh_entries_are_not_downloaded_again(config, db, source):
    fetch_lexicon(config, db, source)
    source.fetcher.requested.clear()

    stats = fetch_lexicon(config, db, source)

    assert stats.fresh_skipped == 3
    assert source.fetcher.requested == [str(config.get("lexicon.sources.kbbj.sitemap"))]


def test_candidates_skip_keywords_and_previous_rejections(config, db, source):
    fetch_lexicon(config, db, source)
    db.execute(
        "INSERT INTO keywords (term, type, status, created_at, updated_at) "
        "VALUES ('sendiri', 'KEYWORD', 'ACTIVE', 'x', 'x')"
    )
    db.commit()

    first = propose_candidates(config, db)
    assert (first.created, first.already_keyword) == (1, 1)

    set_status(db, find_pending(db, "kata uji").id, CandidateStatus.REJECTED)
    again = propose_candidates(config, db)
    assert again.created == 0 and again.already_candidate == 1


def test_approved_candidate_becomes_next_iteration_keyword(config, db, source):
    fetch_lexicon(config, db, source)
    propose_candidates(config, db)
    set_status(db, find_pending(db, "kata uji").id, CandidateStatus.APPROVED)

    result = promote_approved(db)

    assert [k.term for k in result.promoted] == ["kata uji"]
    assert result.promoted[0].iteration == 1
    assert "LEXICON" in result.promoted[0].discovered_from
    assert promote_approved(db).promoted == []
