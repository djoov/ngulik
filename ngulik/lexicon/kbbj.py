"""Adaptor Kamus Besar Bahasa Jomok (https://kbbj.web.id/).

Hasil survei situs (2026-09-23):

* ``robots.txt`` mengizinkan semua dan menunjuk ke sitemap.
* ``sitemap-words.xml`` memuat seluruh URL entri ``/kata/<slug>``, jadi
  pagination tidak perlu dirayapi.
* Halaman entri: kategori di ``a.word-category``, istilah di
  ``h1.word-title``, definisi di ``div.definition``, contoh di
  ``div.example``.
* Bagian "Diusulkan oleh" (``section.contributor``) berisi nama kontributor
  dan sengaja tidak dibaca (PRD bagian 16).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from ngulik.lexicon.base import LexiconError, LexiconSource
from ngulik.models import LexiconEntry

__all__ = ["KbbjSource", "parse_sitemap"]

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_ENTRY_PATH = re.compile(r"^/kata/([^/]+)/?$")
_WHITESPACE = re.compile(r"\s+")

#: Elemen HTML tanpa tag penutup; tidak boleh menambah kedalaman.
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "source", "track", "wbr"}

#: Kelas CSS -> nama field pada LexiconEntry.
_FIELD_CLASSES = {
    "word-category": "category",
    "word-title": "term",
    "definition": "definition",
    "example": "example",
}


def parse_sitemap(xml_text: str) -> list[str]:
    """Ambil semua ``<loc>`` dari sitemap XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise LexiconError(f"Invalid sitemap: {exc}") from exc
    return [
        loc.text.strip()
        for loc in root.iter(f"{_SITEMAP_NS}loc")
        if loc.text and loc.text.strip()
    ]


class _EntryParser(HTMLParser):
    """Ambil teks dari elemen pertama untuk tiap kelas di :data:`_FIELD_CLASSES`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self._field: str | None = None
        self._depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._field is not None:
            if tag == "br":
                self._buffer.append(" ")
            elif tag not in _VOID_TAGS:
                self._depth += 1
            return
        classes = (dict(attrs).get("class") or "").split()
        for css_class, field in _FIELD_CLASSES.items():
            if css_class in classes and field not in self.fields:
                self._field, self._depth, self._buffer = field, 1, []
                return

    def handle_endtag(self, tag: str) -> None:
        if self._field is None or tag in _VOID_TAGS:
            return
        self._depth -= 1
        if self._depth == 0:
            text = _WHITESPACE.sub(" ", "".join(self._buffer)).strip()
            if text:
                self.fields[self._field] = text
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._field is not None:
            self._buffer.append(data)


class KbbjSource(LexiconSource):
    """Kamus Besar Bahasa Jomok."""

    name = "kbbj"
    description = "Kamus Besar Bahasa Jomok (kbbj.web.id)"

    def list_entry_urls(self) -> list[str]:
        sitemap = str(self.settings.get("sitemap", "https://kbbj.web.id/sitemap-words.xml"))
        urls = parse_sitemap(self.fetcher.get(sitemap))
        return [url for url in urls if _ENTRY_PATH.match(urlsplit(url).path)]

    def entry_key(self, url: str) -> str:
        match = _ENTRY_PATH.match(urlsplit(url).path)
        if not match:
            raise LexiconError(f"Not a KBBJ entry URL: {url}")
        return unquote(match.group(1))

    def parse_entry(self, url: str, html: str) -> LexiconEntry | None:
        parser = _EntryParser()
        parser.feed(html)
        parser.close()
        fields = parser.fields
        if "term" not in fields:
            return None
        return LexiconEntry(
            source=self.name,
            entry_key=self.entry_key(url),
            url=url,
            term=fields["term"],
            category=fields.get("category"),
            definition=fields.get("definition"),
            example=fields.get("example"),
        )
