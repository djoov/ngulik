"""Collector YouTube Data API v3 (FR-002).

Tiga kenyataan API yang membentuk seluruh desain modul ini:

**1. Tidak ada pencarian komentar global.** ``commentThreads.list`` wajib
di-scope ke satu ``videoId`` atau satu channel. Jadi alurnya selalu dua
langkah: cari video dulu, baru tarik komentarnya.

**2. Kuota ``search.list`` terpisah dan sangat kecil: 100 call/hari**, di luar
pool 10.000 unit. Sementara ``commentThreads.list`` hanya 1 unit dari pool
tersebut. Artinya *mencari video itu langka, mengambil komentar itu murah*.
Konsekuensinya hasil search di-cache ke tabel ``videos`` dan dipakai ulang
lintas iterasi — tanpa itu, beberapa kali ``collect`` saja sudah menghabiskan
jatah harian. Kuota reset tengah malam Pacific Time.

**3. Parameter ``searchTerms`` sengaja tidak dipakai secara default.** Ia
memaksa komentar harus mengandung seed keyword, yang berarti sistem hanya
menemukan kata yang sudah diketahui — persis kelemahan keyword statis yang
ingin dipecahkan PRD bagian 1.2. Default-nya: cari video yang topikal, lalu
ambil *semua* komentarnya, dan biarkan analisis yang menemukan kata barunya.

**Mode video pilihan.** Bila collector dibuat dengan ``videos=[...]``,
pencarian dilewati sama sekali: komentar diambil langsung dari video yang
disebut pengguna. Mode ini tidak memakai jatah ``search.list``; metadata video
diambil lewat ``videos.list`` yang hanya 1 unit per 50 video.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from ngulik.collectors.base import (
    Collector,
    CollectorError,
    CollectorNotConfigured,
    QuotaExceeded,
)
from ngulik.config import get_logger
from ngulik.models import RawComment, utc_now_iso

logger = get_logger("collectors.youtube")

API_ROOT = "https://www.googleapis.com/youtube/v3"
SEARCH_URL = f"{API_ROOT}/search"
COMMENT_THREADS_URL = f"{API_ROOT}/commentThreads"
VIDEOS_URL = f"{API_ROOT}/videos"

#: ID video YouTube: 11 karakter base64-url.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_PATH = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})")


def parse_video_id(value: str) -> str:
    """Ambil ID video dari URL YouTube atau ID mentah.

    Menerima ``watch?v=``, ``youtu.be/``, ``/shorts/``, ``/live/``, dan
    ``/embed/``. Melempar :class:`CollectorError` bila tidak dikenali.
    """
    text = (value or "").strip()
    if _VIDEO_ID.match(text):
        return text
    parts = urlsplit(text if "://" in text else f"https://{text}")
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    candidate = ""
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        candidate = (parse_qs(parts.query).get("v") or [""])[0]
        if not candidate and (match := _VIDEO_PATH.match(parts.path)):
            candidate = match.group(1)
    if _VIDEO_ID.match(candidate):
        return candidate
    raise CollectorError(f"Not a YouTube video URL or ID: {value!r}")

#: Alasan error 403 yang berarti "berhenti sekarang", bukan "coba lagi".
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
#: Alasan yang berarti "lewati video ini", bukan "gagalkan seluruh run".
_SKIP_VIDEO_REASONS = {
    "commentsDisabled",
    "videoNotFound",
    "forbidden",
    "processingFailure",
}


class YouTubeCollector(Collector):
    """Ambil komentar publik dari YouTube berdasarkan seed keyword."""

    name = "youtube"
    description = "Public comments via YouTube Data API v3 (needs an API key)"

    def __init__(
        self,
        config,
        db,
        videos: list[str] | None = None,
        max_pages: int | None = None,
    ) -> None:
        super().__init__(config, db)
        self.settings = config.section("collection.youtube")
        self.store_author = bool(
            config.get("collection.privacy.store_author_id", False)
        )
        self.api_key = config.youtube_api_key
        self.search_calls = 0
        self._session = requests.Session()
        # Mode video pilihan; dedup urutan tetap dipertahankan.
        self.videos = list(dict.fromkeys(parse_video_id(v) for v in videos or []))
        self.max_pages = max_pages

    @property
    def needs_keywords(self) -> bool:
        """Mode video pilihan tidak butuh keyword untuk mencari video."""
        return not self.videos

    # -- kesiapan -----------------------------------------------------------

    def check_ready(self) -> None:
        if not self.api_key:
            raise CollectorNotConfigured(
                "YOUTUBE_API_KEY is not set.\n\n"
                "  1. Copy .env.example to .env\n"
                "  2. Set YOUTUBE_API_KEY=<your key>\n\n"
                "How to create a key is described in README.md, section "
                "'Menyiapkan YouTube API Key'.\n"
                "To try the pipeline without an API key:\n"
                "  python -m ngulik collect --source file "
                "--path data/fixtures/sample_comments.json"
            )

    def run_params(self) -> dict[str, object]:
        """Snapshot parameter untuk reproducibility (NFR-002)."""
        if self.videos:
            return {"mode": "videos", "videos": self.videos,
                    "max_pages": self._selected_pages()}
        return {
            "max_videos_per_keyword": self.settings.get("max_videos_per_keyword"),
            "max_comment_pages_per_video": self.settings.get(
                "max_comment_pages_per_video"
            ),
            "order": self.settings.get("order"),
            "region_code": self.settings.get("region_code"),
            "published_after": self.settings.get("published_after"),
            "use_search_terms": self.settings.get("use_search_terms"),
        }

    def run_stats(self) -> dict[str, object]:
        """Jumlah call ``search.list`` run ini.

        Disimpan terpisah dari ``quota_used`` karena search punya jatah harian
        sendiri (100 call) yang tidak bisa dibaca ulang dari total unit.
        """
        return {"search_calls": self.search_calls}

    # -- lapisan HTTP -------------------------------------------------------

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET dengan retry backoff, menerjemahkan error API jadi exception kita.

        Membedakan tiga kelas kegagalan: kuota habis (hentikan run, tandai
        PARTIAL), error per-video seperti komentar dimatikan (lewati saja),
        dan error sementara seperti 5xx (coba lagi).
        """
        params = {**params, "key": self.api_key}
        attempts = int(self.settings.get("retry_attempts", 3))
        backoff = float(self.settings.get("retry_backoff", 2.0))
        timeout = int(self.settings.get("request_timeout", 30))

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._session.get(url, params=params, timeout=timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    delay = backoff ** attempt
                    logger.warning(
                        "Network request failed (%s), retrying in %.1fs [%d/%d]",
                        exc, delay, attempt, attempts,
                    )
                    time.sleep(delay)
                    continue
                raise CollectorError(f"Request to YouTube failed: {exc}") from exc

            if response.status_code == 200:
                return response.json()

            reason, message = _parse_api_error(response)

            if response.status_code == 403 and reason in _QUOTA_REASONS:
                raise QuotaExceeded(
                    f"YouTube API quota exhausted ({reason}). "
                    f"Quota resets at midnight Pacific Time. "
                    f"Data collected so far has been kept."
                )

            if reason in _SKIP_VIDEO_REASONS:
                raise _SkipTarget(f"{reason}: {message}")

            if response.status_code == 429 or response.status_code >= 500:
                last_error = CollectorError(f"HTTP {response.status_code}: {message}")
                if attempt < attempts:
                    delay = backoff ** attempt
                    logger.warning(
                        "HTTP %d from YouTube, retrying in %.1fs [%d/%d]",
                        response.status_code, delay, attempt, attempts,
                    )
                    time.sleep(delay)
                    continue

            raise CollectorError(
                f"YouTube API error HTTP {response.status_code} "
                f"({reason or 'no reason given'}): {message}"
            )

        raise CollectorError(f"Request to YouTube failed: {last_error}")

    # -- pencarian video ----------------------------------------------------

    def _cached_videos(self, keyword: str, wanted: int) -> list[str]:
        rows = self.db.query(
            "SELECT video_id FROM videos WHERE keyword = ? "
            "ORDER BY discovered_at DESC LIMIT ?",
            (keyword, wanted),
        )
        return [row["video_id"] for row in rows]

    def _search_videos(self, keyword: str) -> list[str]:
        """Cari video untuk satu keyword, memakai cache bila memungkinkan.

        Inilah titik paling mahal di seluruh sistem: jatahnya hanya 100 call
        per hari untuk seluruh project.
        """
        wanted = int(self.settings.get("max_videos_per_keyword", 25))

        cached = self._cached_videos(keyword, wanted)
        if len(cached) >= wanted:
            logger.info(
                "Keyword %r: using %d cached videos (saved 1 search.list call)",
                keyword, len(cached),
            )
            return cached

        budget = int(self.settings.get("max_search_calls_per_run", 10))
        if self.search_calls >= budget:
            logger.warning(
                "search.list budget for this run is used up (%d calls). "
                "Keyword %r uses its %d cached videos only.",
                budget, keyword, len(cached),
            )
            return cached

        params: dict[str, Any] = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "maxResults": min(50, wanted),
            "order": self.settings.get("order", "relevance"),
        }
        if region := self.settings.get("region_code"):
            params["regionCode"] = region
        if language := self.settings.get("relevance_language"):
            params["relevanceLanguage"] = language
        if published_after := self.settings.get("published_after"):
            params["publishedAfter"] = published_after

        try:
            payload = self._request(SEARCH_URL, params)
        except _SkipTarget as exc:
            logger.warning("Search for %r skipped: %s", keyword, exc)
            return cached

        self.search_calls += 1
        self.quota_used += 100  # biaya nominal search.list

        video_ids: list[str] = []
        now = utc_now_iso()
        for item in payload.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet") or {}
            self.db.execute(
                """
                INSERT INTO videos
                    (video_id, keyword, title, channel_id, published_at, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET keyword = excluded.keyword
                """,
                (
                    video_id,
                    keyword,
                    snippet.get("title"),
                    snippet.get("channelId"),
                    snippet.get("publishedAt"),
                    now,
                ),
            )
            video_ids.append(video_id)
        self.db.commit()

        logger.info(
            "Keyword %r: %d videos found (search.list call %d/%d for this run)",
            keyword, len(video_ids), self.search_calls, budget,
        )

        merged = list(dict.fromkeys(video_ids + cached))
        return merged[:wanted]

    # -- pengambilan komentar -----------------------------------------------

    def _selected_pages(self) -> int:
        if self.max_pages:
            return int(self.max_pages)
        return int(self.settings.get("max_comment_pages_per_selected_video", 10))

    def _register_videos(self, video_ids: list[str]) -> list[str]:
        """Simpan metadata video pilihan ke ``videos``; kembalikan yang ditemukan.

        ``keyword`` dibiarkan NULL: video ini dipilih manusia, bukan hasil
        pencarian keyword. 1 unit kuota per 50 video.
        """
        found: list[str] = []
        now = utc_now_iso()
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start:start + 50]
            payload = self._request(VIDEOS_URL, {"part": "snippet", "id": ",".join(chunk)})
            self.quota_used += 1
            for item in payload.get("items", []):
                snippet = item.get("snippet") or {}
                self.db.execute(
                    """
                    INSERT INTO videos
                        (video_id, keyword, title, channel_id, published_at, discovered_at)
                    VALUES (?, NULL, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET title = excluded.title
                    """,
                    (item["id"], snippet.get("title"), snippet.get("channelId"),
                     snippet.get("publishedAt"), now),
                )
                found.append(item["id"])
        self.db.commit()

        for missing in [v for v in video_ids if v not in found]:
            logger.warning("Video %s not found or not public, skipped", missing)
        return [v for v in video_ids if v in found]

    def _fetch_comments(
        self, video_id: str, keyword: str | None, max_pages: int | None = None
    ) -> Iterator[RawComment]:
        """Ambil comment thread satu video. 1 unit kuota per halaman."""
        max_pages = max_pages or int(self.settings.get("max_comment_pages_per_video", 2))
        per_page = min(100, int(self.settings.get("comments_per_page", 100)))
        include_replies = bool(self.settings.get("include_replies", True))

        params: dict[str, Any] = {
            "part": "snippet,replies" if include_replies else "snippet",
            "videoId": video_id,
            "maxResults": per_page,
            "order": "relevance",
            "textFormat": "plainText",
        }
        # Lihat catatan modul: default-nya mati secara sengaja.
        if keyword and self.settings.get("use_search_terms"):
            params["searchTerms"] = keyword

        page_token: str | None = None
        fetched = 0

        for _ in range(max_pages):
            if page_token:
                params["pageToken"] = page_token
            try:
                payload = self._request(COMMENT_THREADS_URL, params)
            except _SkipTarget as exc:
                # Di mode video pilihan, pengguna perlu tahu kenapa videonya kosong.
                log = logger.warning if self.videos else logger.debug
                log("Video %s skipped: %s", video_id, exc)
                return

            self.quota_used += 1

            for item in payload.get("items", []):
                thread = (item.get("snippet") or {}).get("topLevelComment") or {}
                if comment := self._to_raw_comment(thread, video_id, keyword):
                    fetched += 1
                    yield comment

                if not include_replies:
                    continue
                for reply in (item.get("replies") or {}).get("comments", []):
                    if comment := self._to_raw_comment(reply, video_id, keyword):
                        fetched += 1
                        yield comment

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        self.db.execute(
            "UPDATE videos SET comments_fetched = comments_fetched + ? WHERE video_id = ?",
            (fetched, video_id),
        )

    def _to_raw_comment(
        self, node: dict[str, Any], video_id: str, keyword: str | None
    ) -> RawComment | None:
        """Ubah satu node komentar API menjadi :class:`RawComment`.

        Di sinilah PRD bagian 16 ditegakkan. ``authorDisplayName`` yang
        dikirim API tidak pernah dibaca — tidak ada jalur kode mana pun yang
        bisa menyimpannya. ``author_id`` hanya terisi bila pengguna secara
        eksplisit menyalakannya di konfigurasi.
        """
        comment_id = node.get("id")
        snippet = node.get("snippet") or {}
        text = snippet.get("textOriginal") or snippet.get("textDisplay")
        if not comment_id or not text or not str(text).strip():
            return None

        author_id = None
        if self.store_author:
            author_id = (snippet.get("authorChannelId") or {}).get("value")

        return RawComment(
            source="youtube",
            source_id=str(comment_id),
            text=str(text),
            author_id=author_id,
            created_at=snippet.get("publishedAt"),
            url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
            keyword=keyword,
        )

    # -- kontrak collector --------------------------------------------------

    def collect(self, keywords: list[str], limit: int) -> Iterator[RawComment]:
        if self.videos:
            yield from self._collect_selected(limit)
            return

        emitted = 0
        for keyword in keywords:
            if emitted >= limit:
                logger.info("Comment limit %d reached", limit)
                return

            for video_id in self._search_videos(keyword):
                if emitted >= limit:
                    return
                for comment in self._fetch_comments(video_id, keyword):
                    yield comment
                    emitted += 1
                    if emitted >= limit:
                        self.db.commit()
                        return
            self.db.commit()

    def _collect_selected(self, limit: int) -> Iterator[RawComment]:
        """Ambil komentar dari video yang dipilih pengguna, tanpa search.list."""
        pages = self._selected_pages()
        video_ids = self._register_videos(self.videos)
        emitted = 0
        for video_id in video_ids:
            fetched = 0
            for comment in self._fetch_comments(video_id, None, max_pages=pages):
                yield comment
                emitted += 1
                fetched += 1
                if emitted >= limit:
                    self.db.commit()
                    logger.info("Comment limit %d reached", limit)
                    return
            logger.info("Video %s: %d comments fetched", video_id, fetched)
            self.db.commit()


class _SkipTarget(CollectorError):
    """Internal: target ini bermasalah, lanjutkan ke target berikutnya."""


def _parse_api_error(response: requests.Response) -> tuple[str, str]:
    """Ekstrak ``(reason, message)`` dari body error YouTube."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return "", response.text[:200]

    message = error.get("message", "")
    errors = error.get("errors") or []
    reason = errors[0].get("reason", "") if errors else ""
    return reason, message
