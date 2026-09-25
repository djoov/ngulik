"""Konfigurasi terpusat (NFR-006).

Seluruh parameter pipeline dibaca dari ``config/config.yaml`` dan digabung di
atas :data:`DEFAULTS`. Artinya file YAML boleh memuat sebagian kunci saja, atau
bahkan hilang sama sekali — sistem tetap jalan dengan nilai bawaan.

Secret (API key) dibaca dari ``.env`` / environment, tidak pernah dari YAML,
supaya file konfigurasi aman di-commit.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Lokasi project
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).resolve().parent


def _detect_project_root() -> Path:
    """Tentukan root project (folder yang memuat ``config/``).

    Urutan prioritas: env ``NGULIK_HOME`` -> induk package -> cwd. Urutan ini
    membuat ``python -m ngulik`` dari folder project dan ``pip install -e .``
    sama-sama bekerja.
    """
    env_home = os.environ.get("NGULIK_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    candidate = _PACKAGE_DIR.parent
    if (candidate / "config").is_dir():
        return candidate

    cwd = Path.cwd().resolve()
    if (cwd / "config").is_dir():
        return cwd

    # Belum ada folder config (mis. sebelum `ngulik init`). Pakai induk package.
    return candidate


PROJECT_ROOT = _detect_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
KEYWORDS_FILE = CONFIG_DIR / "keywords.yaml"
ENV_FILE = PROJECT_ROOT / ".env"

# ---------------------------------------------------------------------------
# Nilai bawaan — mencerminkan config/config.yaml
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "project": {
        "name": "Ngulik",
        "database": "data/ngulik.db",
    },
    "collection": {
        "default_limit": 500,
        "default_source": "file",
        "youtube": {
            "daily_search_quota": 100,
            "max_comment_pages_per_selected_video": 10,
            "max_search_calls_per_run": 10,
            "max_videos_per_keyword": 25,
            "max_comment_pages_per_video": 2,
            "comments_per_page": 100,
            "order": "relevance",
            "region_code": "ID",
            "relevance_language": "id",
            "published_after": None,
            "use_search_terms": False,
            "include_replies": True,
            "request_timeout": 30,
            "retry_attempts": 3,
            "retry_backoff": 2.0,
        },
        "privacy": {
            "store_author_id": False,
        },
    },
    "cleaning": {
        "unicode_form": "NFKC",
        "lowercase": True,
        "url_placeholder": "",
        "mention_placeholder": "",
        "keep_hashtag_text": True,
        "normalize_slang": True,
        "slang_file": "config/slang_id.csv",
        "stopword_file": "config/stopwords_id.txt",
        "use_sastrawi_stopwords": True,
        "max_repeated_chars": 2,
        "min_token_length": 2,
        "filter_stopwords": True,
        "use_stemming": False,
        "batch_size": 500,
    },
    "dedup": {
        "enabled": True,
        "near_duplicate": True,
        "simhash_bits": 64,
        "shingle_size": 3,
        "hamming_threshold": 3,
        "bands": 4,
    },
    "spam": {
        "enabled": True,
        "max_urls": 2,
        "max_mentions": 5,
        "max_hashtags": 5,
        "min_tokens_after_clean": 2,
        "min_token_diversity": 0.35,
        "max_char_run": 10,
        "detect_phone_numbers": True,
        "copypasta_min_authors": 5,
    },
    "analysis": {
        "top_n": 100,
        "ngram": {"sizes": [1, 2, 3], "min_frequency": 3},
        "tfidf": {"sublinear_tf": True, "smooth_idf": True},
        "cooccurrence": {"window": 5, "min_pair_frequency": 3, "metric": "pmi"},
    },
    "discovery": {
        "min_doc_frequency": 3,
        "min_term_length": 3,
        "max_candidates": 50,
        "weights": {
            "frequency": 0.25,
            "tfidf": 0.35,
            "cooccurrence": 0.30,
            "ngram": 0.10,
        },
        "ngram_bonus": 1.0,
        "respect_previous_rejections": True,
    },
    "lexicon": {
        "user_agent": "Ngulik/0.1 (riset keyword lokal; non-komersial)",
        "request_delay": 2.0,
        "request_timeout": 30,
        "retry_attempts": 3,
        "retry_backoff": 2.0,
        "respect_robots_txt": True,
        "refetch_after_days": 30,
        "max_entries_per_run": 200,
        "exclude_categories": ["Nama Orang"],
        "sources": {
            "kbbj": {
                "enabled": True,
                "base_url": "https://kbbj.web.id",
                "sitemap": "https://kbbj.web.id/sitemap-words.xml",
            },
        },
    },
    "ui": {
        "color": True,
        "effects": True,
        "line_delay": 0.02,
        "boot_delay": 0.6,
        "tips": True,
        "history_size": 200,
    },
    "logging": {
        "level": "INFO",
        "file": "data/ngulik.log",
    },
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Gabungkan ``override`` di atas ``base`` secara rekursif.

    ``base`` tidak dimutasi. Nilai ``None`` di override tetap dihormati (mis.
    ``published_after: null`` memang berarti "tidak dibatasi").
    """
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Baca file ``.env`` sederhana ke ``os.environ``.

    Ditulis manual (bukan python-dotenv) supaya project tidak menambah
    dependency hanya untuk sepuluh baris parsing. Variabel yang sudah ada di
    environment TIDAK ditimpa — environment asli selalu menang.
    """
    env_path = path or ENV_FILE
    loaded: dict[str, str] = {}
    if not env_path.is_file():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


class Config:
    """Konfigurasi pipeline dengan akses bertitik.

    Contoh::

        cfg = Config.load()
        cfg.get("discovery.weights.tfidf")   # -> 0.35
        cfg.path("project.database")         # -> Path absolut
    """

    def __init__(self, data: dict[str, Any], root: Path | None = None) -> None:
        self.data = data
        self.root = root or PROJECT_ROOT

    # -- konstruksi ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None, *, root: Path | None = None) -> "Config":
        """Muat konfigurasi dari YAML, digabung di atas :data:`DEFAULTS`."""
        load_dotenv()
        config_path = path or CONFIG_FILE
        data = DEFAULTS

        if config_path.is_file():
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(
                    f"{config_path} must be a YAML mapping, "
                    f"not {type(raw).__name__}"
                )
            data = _deep_merge(DEFAULTS, raw)

        cfg = cls(data, root=root)
        cfg._apply_env_overrides()
        return cfg

    def _apply_env_overrides(self) -> None:
        """Terapkan override dari environment untuk beberapa kunci praktis."""
        if db := os.environ.get("NGULIK_DATABASE"):
            self.data["project"]["database"] = db
        if level := os.environ.get("NGULIK_LOG_LEVEL"):
            self.data["logging"]["level"] = level

    # -- akses --------------------------------------------------------------

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Ambil nilai lewat jalur bertitik, mis. ``"analysis.ngram.sizes"``."""
        node: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, dotted_key: str) -> dict[str, Any]:
        """Seperti :meth:`get` tetapi selalu mengembalikan dict."""
        value = self.get(dotted_key)
        return value if isinstance(value, dict) else {}

    def path(self, dotted_key: str, default: str | None = None) -> Path:
        """Resolusi nilai konfigurasi menjadi path absolut relatif ke root."""
        value = self.get(dotted_key, default)
        if value is None:
            raise KeyError(f"Config key '{dotted_key}' not found")
        candidate = Path(str(value)).expanduser()
        return candidate if candidate.is_absolute() else (self.root / candidate)

    def resolve(self, value: str | Path) -> Path:
        """Jadikan path apa pun absolut relatif ke root project."""
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else (self.root / candidate)

    # -- turunan ------------------------------------------------------------

    @property
    def database_path(self) -> Path:
        return self.path("project.database", "data/ngulik.db")

    @property
    def youtube_api_key(self) -> str | None:
        """API key YouTube dari environment. Tidak pernah dari YAML."""
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        return key or None

    def __repr__(self) -> str:  # pragma: no cover - diagnostik
        return f"Config(root={self.root}, database={self.database_path})"


# ---------------------------------------------------------------------------
# Logging (NFR-005)
# ---------------------------------------------------------------------------


def setup_logging(config: Config, *, verbose: bool = False) -> logging.Logger:
    """Konfigurasi logging ke konsol dan berkas.

    Konsol dibuat ringkas karena CLI sudah mencetak tabelnya sendiri; berkas
    log memuat timestamp lengkap untuk audit jalannya pipeline.
    """
    level_name = "DEBUG" if verbose else str(config.get("logging.level", "INFO"))
    level = getattr(logging, level_name.upper(), logging.INFO)

    logger = logging.getLogger("ngulik")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler()
    console.setLevel(level)
    from ngulik.ui import ConsoleFormatter

    console.setFormatter(ConsoleFormatter("%(message)s"))
    logger.addHandler(console)

    log_file = config.path("logging.file", "data/ngulik.log")
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - mis. disk read-only
        logger.warning("Cannot write log to %s: %s", log_file, exc)

    return logger


def get_logger(name: str = "ngulik") -> logging.Logger:
    """Ambil logger anak di bawah namespace ``ngulik``."""
    return logging.getLogger(name if name.startswith("ngulik") else f"ngulik.{name}")
