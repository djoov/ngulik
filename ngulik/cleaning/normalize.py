"""Normalisasi teks (FR-004).

Mengimplementasikan langkah-langkah awal dari diagram pipeline PRD bagian 4::

    Raw Text -> Unicode -> Lowercase -> URL -> Mention -> Whitespace -> Slang

Setiap langkah bisa dimatikan lewat ``config/config.yaml`` (NFR-006).

Fungsi di sini murni: ia menerima string dan mengembalikan string, tidak
menyentuh database. Teks asli tetap utuh di tabel ``comments`` — cleaning
tidak pernah merusak raw dataset (FR-004, NFR-002).
"""

from __future__ import annotations

import re
import unicodedata

# --- Pola ------------------------------------------------------------------

URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@[\w.\-]+")
HASHTAG_PATTERN = re.compile(r"#(\w+)", re.UNICODE)
WHITESPACE_PATTERN = re.compile(r"\s+")
# Karakter berulang tiga kali atau lebih: "bagusssss", "wkwkwkwk", "aaaaaa".
REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{2,}", re.DOTALL)
# Nomor telepon Indonesia: 08xx / +628xx / 628xx, dengan pemisah opsional.
PHONE_PATTERN = re.compile(r"(?:\+?62|0)8[\d\s.\-]{7,13}\d")
# Simbol yang tidak membawa makna kata; dibuang saat tokenisasi.
NON_WORD_PATTERN = re.compile(r"[^\w\s'-]", re.UNICODE)
DIGIT_ONLY_PATTERN = re.compile(r"^\d+$")


def normalize_unicode(text: str, form: str = "NFKC") -> str:
    """Satukan bentuk Unicode yang setara.

    NFKC menyatukan varian lebar-penuh dan huruf bergaya (mis. teks berhias
    "𝓫𝓪𝓰𝓾𝓼" menjadi "bagus"), yang sering dipakai di komentar media sosial
    dan kalau dibiarkan akan terhitung sebagai term yang berbeda.
    """
    return unicodedata.normalize(form, text)


def strip_control_chars(text: str) -> str:
    """Buang karakter kontrol, pertahankan tab dan newline."""
    return "".join(
        char
        for char in text
        if char in "\t\n\r" or unicodedata.category(char)[0] != "C"
    )


def replace_urls(text: str, placeholder: str = "") -> str:
    """Ganti URL. Placeholder kosong berarti dihapus."""
    return URL_PATTERN.sub(placeholder, text)


def replace_mentions(text: str, placeholder: str = "") -> str:
    """Ganti mention ``@user``.

    Default-nya dibuang: username adalah data identitas yang tidak dibutuhkan
    analisis pola bahasa (PRD bagian 16).
    """
    return MENTION_PATTERN.sub(placeholder, text)


def handle_hashtags(text: str, keep_text: bool = True) -> str:
    """Perlakuan hashtag.

    ``keep_text=True`` mengubah ``#gabut`` menjadi ``gabut`` sehingga isinya
    tetap ikut dianalisis; ``False`` membuang hashtag sepenuhnya.
    """
    return HASHTAG_PATTERN.sub(r"\1" if keep_text else "", text)


def collapse_repeated_chars(text: str, max_run: int = 2) -> str:
    """Batasi karakter berulang, mis. ``"bagusssss"`` -> ``"baguss"``.

    Menyatukan variasi penekanan yang sebetulnya satu kata yang sama, tanpa
    menghapusnya — nilai ``max_run=2`` menjaga bentuk yang masih wajar dalam
    Bahasa Indonesia.
    """
    if max_run < 1:
        return text
    return REPEATED_CHAR_PATTERN.sub(lambda m: m.group(1) * max_run, text)


def normalize_whitespace(text: str) -> str:
    """Rapatkan semua spasi beruntun menjadi satu, lalu trim."""
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def normalize_text(text: str, config: dict | None = None) -> str:
    """Jalankan seluruh rantai normalisasi sesuai konfigurasi.

    Mengembalikan teks bersih yang masih enak dibaca manusia (untuk kolom
    ``cleaned_comments.text_clean``). Pemecahan menjadi token dikerjakan
    terpisah oleh :mod:`ngulik.cleaning.tokenize`.
    """
    settings = config or {}
    if not text:
        return ""

    result = normalize_unicode(text, settings.get("unicode_form", "NFKC"))
    result = strip_control_chars(result)

    if settings.get("lowercase", True):
        result = result.lower()

    result = replace_urls(result, settings.get("url_placeholder", ""))
    result = replace_mentions(result, settings.get("mention_placeholder", ""))
    result = handle_hashtags(result, settings.get("keep_hashtag_text", True))
    result = collapse_repeated_chars(result, int(settings.get("max_repeated_chars", 2)))
    return normalize_whitespace(result)


# ---------------------------------------------------------------------------
# Statistik teks — dipakai oleh spam filter
# ---------------------------------------------------------------------------


def count_urls(text: str) -> int:
    return len(URL_PATTERN.findall(text))


def count_mentions(text: str) -> int:
    return len(MENTION_PATTERN.findall(text))


def count_hashtags(text: str) -> int:
    return len(HASHTAG_PATTERN.findall(text))


def has_phone_number(text: str) -> bool:
    """Deteksi pola nomor telepon/WhatsApp Indonesia.

    Sangat umum pada spam promosi di kolom komentar YouTube berbahasa
    Indonesia ("wa 0812...").
    """
    return bool(PHONE_PATTERN.search(text))


def longest_char_run(text: str) -> int:
    """Panjang deret karakter identik terpanjang.

    Dihitung pada teks MENTAH, sebelum :func:`collapse_repeated_chars`, agar
    ``"aaaaaaaaaaaaaaa"`` masih bisa dikenali sebagai spam.
    """
    if not text:
        return 0
    longest = run = 1
    for previous, current in zip(text, text[1:], strict=False):
        run = run + 1 if current == previous else 1
        longest = max(longest, run)
    return longest
