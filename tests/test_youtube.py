"""Test mode video pilihan YouTube dan pencocokan keyword. API YouTube ditiru."""

from __future__ import annotations

import pytest

from ngulik.collectors import CollectorError, run_collection
from ngulik.collectors.youtube import (
    COMMENT_THREADS_URL,
    VIDEOS_URL,
    YouTubeCollector,
    parse_video_id,
)
from ngulik.matching import match_keywords

VIDEO = "dQw4w9WgXcQ"
MISSING = "AAAAAAAAAAA"


@pytest.mark.parametrize("value", [
    VIDEO,
    f"https://www.youtube.com/watch?v={VIDEO}&t=42s",
    f"https://m.youtube.com/watch?feature=share&v={VIDEO}",
    f"https://youtu.be/{VIDEO}?si=abc",
    f"youtube.com/shorts/{VIDEO}",
    f"https://www.youtube.com/live/{VIDEO}",
])
def test_parse_video_id_accepts_common_forms(value):
    assert parse_video_id(value) == VIDEO


@pytest.mark.parametrize("value", ["", "hello", "https://example.com/watch?v=" + VIDEO])
def test_parse_video_id_rejects_non_youtube(value):
    with pytest.raises(CollectorError):
        parse_video_id(value)


def _thread(cid: str, text: str, replies: list[tuple[str, str]] = ()) -> dict:
    node = lambda i, t: {"id": i, "snippet": {"textOriginal": t,  # noqa: E731
                                              "authorDisplayName": "SHOULD NOT BE STORED"}}
    return {"snippet": {"topLevelComment": node(cid, text)},
            "replies": {"comments": [node(i, t) for i, t in replies]}}


@pytest.fixture
def fake_api(monkeypatch):
    """Tiru dua endpoint yang dipakai mode video; catat setiap panggilan."""
    calls: list[str] = []

    def fake_request(self, url, params):
        calls.append(url)
        if url == VIDEOS_URL:
            return {"items": [{"id": VIDEO, "snippet": {"title": "Video uji"}}]}
        if url == COMMENT_THREADS_URL:
            assert params["videoId"] == VIDEO
            assert "searchTerms" not in params
            return {"items": [
                _thread("c1", "ayo rek nonton bareng", [("c1r", "rekam dulu")]),
                _thread("c2", "#Gabut banget videonya"),
                _thread("c3", "MAS  mas GABUT lewat"),
            ]}
        raise AssertionError(f"unexpected call to {url}")

    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setattr(YouTubeCollector, "_request", fake_request)
    return calls


def test_selected_videos_need_no_keywords_and_no_search(config, db, fake_api):
    collector = YouTubeCollector(config, db, videos=[f"https://youtu.be/{VIDEO}", MISSING])

    run = run_collection(config, db, collector, [], limit=100)

    assert run.comments_collected == 4
    assert _no_search_calls(fake_api)
    assert run.params["search_calls"] == 0
    assert run.params["videos"] == [VIDEO, MISSING]
    video = db.query_one("SELECT keyword, title FROM videos WHERE video_id = ?", (VIDEO,))
    assert video["keyword"] is None and video["title"] == "Video uji"
    stored = " ".join(r["text_raw"] for r in db.query("SELECT text_raw FROM comments"))
    assert "SHOULD NOT BE STORED" not in stored


def _no_search_calls(calls: list[str]) -> bool:
    return all(not url.endswith("/search") for url in calls)


def test_keyword_match_uses_whole_words_and_hashtags(config, db, fake_api):
    run_collection(config, db, YouTubeCollector(config, db, videos=[VIDEO]), [], limit=100)
    for term, kind in (("rek", "KEYWORD"), ("#gabut", "HASHTAG"), ("mas mas gabut", "PHRASE")):
        db.execute(
            "INSERT INTO keywords (term, type, status, created_at, updated_at) "
            "VALUES (?, ?, 'ACTIVE', 'x', 'x')", (term, kind))
    db.commit()

    stats = match_keywords(config, db)

    matches = {
        (r["source_id"], r["term"])
        for r in db.query(
            "SELECT c.source_id, k.term FROM comment_keyword_matches m "
            "JOIN comments c ON c.id = m.comment_id JOIN keywords k ON k.id = m.keyword_id")
    }
    assert ("c1", "rek") in matches
    assert not any(sid == "c1r" for sid, _ in matches)  # "rekam" bukan "rek"
    assert ("c2", "#gabut") in matches
    assert {("c3", "mas mas gabut"), ("c3", "#gabut")} <= matches
    assert stats.comments_matched == 3


def test_keyword_match_is_rebuilt_when_keywords_change(config, db, fake_api):
    run_collection(config, db, YouTubeCollector(config, db, videos=[VIDEO]), [], limit=100)
    db.execute("INSERT INTO keywords (term, type, status, created_at, updated_at) "
               "VALUES ('rek', 'KEYWORD', 'ACTIVE', 'x', 'x')")
    db.commit()
    assert match_keywords(config, db).comments_matched == 1

    db.execute("UPDATE keywords SET status = 'INACTIVE'")
    db.commit()
    assert match_keywords(config, db).comments_matched == 0
    assert db.scalar("SELECT COUNT(*) FROM comment_keyword_matches") == 0
