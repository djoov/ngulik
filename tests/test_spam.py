"""Test aturan spam per komentar dan copypasta."""

from __future__ import annotations

import pytest

from ngulik.cleaning import CleaningPipeline, SpamFilter
from ngulik.cleaning.spam import reason_codes
from tests.conftest import insert_comments


@pytest.fixture
def spam(config) -> SpamFilter:
    return SpamFilter(config)


def _check(spam: SpamFilter, text: str, tokens: list[str] | None = None) -> str | None:
    raw = text.lower().split()
    return spam.check(text, raw, tokens if tokens is not None else raw)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("hubungi wa 081234567890 sekarang", "phone_number"),
        ("lihat http://a.id http://b.id http://c.id", "too_many_urls"),
        ("@a @b @c @d @e @f halo semua", "too_many_mentions"),
        ("#a #b #c #d #e #f halo semua", "too_many_hashtags"),
        ("aaaaaaaaaaaaaaaa keren", "char_run"),
        ("mantap mantap mantap mantap mantap", "low_diversity"),
    ],
)
def test_rules_report_specific_reason(spam, text, code):
    assert code in reason_codes(_check(spam, text))


def test_too_few_tokens_uses_final_tokens(spam):
    assert reason_codes(_check(spam, "ok sip", tokens=["ok"])) == ["too_few_tokens"]


def test_normal_comment_passes(spam):
    assert _check(spam, "penjelasan di video ini jelas dan runtut") is None


def test_multiple_reasons_are_all_kept(spam):
    codes = reason_codes(_check(spam, "aaaaaaaaaaaaaaaa", tokens=[]))
    assert codes == ["char_run", "too_few_tokens"]


def test_copypasta_marks_every_copy(config, db):
    text = "komentar ini dikirim oleh banyak akun berbeda"
    insert_comments(db, [text] * 5 + ["komentar lain yang wajar dan berbeda isinya"])

    stats = CleaningPipeline(config, db).run()

    assert stats.copypasta == 5
    reasons = [r["spam_reason"] for r in db.query(
        "SELECT spam_reason FROM cleaned_comments ORDER BY comment_id")]
    assert all(r.startswith("copypasta") for r in reasons[:5])
    assert reasons[5] is None
