"""Presentasi hasil: tabel teks, ringkasan, dan ekspor berkas.

Sengaja tanpa dependency (tanpa `rich`, tanpa `tabulate`) agar output pipeline
tetap bisa dibaca di terminal mana pun, termasuk saat di-pipe ke berkas.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Indentasi tabel, meniru ``show options`` di msfconsole.
_INDENT = "   "
_GAP = "  "


def _display_width(value: str) -> int:
    """Lebar tampilan sebuah string.

    Aproksimasi sederhana: hitung karakter. Cukup untuk teks Latin dan emoji
    BMP yang umum muncul di komentar Bahasa Indonesia.
    """
    return len(value)


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if _display_width(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def format_number(value: Any) -> str:
    """Angka dengan pemisah ribuan; float dibulatkan empat desimal."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:.4f}"
    return "" if value is None else str(value)


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    title: str | None = None,
    max_width: int | None = None,
    empty_message: str = "(no data)",
) -> str:
    """Render tabel teks bergaya msfconsole: header digaris bawahi ``----``.

    Kolom melar mengikuti isi, lalu kolom terlebar dipangkas bila total
    lebarnya melebihi lebar terminal.
    """
    lines: list[str] = []
    if title:
        lines.extend([title, "=" * _display_width(title), ""])

    if not rows:
        lines.append(_INDENT + empty_message)
        return "\n".join(lines)

    text_rows = [[format_number(cell) for cell in row] for row in rows]
    header_texts = [str(h) for h in headers]

    widths = [_display_width(h) for h in header_texts]
    for row in text_rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], _display_width(cell))

    limit = (max_width or shutil.get_terminal_size((100, 24)).columns) - len(_INDENT)
    total = sum(widths) + len(_GAP) * (len(widths) - 1)
    if total > limit and widths:
        widest = max(range(len(widths)), key=lambda i: widths[i])
        widths[widest] = max(8, widths[widest] - (total - limit))

    def render(cells: Sequence[str]) -> str:
        parts = [
            _truncate(cell, widths[i]).ljust(widths[i])
            for i, cell in enumerate(cells)
            if i < len(widths)
        ]
        return (_INDENT + _GAP.join(parts)).rstrip()

    lines.append(render(header_texts))
    lines.append(render(["-" * min(_display_width(h), widths[i])
                         for i, h in enumerate(header_texts)]))
    lines.extend(render(row) for row in text_rows)
    return "\n".join(lines)


def key_values(data: dict[str, Any], *, title: str | None = None) -> str:
    """Render pasangan label/nilai sejajar, bergaya ``info`` di msfconsole."""
    lines: list[str] = []
    if title:
        lines.extend([title, "=" * _display_width(title), ""])
    if not data:
        lines.append(_INDENT + "(empty)")
        return "\n".join(lines)

    width = max(_display_width(str(k)) for k in data)
    for key, value in data.items():
        lines.append(f"{_INDENT}{(str(key) + ':').ljust(width + 1)}  {format_number(value)}")
    return "\n".join(lines)


def bar(value: float, maximum: float, width: int = 24) -> str:
    """Bar horizontal untuk memvisualkan frekuensi relatif."""
    if maximum <= 0:
        return ""
    filled = int(round((value / maximum) * width))
    return "█" * max(0, min(width, filled))


def section(title: str) -> str:
    """Judul bagian yang menonjol di antara keluaran panjang."""
    return f"\n{title}\n{'=' * _display_width(title)}\n"


# ---------------------------------------------------------------------------
# Ekspor
# ---------------------------------------------------------------------------


def export_csv(path: Path, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> Path:
    """Tulis CSV UTF-8 dengan BOM agar langsung rapi dibuka di Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def export_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def rows_to_dicts(
    headers: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    return [dict(zip(headers, row, strict=False)) for row in rows]
