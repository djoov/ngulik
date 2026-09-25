"""Lapisan tampilan terminal bergaya msfconsole.

Berisi: prefix status berwarna (``[*]``, ``[+]``, ``[-]``, ``[!]``), banner
ASCII acak, panel statistik, spinner, efek baris-demi-baris, dan formatter
logging yang memakai prefix yang sama.

Semua efek otomatis mati bila output bukan terminal interaktif (di-pipe ke
berkas, dijalankan dari test) atau bila ``ui.effects: false``. Warna mati bila
``ui.color: false`` atau environment ``NO_COLOR`` diisi. Dengan begitu output
tetap bersih untuk skrip, dan efek tidak pernah memperlambat pipeline.

Tanpa dependency tambahan: warna lewat ``click.style``, yang sudah menjadi
dependency, dan colorama yang ikut terpasang bersama click di Windows.
"""

from __future__ import annotations

import itertools
import logging
import os
import random
import re
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import click

__all__ = [
    "BANNERS",
    "ConsoleFormatter",
    "Theme",
    "banner",
    "configure",
    "error",
    "good",
    "info",
    "print_lines",
    "spinner",
    "stats_panel",
    "style",
    "tip",
    "warn",
]


class Theme:
    """Pengaturan tampilan global, diisi sekali oleh :func:`configure`."""

    color: bool = True
    effects: bool = True
    line_delay: float = 0.02
    boot_delay: float = 0.6
    tips: bool = True


def _stream_is_terminal(stream: Any) -> bool:
    """Apakah ``stream`` benar-benar konsol.

    Di Windows ``isatty()`` juga bernilai True untuk ``NUL`` (``/dev/null``),
    jadi dipastikan lagi lewat ``GetConsoleMode``.
    """
    try:
        if not stream.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        return False


def _is_tty() -> bool:
    """Warna dan efek hanya bila stdout DAN stderr (tujuan log) adalah konsol."""
    return _stream_is_terminal(sys.stdout) and _stream_is_terminal(sys.stderr)


def configure(config: Any) -> None:
    """Baca section ``ui`` dari config dan sesuaikan dengan kemampuan terminal."""
    settings = config.section("ui") if config is not None else {}
    tty = _is_tty()
    Theme.color = bool(settings.get("color", True)) and tty and not os.environ.get("NO_COLOR")
    Theme.effects = bool(settings.get("effects", True)) and tty
    Theme.line_delay = float(settings.get("line_delay", 0.02))
    Theme.boot_delay = float(settings.get("boot_delay", 0.6))
    Theme.tips = bool(settings.get("tips", True))
    if Theme.color and os.name == "nt":
        _enable_windows_ansi()


