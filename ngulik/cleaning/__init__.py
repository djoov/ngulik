"""Lapisan cleaning (FR-004, FR-005).

Mengubah ``comments`` mentah menjadi ``cleaned_comments`` siap analisis:
normalisasi, tokenisasi, penyaringan spam, dan deteksi duplikat. Teks asli
tidak pernah disentuh (FR-003).
"""

from ngulik.cleaning.dedup import DuplicateDetector
from ngulik.cleaning.normalize import normalize_text
from ngulik.cleaning.pipeline import CleaningPipeline, CleaningStats
from ngulik.cleaning.spam import SpamFilter, mark_copypasta
from ngulik.cleaning.stopwords import get_stopwords
from ngulik.cleaning.tokenize import Tokenizer

__all__ = [
    "CleaningPipeline",
    "CleaningStats",
    "DuplicateDetector",
    "SpamFilter",
    "Tokenizer",
    "get_stopwords",
    "mark_copypasta",
    "normalize_text",
]
