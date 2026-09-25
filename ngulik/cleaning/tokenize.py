"""Tokenisasi, normalisasi slang, dan penyaringan stopword (FR-004).

Melanjutkan rantai dari :mod:`ngulik.cleaning.normalize`::

    Slang Normalization -> Tokenization -> Stopword Filtering -> Clean Text

Satu keputusan yang layak disorot: kata berulang (reduplikasi) dengan tanda
hubung dipertahankan sebagai **satu** token. ``"kata-kata"``, ``"tiba-tiba"``,
dan ``"buru-buru"`` adalah satu kata utuh dalam Bahasa Indonesia; memecahnya
akan melahirkan unigram palsu dan mengacaukan hitungan frekuensi.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from ngulik.config import get_logger

logger = get_logger("cleaning.tokenize")

#: Satu token = rangkaian karakter kata, boleh disambung "-" atau "'".
#: Pola inilah yang menjaga "kata-kata" tetap utuh.
TOKEN_PATTERN = re.compile(r"\w+(?:[-']\w+)*", re.UNICODE)


# ---------------------------------------------------------------------------
# Kamus slang
# ---------------------------------------------------------------------------


def load_slang_dict(path: Path) -> dict[str, str]:
    """Muat pemetaan slang dari CSV dua kolom (``slang,normal``).

    Baris berawalan ``#`` dan baris header dilewati.
    """
    if not path.is_file():
        logger.warning("Slang file not found: %s", path)
        return {}

    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 2:
                continue
            slang, normal = row[0].strip().lower(), row[1].strip().lower()
            if not slang or not normal or slang.startswith("#") or slang == "slang":
                continue
            mapping[slang] = normal

    logger.info("Slang dictionary loaded: %d mappings from %s", len(mapping), path.name)
    return mapping


@lru_cache(maxsize=8)
def _cached_slang(path_str: str) -> tuple[tuple[str, str], ...]:
    return tuple(load_slang_dict(Path(path_str)).items())


def get_slang_dict(path: Path) -> dict[str, str]:
    """Kamus slang yang di-cache per path."""
    return dict(_cached_slang(str(path)))


def clear_cache() -> None:
    """Kosongkan cache kamus slang — dipakai di test."""
    _cached_slang.cache_clear()


# ---------------------------------------------------------------------------
# Operasi token
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Pecah teks menjadi token kata."""
    return TOKEN_PATTERN.findall(text) if text else []


def apply_slang(tokens: list[str], mapping: dict[str, str]) -> list[str]:
    """Ganti token slang dengan bentuk bakunya.

    Pemetaan dilakukan per token, bukan per substring, sehingga ``"ke"`` di
    dalam ``"kereta"`` tidak ikut berubah. Bentuk baku yang terdiri dari
    beberapa kata (``"gpp" -> "tidak apa-apa"``) dipecah kembali menjadi
    beberapa token.
    """
    if not mapping:
        return tokens

    result: list[str] = []
    for token in tokens:
        replacement = mapping.get(token)
        if replacement is None:
            result.append(token)
        elif " " in replacement:
            result.extend(replacement.split())
        else:
            result.append(replacement)
    return result


def filter_tokens(
    tokens: list[str],
    stopwords: frozenset[str] | set[str],
    *,
    min_length: int = 2,
    drop_numeric: bool = True,
) -> list[str]:
    """Buang stopword, token terlalu pendek, dan token berupa angka murni."""
    result: list[str] = []
    for token in tokens:
        if len(token) < min_length:
            continue
        if drop_numeric and token.isdigit():
            continue
        if token in stopwords:
            continue
        result.append(token)
    return result


def apply_stemming(tokens: list[str]) -> list[str]:
    """Stem token memakai Sastrawi. Dikembalikan apa adanya bila tak tersedia.

    Jarang dipakai: ``cleaning.use_stemming`` default-nya mati karena stemming
    justru mengolapskan variasi slang yang ingin ditemukan sistem ini.
    """
    from ngulik.cleaning.stopwords import get_stemmer

    stemmer = get_stemmer()
    if stemmer is None:
        return tokens
    return [stemmer.stem(token) or token for token in tokens]


# ---------------------------------------------------------------------------
# Tokenizer terkonfigurasi
# ---------------------------------------------------------------------------


class Tokenizer:
    """Tokenizer siap pakai yang membaca konfigurasi sekali di awal.

    Dipakai bersama oleh cleaning maupun analisis, sehingga korpus yang
    dianalisis dijamin ditokenisasi dengan aturan yang persis sama.
    """

    def __init__(self, config) -> None:
        cleaning = config.section("cleaning")
        self.min_length = int(cleaning.get("min_token_length", 2))
        self.filter_stopwords = bool(cleaning.get("filter_stopwords", True))
        self.normalize_slang = bool(cleaning.get("normalize_slang", True))
        self.use_stemming = bool(cleaning.get("use_stemming", False))

        from ngulik.cleaning.stopwords import get_stopwords

        self.stopwords = (
            get_stopwords(
                config.resolve(cleaning.get("stopword_file", "config/stopwords_id.txt")),
                use_sastrawi=bool(cleaning.get("use_sastrawi_stopwords", True)),
            )
            if self.filter_stopwords
            else frozenset()
        )
        self.slang = (
            get_slang_dict(
                config.resolve(cleaning.get("slang_file", "config/slang_id.csv"))
            )
            if self.normalize_slang
            else {}
        )

    def __call__(self, text: str) -> list[str]:
        """Ubah teks yang sudah dinormalisasi menjadi token siap analisis."""
        tokens = tokenize(text)
        if self.normalize_slang:
            tokens = apply_slang(tokens, self.slang)
        if self.use_stemming:
            tokens = apply_stemming(tokens)
        return filter_tokens(tokens, self.stopwords, min_length=self.min_length)

    def raw_tokens(self, text: str) -> list[str]:
        """Token tanpa penyaringan — dipakai spam filter untuk menghitung rasio."""
        return tokenize(text)