def _enable_windows_ansi() -> None:
    """Nyalakan mode VT di konsol Windows supaya kode warna ANSI dirender."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
    except Exception:  # noqa: BLE001 - kosmetik, jangan pernah fatal
        pass


# ---------------------------------------------------------------------------
# Warna dan prefix status
# ---------------------------------------------------------------------------


def style(text: str, **kwargs: Any) -> str:
    """``click.style`` yang menghormati :attr:`Theme.color`."""
    return click.style(text, **kwargs) if Theme.color else text


_PREFIX = {
    "info": ("[*]", "blue"),
    "good": ("[+]", "green"),
    "error": ("[-]", "red"),
    "warn": ("[!]", "yellow"),
}


def _status(kind: str, message: str, *, err: bool = False) -> None:
    symbol, color = _PREFIX[kind]
    click.echo(f"{style(symbol, fg=color, bold=True)} {message}", err=err)


def info(message: str) -> None:
    _status("info", message)


def good(message: str) -> None:
    _status("good", message)


def warn(message: str) -> None:
    _status("warn", message)


def error(message: str) -> None:
    _status("error", message, err=True)


class ConsoleFormatter(logging.Formatter):
    """Formatter log konsol dengan prefix gaya msfconsole."""

    _LEVELS = {
        logging.DEBUG: ("[.]", "bright_black"),
        logging.INFO: ("[*]", "blue"),
        logging.WARNING: ("[!]", "yellow"),
        logging.ERROR: ("[-]", "red"),
        logging.CRITICAL: ("[-]", "red"),
    }

    def format(self, record: logging.LogRecord) -> str:
        symbol, color = self._LEVELS.get(record.levelno, ("[*]", "blue"))
        message = super().format(record)
        return f"{style(symbol, fg=color, bold=True)} {message}"


# ---------------------------------------------------------------------------
# Efek
# ---------------------------------------------------------------------------


def print_lines(lines: list[str], *, delay: float | None = None) -> None:
    """Cetak baris demi baris seperti output terminal yang sedang mengalir."""
    pause = Theme.line_delay if delay is None else delay
    for line in lines:
        click.echo(line)
        if Theme.effects and pause > 0:
            time.sleep(pause)


@contextmanager
def spinner(message: str) -> Iterator[None]:
    """Spinner ``|/-\\`` selama blok berjalan, lalu tanda selesai.

    Tanpa efek, cukup mencetak pesan ``[*]`` sekali.
    """
    if not Theme.effects:
        info(message)
        yield
        return

    stop = threading.Event()

    def spin() -> None:
        for frame in itertools.cycle("|/-\\"):
            if stop.is_set():
                break
            sys.stdout.write(f"\r{style('[' + frame + ']', fg='blue', bold=True)} {message}")
            sys.stdout.flush()
            time.sleep(0.08)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        sys.stdout.write(f"\r{style('[+]', fg='green', bold=True)} {message}\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

# Glyph "ANSI Shadow", disusun per huruf supaya lebar kolomnya selalu cocok.
_GLYPHS = {
    "K": ["██╗  ██╗", "██║ ██╔╝", "█████╔╝ ", "██╔═██╗ ", "██║  ██╗", "╚═╝  ╚═╝"],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "G": [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "U": ["██╗   ██╗", "██║   ██║", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
}


def _block_banner() -> list[str]:
    rows = ["".join(_GLYPHS[ch][i] for ch in "NGULIK") for i in range(6)]
    palette = ["bright_red", "red", "bright_magenta", "magenta", "bright_blue", "blue"]
    lines = [""] + [style("   " + row, fg=color, bold=True) for row, color in zip(rows, palette)]
    lines.append(style("      iterative slang & keyword discovery :: local-first",
                       fg="bright_white"))
    return lines + [""]


_BOX = re.compile(r"(\[ [A-Z]+ \])")


def _colorize_loop(line: str) -> str:
    """Kotak tahap berwarna hijau, panah dan garis redup."""
    return "".join(
        style(part, fg="green", bold=True) if _BOX.fullmatch(part)
        else style(part, fg="bright_black")
        for part in _BOX.split(line) if part
    )


def _loop_banner() -> list[str]:
    top = "   [ SEED ] -> [ COLLECT ] -> [ CLEAN ] -> [ ANALYZE ]"
    left = "   [ EXPAND ] <- [ REVIEW ] <"
    last = "[ DISCOVER ]"
    seed_at = top.index("[ SEED ]") + 4
    analyze_at = top.index("[ ANALYZE ]") + 5
    gap = analyze_at - seed_at - 1
    bottom = left + "-" * (analyze_at - len(last) // 2 - len(left) - 1) + " " + last
    prompt = style("ngulik@localhost", fg="green", bold=True) + ":" + style("~", fg="blue", bold=True)
    return [
        "",
        f"  {prompt}$ ./discover --iterate --local-only",
        "",
        _colorize_loop(top),
        style(" " * seed_at + "^" + " " * gap + "|", fg="bright_black"),
        style(" " * seed_at + "|" + " " * gap + "v", fg="bright_black"),
        _colorize_loop(bottom),
        "",
    ]


def _frame_banner() -> list[str]:
    width = 67
    rows = [
        ("NGULIK", {"fg": "bright_white", "bold": True}),
        ("iterative keyword discovery :: bahasa indonesia :: local-first",
         {"fg": "bright_black"}),
        ("", {}),
        ("> no surveillance   > no profiling   > human-reviewed keywords",
         {"fg": "green"}),
    ]
    edge = lambda text: style(text, fg="cyan")  # noqa: E731
    lines = ["", edge("   ." + "-" * width + ".")]
    for text, fmt in rows:
        padded = ("   " + text).ljust(width)
        lines.append(edge("   |") + (style(padded, **fmt) if fmt else padded) + edge("|"))
    lines += [edge("   '" + "-" * width + "'"), ""]
    return lines


BANNERS = [_block_banner, _loop_banner, _frame_banner]


def banner(index: int | None = None) -> None:
    """Cetak satu banner, acak seperti msfconsole bila ``index`` kosong."""
    make = BANNERS[index % len(BANNERS)] if index is not None else random.choice(BANNERS)
    print_lines(make())


def stats_panel(version: str, lines: list[str]) -> None:
    """Panel ``=[ ... ]`` khas msfconsole."""
    width = max(len(line) for line in [version, *lines]) + 2
    head = f"       =[ {style(version, fg='bright_white', bold=True)}{' ' * (width - len(version))}]"
    body = [
        f"{style('+ -- --=[', fg='bright_black')} {line}{' ' * (width - len(line))}"
        f"{style(']', fg='bright_black')}"
        for line in lines
    ]
    print_lines([head, *body, ""])


_TIPS = [
    "Use {show modules} to see everything this console can run.",
    "Type {use lexicon/kbbj} then {run} to pull slang terms from an online dictionary.",
    "Rejected candidates are never proposed again. Review with care.",
    "{clean --reprocess} rebuilds cleaned data from the untouched raw comments.",
    "Every command from {ngulik --help} also works inside this console.",
    "{status} shows how much of today's YouTube search quota is left.",
    "Press Ctrl+C to interrupt, type {exit} to leave.",
]


def tip() -> None:
    if not Theme.tips:
        return
    text = random.choice(_TIPS)
    for part in ("show modules", "use lexicon/kbbj", "run", "clean --reprocess",
                 "ngulik --help", "status", "exit"):
        text = text.replace("{" + part + "}", style(part, fg="yellow"))
    click.echo(f"{style('Ngulik tip:', fg='bright_white', bold=True)} {text}\n")
