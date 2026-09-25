"""Lapisan collection (FR-002).

Setiap sumber data adalah adapter yang mengimplementasikan
:class:`~ngulik.collectors.base.Collector` dan menghasilkan
:class:`~ngulik.models.RawComment` dengan bentuk yang sama. Batas inilah yang
membuat penambahan sumber baru tidak merembet ke NLP pipeline (NFR-004).
"""

from ngulik.collectors.base import (
    Collector,
    CollectorError,
    CollectorNotConfigured,
    QuotaExceeded,
    run_collection,
)
from ngulik.collectors.file_import import FileCollector
from ngulik.collectors.registry import available, describe, get_collector
from ngulik.collectors.youtube import YouTubeCollector, parse_video_id

__all__ = [
    "Collector",
    "CollectorError",
    "CollectorNotConfigured",
    "FileCollector",
    "QuotaExceeded",
    "YouTubeCollector",
    "available",
    "describe",
    "get_collector",
    "parse_video_id",
    "run_collection",
]
