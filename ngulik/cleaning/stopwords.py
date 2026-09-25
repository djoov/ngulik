"""Daftar stopword Bahasa Indonesia (FR-004).

Sumbernya digabung dari dua tempat: berkas ``config/stopwords_id.txt`` yang
selalu ada, dan daftar Sastrawi bila paket itu terpasang. Sastrawi bersifat
opsional secara sengaja — pipeline tidak boleh gagal hanya karena sebuah
dependency tambahan tidak ada (NFR-001).

Catatan penting soal stemming: Sastrawi juga menyediakan stemmer, tetapi
``cleaning.use_stemming`` default-nya **mati**. Stemming mengolapskan variasi
kata menjadi bentuk dasar, padahal variasi slang itulah yang justru ingin
ditemukan sistem ini. Menyalakannya akan melawan tujuan PRD bagian 1.2.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ngulik.config import get_logger

logger = get_logger("cleaning.stopwords")


def load_stopword_file(path: Path) -> set[str]:
    """Baca berkas stopword: satu kata per baris, ``#`` sebagai komentar."""
    if not path.is_file():
        logger.warning("Stopword file not found: %s", path)
        return set()

    words: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().lower()
        if line and not line.startswith("#"):
            words.add(line)
    return words


def load_sastrawi_stopwords() -> set[str]:
    """Ambil daftar stopword Sastrawi bila terpasang; set kosong bila tidak."""
    try:
        from Sastrawi.StopWordRemover.StopWordRemoverFactory import (  # type: ignore
            StopWordRemoverFactory,
        )
    except ImportError:
        logger.debug("Sastrawi not installed, using the built-in stopword list only")
        return set()

    try:
        return {word.lower() for word in StopWordRemoverFactory().get_stop_words()}
    except Exception as exc:  # noqa: BLE001 - paket pihak ketiga, jangan sampai fatal
        logger.warning("Failed to read Sastrawi stopwords: %s", exc)
        return set()


@lru_cache(maxsize=8)
def _cached_stopwords(path_str: str, use_sastrawi: bool) -> frozenset[str]:
    words = load_stopword_file(Path(path_str))
    source = f"{len(words)} from file"

    if use_sastrawi:
        sastrawi_words = load_sastrawi_stopwords()
        if sastrawi_words:
            before = len(words)
            words |= sastrawi_words
            source += f" + {len(words) - before} extra from Sastrawi"

    logger.info("Stopwords loaded: %d words (%s)", len(words), source)
    return frozenset(words)


def get_stopwords(path: Path, *, use_sastrawi: bool = True) -> frozenset[str]:
    """Kumpulan stopword gabungan, di-cache per kombinasi argumen."""
    return _cached_stopwords(str(path), use_sastrawi)


def clear_cache() -> None:
    """Kosongkan cache — dipakai di test dan setelah berkas stopword diubah."""
    _cached_stopwords.cache_clear()


# ---------------------------------------------------------------------------
# Stemmer opsional
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_stemmer():
    """Stemmer Sastrawi, atau ``None`` bila tidak tersedia.

    Dibungkus ``lru_cache`` karena ``StemmerFactory`` memuat kamus kata dasar
    yang relatif besar dan tidak murah untuk dibuat berulang kali.
    """
    try:
        from Sastrawi.Stemmer.StemmerFactory import StemmerFactory  # type: ignore
    except ImportError:
        logger.warning(
            "cleaning.use_stemming is on but Sastrawi is not installed. "
            "Stemming skipped. Install it with: pip install Sastrawi"
        )
        return None

    try:
        return StemmerFactory().create_stemmer()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to create the Sastrawi stemmer: %s", exc)
        return None
