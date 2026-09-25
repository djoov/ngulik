"""Deteksi duplikat (FR-005) — AC-005.

Dua tingkat, sesuai PRD bagian 5:

**Exact duplicate.** SHA-1 atas teks yang sudah dinormalisasi. Karena
normalisasi sudah menyamakan kapitalisasi, spasi, dan karakter berulang, dua
komentar yang hanya beda kosmetik sudah tertangkap di tahap ini.

**Near duplicate.** SimHash 64-bit atas shingle token, dibandingkan dengan
jarak Hamming. Contoh persis dari PRD::

    "ini lucu banget"
    "ini lucu banget wkwk"

Pencocokan naif berarti membandingkan setiap komentar dengan semua komentar
lain — O(n^2), tidak terpakai pada puluhan ribu baris. Modul ini memakai
*banding*: 64 bit dibagi menjadi 4 pita 16-bit, dan hanya komentar yang
berbagi setidaknya satu pita identik yang dibandingkan. Ini bukan heuristik
yang mengorbankan ketepatan — menurut prinsip pigeonhole, dua nilai dengan
jarak Hamming <= 3 yang dibagi ke 4 pita PASTI punya minimal satu pita yang
sama persis, jadi tidak ada pasangan sah yang terlewat.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence

DEFAULT_BITS = 64
DEFAULT_SHINGLE = 3
DEFAULT_THRESHOLD = 3
DEFAULT_BANDS = 4


# ---------------------------------------------------------------------------
# Exact duplicate
# ---------------------------------------------------------------------------


def text_hash(text: str) -> str:
    """Hash stabil untuk pencocokan exact duplicate."""
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# SimHash
# ---------------------------------------------------------------------------


def _stable_hash(value: str, bits: int) -> int:
    """Hash 64-bit yang stabil lintas proses.

    ``hash()` bawaan Python tidak bisa dipakai: nilainya di-randomisasi per
    proses (PYTHONHASHSEED), sehingga simhash yang tersimpan di database tidak
    akan cocok lagi saat dijalankan ulang — melanggar NFR-002.
    """
    digest = hashlib.blake2b(
        value.encode("utf-8"), digest_size=max(1, bits // 8)
    ).digest()
    return int.from_bytes(digest, "big")


def shingles(tokens: Sequence[str], size: int = DEFAULT_SHINGLE) -> list[str]:
    """Bentuk shingle token yang saling tumpang tindih.

    Shingle (bukan token tunggal) membuat SimHash peka terhadap URUTAN kata,
    sehingga "anjing gigit orang" dan "orang gigit anjing" tidak dianggap
    kembar.
    """
    if not tokens:
        return []
    if len(tokens) < size:
        return [" ".join(tokens)]
    return [" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)]


def simhash(
    tokens: Sequence[str], bits: int = DEFAULT_BITS, shingle_size: int = DEFAULT_SHINGLE
) -> int:
    """Hitung SimHash dari daftar token.

    Fitur yang muncul berulang otomatis punya bobot lebih besar karena tiap
    kemunculan menambah vektornya sekali lagi.
    """
    parts = shingles(tokens, shingle_size)
    if not parts:
        return 0

    vector = [0] * bits
    for part in parts:
        value = _stable_hash(part, bits)
        for index in range(bits):
            vector[index] += 1 if (value >> index) & 1 else -1

    result = 0
    for index in range(bits):
        if vector[index] > 0:
            result |= 1 << index
    return result


def hamming_distance(left: int, right: int) -> int:
    """Jumlah bit yang berbeda antara dua nilai."""
    return (left ^ right).bit_count()


def is_near_duplicate(
    left: int, right: int, threshold: int = DEFAULT_THRESHOLD
) -> bool:
    return hamming_distance(left, right) <= threshold


# ---------------------------------------------------------------------------
# Indeks
# ---------------------------------------------------------------------------


class NearDuplicateIndex:
    """Indeks SimHash dengan banding untuk pencarian mendekati-linear.

    Pemakaian::

        index = NearDuplicateIndex()
        for comment_id, tokens in corpus:
            value = simhash(tokens)
            if (original := index.find(value)) is not None:
                mark_duplicate(comment_id, original)
            else:
                index.add(comment_id, value)
    """

    def __init__(
        self,
        *,
        bits: int = DEFAULT_BITS,
        bands: int = DEFAULT_BANDS,
        threshold: int = DEFAULT_THRESHOLD,
    ) -> None:
        if bands < 1:
            raise ValueError("bands must be at least 1")
        if threshold >= bands:
            # Pigeonhole hanya berlaku bila jumlah pita melebihi ambang bit.
            raise ValueError(
                f"hamming_threshold ({threshold}) must be smaller than "
                f"bands ({bands}), otherwise some near-duplicates will be missed"
            )
        self.bits = bits
        self.bands = bands
        self.threshold = threshold
        self.band_width = bits // bands
        self._buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        self._values: dict[int, int] = {}

    def _band_keys(self, value: int) -> list[tuple[int, int]]:
        mask = (1 << self.band_width) - 1
        return [
            (band, (value >> (band * self.band_width)) & mask)
            for band in range(self.bands)
        ]

    def add(self, key: int, value: int) -> None:
        """Daftarkan sebuah dokumen ke indeks."""
        self._values[key] = value
        for band_key in self._band_keys(value):
            self._buckets[band_key].append(key)

    def find(self, value: int) -> int | None:
        """Cari dokumen pertama yang mirip. ``None`` bila tidak ada.

        Hanya kandidat yang berbagi minimal satu pita yang diperiksa; sisanya
        tidak mungkin berada dalam jarak ambang.
        """
        seen: set[int] = set()
        for band_key in self._band_keys(value):
            for key in self._buckets.get(band_key, ()):
                if key in seen:
                    continue
                seen.add(key)
                if hamming_distance(self._values[key], value) <= self.threshold:
                    return key
        return None

    def __len__(self) -> int:
        return len(self._values)


# ---------------------------------------------------------------------------
# Pembungkus siap pakai
# ---------------------------------------------------------------------------


class DuplicateDetector:
    """Gabungan deteksi exact dan near duplicate, terkonfigurasi sekali.

    Baris pertama yang muncul dianggap sebagai yang asli; kemunculan
    berikutnya ditandai duplikat dan menyimpan rujukan ``duplicate_of``
    sehingga keputusannya bisa diaudit.
    """

    def __init__(self, config) -> None:
        settings = config.section("dedup")
        self.enabled = bool(settings.get("enabled", True))
        self.near_enabled = bool(settings.get("near_duplicate", True))
        self.bits = int(settings.get("simhash_bits", DEFAULT_BITS))
        self.shingle_size = int(settings.get("shingle_size", DEFAULT_SHINGLE))

        threshold = int(settings.get("hamming_threshold", DEFAULT_THRESHOLD))
        bands = int(settings.get("bands", DEFAULT_BANDS))
        if threshold >= bands:
            bands = threshold + 1
        self.threshold = threshold
        self.bands = bands

        self._exact: dict[str, int] = {}
        self._index = NearDuplicateIndex(
            bits=self.bits, bands=self.bands, threshold=self.threshold
        )

    def check(
        self, key: int, text_clean: str, tokens: Sequence[str]
    ) -> tuple[bool, int | None, str, str]:
        """Periksa satu komentar.

        Mengembalikan ``(is_duplicate, duplicate_of, norm_hash, simhash_hex)``.
        Nilai hash tetap dikembalikan meski deteksi dimatikan, supaya kolomnya
        terisi dan bisa dipakai menjalankan deteksi belakangan tanpa
        menghitung ulang.
        """
        norm_hash = text_hash(text_clean)
        simhash_value = (
            simhash(tokens, self.bits, self.shingle_size)
            if self.near_enabled and tokens
            else 0
        )
        simhash_hex = format(simhash_value, "016x")

        if not self.enabled:
            return False, None, norm_hash, simhash_hex

        if (original := self._exact.get(norm_hash)) is not None:
            return True, original, norm_hash, simhash_hex
        self._exact[norm_hash] = key

        if self.near_enabled and tokens:
            if (original := self._index.find(simhash_value)) is not None:
                return True, original, norm_hash, simhash_hex
            self._index.add(key, simhash_value)

        return False, None, norm_hash, simhash_hex

    def register(self, key: int, norm_hash: str, simhash_hex: str | None) -> None:
        """Daftarkan komentar yang sudah diproses di run sebelumnya.

        Dipakai saat cleaning berjalan inkremental: tanpa ini, komentar baru
        tidak akan dikenali sebagai duplikat dari komentar lama karena state
        detektor hanya hidup di memori.
        """
        self._exact.setdefault(norm_hash, key)
        if self.near_enabled and simhash_hex:
            value = int(simhash_hex, 16)
            # Nilai 0 berarti komentar tanpa token; check() juga tidak
            # memasukkannya ke indeks.
            if value:
                self._index.add(key, value)

    def reset(self) -> None:
        """Kosongkan state — dipanggil sebelum ``clean --reprocess``."""
        self._exact.clear()
        self._index = NearDuplicateIndex(
            bits=self.bits, bands=self.bands, threshold=self.threshold
        )
