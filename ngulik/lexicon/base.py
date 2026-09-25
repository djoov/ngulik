"""Kontrak sumber leksikon dan pengambil HTTP yang sopan (CLAUDE.md Prioritas 8).

Sumber leksikon berbeda dari :class:`~ngulik.collectors.base.Collector`:
keluarannya istilah beserta definisinya, bukan komentar. Karena itu hasilnya
tidak masuk ke tabel ``comments`` maupun pipeline cleaning, melainkan ke
``lexicon_entries`` lalu diusulkan sebagai kandidat keyword yang tetap harus
direview manusia (PRD bagian 8).

:class:`PoliteFetcher` memusatkan aturan sopan-santun terhadap situs sumber:
User-Agent jujur, jeda antar-request, patuh robots.txt, dan retry dengan
backoff yang menghormati ``Retry-After``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from ngulik.config import Config, get_logger
from ngulik.models import LexiconEntry

__all__ = ["LexiconError", "LexiconSource", "PoliteFetcher"]

logger = get_logger("lexicon")

#: Status HTTP yang layak dicoba ulang.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class LexiconError(RuntimeError):
    """Kegagalan pada sumber leksikon."""


class PoliteFetcher:
    """Pengambil halaman dengan jeda, retry, dan kepatuhan robots.txt."""

    def __init__(self, config: Config) -> None:
        settings = config.section("lexicon")
        self.user_agent = str(settings.get("user_agent", "Ngulik"))
        self.delay = float(settings.get("request_delay", 2.0))
        self.timeout = float(settings.get("request_timeout", 30))
        self.retry_attempts = int(settings.get("retry_attempts", 3))
        self.retry_backoff = float(settings.get("retry_backoff", 2.0))
        self.respect_robots = bool(settings.get("respect_robots_txt", True))

        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.user_agent
        self._last_request = 0.0
        self._robots: dict[str, RobotFileParser | None] = {}
        self.requests_made = 0

    def get(self, url: str) -> str:
        """Ambil teks halaman. Melempar :class:`LexiconError` bila gagal."""
        if not self.allowed(url):
            raise LexiconError(f"Disallowed by robots.txt: {url}")

        last_error = ""
        for attempt in range(1, self.retry_attempts + 1):
            self._wait()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                wait = self.retry_backoff ** attempt
            else:
                if response.ok:
                    response.encoding = response.encoding or "utf-8"
                    return response.text
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in _RETRY_STATUS:
                    break
                wait = _retry_after(response) or self.retry_backoff ** attempt

            if attempt < self.retry_attempts:
                logger.debug("Failed to fetch %s (%s), retrying in %.1fs", url, last_error, wait)
                time.sleep(wait)

        raise LexiconError(f"Failed to fetch {url}: {last_error}")

    def allowed(self, url: str) -> bool:
        """Apakah robots.txt situs mengizinkan User-Agent ini mengambil ``url``."""
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # -- internal -----------------------------------------------------------

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
        self.requests_made += 1

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        """Unduh robots.txt lewat session ini.

        ``RobotFileParser.read()`` tidak dipakai karena memakai User-Agent
        urllib bawaan; sebagian situs menjawab 403 untuk itu, dan parser
        lalu menganggap seluruh situs terlarang.
        """
        self._wait()
        try:
            response = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Could not read robots.txt of %s (%s), proceeding carefully", origin, exc)
            return None
        if response.status_code >= 400:
            # Konvensi robots.txt: tidak ada berkas berarti tidak ada larangan.
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


class LexiconSource(ABC):
    """Basis untuk adaptor kamus slang per situs.

    Subclass mengisi :attr:`name` dan :attr:`description`, lalu
    mengimplementasikan dua langkah: :meth:`list_entry_urls` (daftar halaman
    entri) dan :meth:`parse_entry` (HTML satu entri menjadi
    :class:`~ngulik.models.LexiconEntry`).
    """

    name: str = "base"
    description: str = ""

    def __init__(self, config: Config, fetcher: PoliteFetcher | None = None) -> None:
        self.config = config
        self.settings = config.section(f"lexicon.sources.{self.name}")
        self.fetcher = fetcher or PoliteFetcher(config)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    @abstractmethod
    def list_entry_urls(self) -> list[str]:
        """URL semua halaman entri yang tersedia."""
        raise NotImplementedError

    @abstractmethod
    def entry_key(self, url: str) -> str:
        """Kunci stabil sebuah entri, biasanya slug dari URL."""
        raise NotImplementedError

    @abstractmethod
    def parse_entry(self, url: str, html: str) -> LexiconEntry | None:
        """Ubah HTML satu entri menjadi :class:`LexiconEntry`. ``None`` bila bukan entri."""
        raise NotImplementedError

    def fetch_entry(self, url: str) -> LexiconEntry | None:
        return self.parse_entry(url, self.fetcher.get(url))
