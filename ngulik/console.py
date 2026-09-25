"""Konsol interaktif bergaya msfconsole: ``python -m ngulik`` tanpa argumen.

Dua cara menjalankan sesuatu dari prompt ``ngulik >``:

1. **Modul**, meniru alur Metasploit::

       ngulik > use lexicon/kbbj
       ngulik lexicon(kbbj) > set LIMIT 20
       ngulik lexicon(kbbj) > run

   Setiap modul adalah pembungkus tipis di atas satu perintah click di
   :mod:`ngulik.cli`; opsinya dipetakan ke parameter perintah itu. Modul untuk
   fase yang belum selesai tetap terdaftar dengan tanda fase, dan menolak
   dijalankan, sehingga menambah fase baru cukup dengan mengisi
   ``command`` pada entri :data:`MODULES` yang sudah ada.

2. **Perintah pipeline langsung**, persis seperti di shell biasa::

       ngulik > status
       ngulik > review --list

   Baris diteruskan ke grup click ``cli``, jadi semua perintah dan opsinya
   otomatis tersedia di konsol tanpa kode tambahan.

Tab completion aktif bila modul ``readline`` tersedia (Linux/macOS). Di
Windows konsol tetap jalan, hanya tanpa completion.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from ngulik import __version__, report, ui
from ngulik.collectors import available as collector_names
from ngulik.db import Database
from ngulik.lexicon import available as lexicon_names
from ngulik.models import SourceMethod

__all__ = ["MODULES", "NgulikConsole", "Module", "Option"]

_ANSI = re.compile(r"(\x1b\[[0-9;]*m)")

try:  # pragma: no cover - bergantung platform
    import readline
except ImportError:  # Windows tanpa pyreadline3
    readline = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Definisi modul
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Option:
    """Satu opsi modul, dipetakan ke parameter perintah click."""

    name: str
    param: str
    description: str
    default: Any = None
    required: bool = False
    kind: str = "str"  # str | int | bool | path | choice | list
    choices: tuple[str, ...] = ()
    #: Kunci config untuk nilai default, dibaca saat modul dipilih.
    config_default: str | None = None

    def convert(self, raw: str | None) -> Any:
        if raw is None or raw == "":
            return None
        match self.kind:
            case "int":
                try:
                    return int(raw)
                except ValueError:
                    raise ValueError(f"expected a whole number, got {raw!r}") from None
            case "bool":
                value = str(raw).strip().lower()
                if value in {"true", "yes", "y", "1", "on"}:
                    return True
                if value in {"false", "no", "n", "0", "off"}:
                    return False
                raise ValueError(f"expected true/false, got {raw!r}")
            case "path":
                return Path(raw)
            case "list":
                # Dipisah koma atau spasi: "URL1, URL2" dan "URL1 URL2" sama saja.
                return tuple(part for part in re.split(r"[,\s]+", str(raw)) if part)
            case "choice":
                value = str(raw).strip().lower()
                if value not in self.choices:
                    raise ValueError(f"expected one of {', '.join(self.choices)}")
                return value
        return raw


@dataclass(slots=True)
class Module:
    """Satu modul konsol. ``command`` adalah nama atribut di :mod:`ngulik.cli`."""

    path: str
    description: str
    command: str | None
    options: list[Option] = field(default_factory=list)
    fixed: dict[str, Any] = field(default_factory=dict)
    phase: str | None = None

    @property
    def ready(self) -> bool:
        return self.command is not None and self.phase is None


_LIMIT = "Maximum items to process"
_ITER = "Iteration number (empty = current)"
_SHOW = Option("SHOW", "show", "Rows to show per table", 15, True, "int")

MODULES: list[Module] = [
    Module("collector/file", "Import comments from a local JSON/JSONL/CSV file", "collect",
           [Option("PATH", "file_path", "File to import", "data/fixtures/sample_comments.json",
                   True, "path"),
            Option("LIMIT", "limit", _LIMIT, None, True, "int",
                   config_default="collection.default_limit"),
            Option("ITERATION", "iteration", _ITER, None, False, "int")],
           fixed={"source": "file"}),
    Module("collector/youtube", "Collect public YouTube comments for the active keywords",
           "collect",
           [Option("LIMIT", "limit", _LIMIT, None, True, "int",
                   config_default="collection.default_limit"),
            Option("ITERATION", "iteration", _ITER, None, False, "int")],
           fixed={"source": "youtube", "file_path": None, "videos": (), "pages": None}),
    Module("collector/youtube-video",
           "Collect comments from specific YouTube videos (no search quota used)", "collect",
           [Option("VIDEOS", "videos", "Video URLs or IDs, comma or space separated",
                   None, True, "list"),
            Option("PAGES", "pages", "Comment pages per video (100 comments each)", None,
                   True, "int", config_default="collection.youtube.max_comment_pages_per_selected_video"),
            Option("LIMIT", "limit", _LIMIT, None, True, "int",
                   config_default="collection.default_limit"),
            Option("ITERATION", "iteration", _ITER, None, False, "int")],
           fixed={"source": "youtube", "file_path": None}),
    Module("cleaning/pipeline", "Normalize, tokenize, filter spam and detect duplicates", "clean",
           [Option("REPROCESS", "reprocess", "Rebuild everything from raw comments", False,
                   True, "bool")]),
    Module("lexicon/kbbj", "Fetch slang from kbbj.web.id as review candidates",
           "lexicon_fetch",
           [Option("LIMIT", "limit", "Maximum entries to download", None, True, "int",
                   config_default="lexicon.max_entries_per_run"),
            Option("REFRESH", "refresh", "Re-download entries that are still fresh", False,
                   True, "bool")],
           fixed={"source_name": "kbbj"}),
    Module("discovery/review", "Approve or reject keyword candidates interactively", "review",
           [Option("METHOD", "method", "Only candidates from this method", None, False,
                   "choice", tuple(m.value.lower() for m in SourceMethod)),
            Option("LIMIT", "limit", "Maximum candidates to show", None, False, "int"),
            Option("LIST", "list_only", "Only list, do not review", False, True, "bool")],
           fixed={"approve": (), "reject": ()}),
    Module("discovery/iterate", "Promote approved candidates to seed keywords", "iterate"),
    Module("analysis/all", "Run every analysis on the cleaned comments", "analyze",
           [_SHOW], fixed={"method": "all"}),
    Module("analysis/frequency", "Top terms by frequency (AC-006)", "analyze",
           [_SHOW], fixed={"method": "frequency"}),
    Module("analysis/ngram", "Bigrams and trigrams (AC-007)", "analyze",
           [_SHOW], fixed={"method": "ngram"}),
    Module("analysis/tfidf", "TF-IDF over cleaned comments (AC-008)", "analyze",
           [_SHOW], fixed={"method": "tfidf"}),
    Module("analysis/cooccurrence", "Co-occurrence with PMI (AC-009)", "analyze",
           [_SHOW], fixed={"method": "cooccurrence"}),
    Module("discovery/candidates", "Score and propose new keywords from the corpus", "discover",
           [Option("MAX", "max_candidates", "How many candidates to propose", None, True, "int",
                   config_default="discovery.max_candidates"),
            Option("DRY_RUN", "dry_run", "Only show the ranking, save nothing", False,
                   True, "bool")]),
]

#: Perintah click yang boleh dipanggil langsung dari prompt.
PIPELINE_COMMANDS = {
    "init": "Create the database and data folder",
    "status": "Database summary and latest collection runs",
    "keyword": "Manage seed keywords (import, list, add, remove, match)",
    "collect": "Collect comments from a source",
    "clean": "Clean collected comments",
    "analyze": "Frequency, n-grams, TF-IDF and co-occurrence of the corpus",
    "discover": "Propose new keyword candidates from the corpus",
    "comments": "Browse collected comments (list, show)",
    "videos": "Browse YouTube videos comments came from",
    "lexicon": "Fetch slang terms from online dictionaries",
    "review": "Approve or reject candidates",
    "iterate": "Promote approved candidates",
}

CORE_COMMANDS = {
    "?": "Help menu",
    "help": "Help menu",
    "banner": "Display an awesome Ngulik banner",
    "clear": "Clear the screen",
    "history": "Show command history",
    "version": "Show the framework version",
    "exit": "Exit the console",
    "quit": "Exit the console",
}

MODULE_COMMANDS = {
    "use": "Select a module by name",
    "back": "Move back from the current module",
    "info": "Display information about the current module",
    "show": "Show modules or the current module's options",
    "search": "Search modules by name or description",
    "set": "Set an option of the current module",
    "unset": "Clear an option of the current module",
    "run": "Run the current module",
    "exploit": "Alias for run",
}


# ---------------------------------------------------------------------------
# Konsol
# ---------------------------------------------------------------------------


class NgulikConsole:
    """REPL bergaya msfconsole di atas grup click ``cli``."""

    def __init__(self, ctx: click.Context) -> None:
        self.ctx = ctx.find_root()
        self.config = self.ctx.obj
        self.module: Module | None = None
        self.values: dict[str, str] = {}
        self.history: list[str] = []
        self.history_size = int(self.config.get("ui.history_size", 200))
        self.running = True
        self._modules = {m.path: m for m in MODULES}
        self._setup_readline()

    # -- siklus -------------------------------------------------------------

    def loop(self) -> None:
        self.boot()
        while self.running:
            try:
                line = input(self.prompt())
            except KeyboardInterrupt:
                click.echo()
                ui.warn("Interrupt: use the 'exit' command to quit")
                continue
            except EOFError:
                click.echo()
                break
            self.execute(line)

    def boot(self) -> None:
        with ui.spinner("Starting the Ngulik console..."):
            if ui.Theme.effects:
                time.sleep(ui.Theme.boot_delay)
            stats = self._stats()
        ui.banner()
        ready = sum(m.ready for m in MODULES)
        ui.stats_panel(f"ngulik v{__version__}", [
            f"{ready} modules ready - {len(MODULES) - ready} coming - "
            f"{len(collector_names())} collectors - {len(lexicon_names())} lexicon source",
            f"{stats['comments']} comments - {stats['keywords']} active keywords - "
            f"{stats['candidates_pending']} candidates pending",
            f"iteration {stats['iteration']} - {stats['usable']} comments usable for analysis",
        ])
        ui.tip()

    def prompt(self) -> str:
        name = ui.style("ngulik", underline=True)
        if self.module:
            category, _, leaf = self.module.path.partition("/")
            name += f" {category}({ui.style(leaf, fg='red', bold=True)})"
        text = f"{name} > "
        if readline is not None and ui.Theme.color:
            # Penanda \001..\002 supaya readline tidak salah menghitung
            # panjang prompt yang berisi kode warna.
            text = _ANSI.sub("\001\\1\002", text)
        return text

    # -- dispatch -----------------------------------------------------------

    def execute(self, line: str) -> None:
        line = line.strip()
        if not line or line.startswith("#"):
            return
        self._remember(line)
        try:
            argv = _split(line)
        except ValueError as exc:
            ui.error(f"Parse error: {exc}")
            return
        command, args = argv[0].lower(), argv[1:]

        handler = getattr(self, f"cmd_{command}", None)
        try:
            if command in {"?", "help"}:
                self.cmd_help(args)
            elif handler is not None and command in CORE_COMMANDS | MODULE_COMMANDS:
                handler(args)
            elif command in PIPELINE_COMMANDS:
                self._run_click(command, args)
            else:
                ui.error(f"Unknown command: {command}. Type 'help' for a list of commands.")
        except KeyboardInterrupt:
            click.echo()
            ui.warn("Interrupted")

    def _run_click(self, name: str, args: list[str]) -> None:
        cli_group = self.ctx.command
        command = cli_group.get_command(self.ctx, name)  # type: ignore[attr-defined]
        try:
            with command.make_context(name, args, parent=self.ctx) as sub:
                command.invoke(sub)
        except click.exceptions.Exit:
            pass
        except click.ClickException as exc:
            # Grup tanpa subperintah (mis. "keyword") melempar NoArgsIsHelpError
            # yang isinya teks bantuan, bukan pesan error.
            if type(exc).__name__ == "NoArgsIsHelpError":
                click.echo(exc.format_message())
            else:
                ui.error(exc.format_message())
        except click.Abort:
            click.echo()
            ui.warn("Aborted")

    # -- perintah inti ------------------------------------------------------

    def cmd_help(self, args: list[str]) -> None:
        for title, commands in (("Core Commands", CORE_COMMANDS),
                                ("Module Commands", MODULE_COMMANDS),
                                ("Pipeline Commands", PIPELINE_COMMANDS)):
            click.echo()
            click.echo(report.table(["Command", "Description"], list(commands.items()),
                                    title=title))
        click.echo()
        ui.info("Pipeline commands accept the same options as 'ngulik <command> --help'.")
        click.echo()

    def cmd_banner(self, args: list[str]) -> None:
        ui.banner()

    def cmd_clear(self, args: list[str]) -> None:
        click.clear()

    def cmd_history(self, args: list[str]) -> None:
        for index, entry in enumerate(self.history, start=1):
            click.echo(f"{index:>5}  {entry}")

    def cmd_version(self, args: list[str]) -> None:
        ui.info(f"Framework: {__version__}")
        ui.info(f"Console  : {__version__}")

    def cmd_exit(self, args: list[str]) -> None:
        self.running = False

    cmd_quit = cmd_exit

    # -- perintah modul -----------------------------------------------------

    def cmd_use(self, args: list[str]) -> None:
        if not args:
            ui.error("Usage: use <module>. Type 'show modules' to list them.")
            return
        name = args[0].strip().lower()
        module = self._modules.get(name) or self._resolve_index(name)
        if module is None:
            ui.error(f"No module named {name!r}. Try 'search {name}'.")
            return
        if not module.ready:
            ui.warn(f"{module.path} is coming in {module.phase}; it cannot run yet.")
        self.module = module
        self.values = {opt.name: self._default(opt) for opt in module.options}
        if module.options:
            ui.info("Using configured defaults. Type 'show options' to review them.")

    def cmd_back(self, args: list[str]) -> None:
        self.module = None
        self.values = {}

    def cmd_show(self, args: list[str]) -> None:
        what = (args[0].lower() if args else "")
        if what in {"modules", "all"}:
            self._show_modules(MODULES)
        elif what == "options":
            self._show_options()
        else:
            ui.error("Usage: show <modules|options>")

    def cmd_search(self, args: list[str]) -> None:
        if not args:
            ui.error("Usage: search <keyword>")
            return
        needle = " ".join(args).lower()
        found = [m for m in MODULES if needle in m.path or needle in m.description.lower()]
        if not found:
            ui.warn(f"No results for {needle!r}")
            return
        self._show_modules(found, title="Matching Modules")

    def cmd_info(self, args: list[str]) -> None:
        module = self._modules.get(args[0].lower()) if args else self.module
        if module is None:
            ui.error("No module selected. Usage: info [module]")
            return
        click.echo()
        click.echo(report.key_values({
            "Name": module.path,
            "Status": "ready" if module.ready else f"coming in {module.phase}",
            "Runs": f"ngulik {module.command.replace('_', ' ')}" if module.command else "-",
            "Description": module.description,
        }))
        if module is self.module:
            click.echo()
            self._show_options()
        click.echo()

    def cmd_set(self, args: list[str]) -> None:
        if self.module is None:
            ui.error("No module selected. Use 'use <module>' first.")
            return
        if len(args) < 2:
            ui.error("Usage: set <OPTION> <value>")
            return
        option = self._option(args[0])
        if option is None:
            return
        value = " ".join(args[1:])
        try:
            option.convert(value)
        except ValueError as exc:
            ui.error(f"Invalid value for {option.name}: {exc}")
            return
        self.values[option.name] = value
        click.echo(f"{option.name} => {value}")

    def cmd_unset(self, args: list[str]) -> None:
        if self.module is None or not args:
            ui.error("Usage: unset <OPTION> (with a module selected)")
            return
        option = self._option(args[0])
        if option is not None:
            self.values[option.name] = ""
            click.echo(f"Unsetting {option.name}...")

    def cmd_run(self, args: list[str]) -> None:
        module = self.module
        if module is None:
            ui.error("No module selected. Use 'use <module>' first.")
            return
        if not module.ready:
            ui.error(f"{module.path} is not available yet ({module.phase}).")
            return

        params = dict(module.fixed)
        for option in module.options:
            raw = self.values.get(option.name, "")
            if option.required and raw in ("", None):
                ui.error(f"Missing required option: {option.name}")
                return
            try:
                params[option.param] = option.convert(raw)
            except ValueError as exc:
                ui.error(f"Invalid value for {option.name}: {exc}")
                return
        if params.get("file_path") is not None:
            params["file_path"] = self.config.resolve(params["file_path"])

        from ngulik import cli as cli_module

        command = getattr(cli_module, module.command)
        ui.info(f"Running module {ui.style(module.path, bold=True)}...")
        click.echo()
        try:
            self.ctx.invoke(command, **params)
        except click.ClickException as exc:
            ui.error(exc.format_message())
            return
        except click.Abort:
            click.echo()
            ui.warn("Aborted")
            return
        click.echo()
        ui.good(f"Module {module.path} completed")

    cmd_exploit = cmd_run

    # -- bantuan ------------------------------------------------------------

    def _show_modules(self, modules: list[Module], title: str = "Modules") -> None:
        rows = [
            (index, m.path, "ready" if m.ready else m.phase, m.description)
            for index, m in enumerate(modules)
        ]
        click.echo()
        click.echo(report.table(["#", "Name", "Status", "Description"], rows, title=title))
        click.echo()
        ui.info("Interact with a module by name or index, e.g. 'use lexicon/kbbj' or 'use 0'")
        click.echo()

    def _show_options(self) -> None:
        if self.module is None:
            ui.error("No module selected.")
            return
        rows = [
            (opt.name, self.values.get(opt.name, ""), "yes" if opt.required else "no",
             opt.description + (f" ({', '.join(opt.choices)})" if opt.choices else ""))
            for opt in self.module.options
        ]
        click.echo()
        click.echo(report.table(
            ["Name", "Current Setting", "Required", "Description"], rows,
            title=f"Module options ({self.module.path})",
            empty_message="This module has no options.",
        ))
        click.echo()

    def _option(self, name: str) -> Option | None:
        assert self.module is not None
        for option in self.module.options:
            if option.name.lower() == name.lower():
                return option
        ui.error(f"Unknown option {name.upper()} for {self.module.path}")
        return None

    def _default(self, option: Option) -> str:
        value = option.default
        if option.config_default:
            value = self.config.get(option.config_default, value)
        if value is None:
            return ""
        return str(value).lower() if isinstance(value, bool) else str(value)

    def _resolve_index(self, name: str) -> Module | None:
        return MODULES[int(name)] if name.isdigit() and int(name) < len(MODULES) else None

    def _stats(self) -> dict[str, int]:
        with Database(self.config) as db:
            db.initialize()
            return db.stats()

    def _remember(self, line: str) -> None:
        self.history.append(line)
        del self.history[:-self.history_size]

    # -- readline -----------------------------------------------------------

    def _setup_readline(self) -> None:  # pragma: no cover - interaktif
        if readline is None:
            return
        readline.set_completer(self._complete)
        readline.set_completer_delims(" \t")
        readline.parse_and_bind("tab: complete")

    def _complete(self, text: str, state: int) -> str | None:  # pragma: no cover
        buffer = readline.get_line_buffer().lstrip()
        words = buffer.split()
        if len(words) <= 1 and not buffer.endswith(" "):
            pool = [*CORE_COMMANDS, *MODULE_COMMANDS, *PIPELINE_COMMANDS]
        elif words[0] in {"use", "info"}:
            pool = [m.path for m in MODULES]
        elif words[0] == "show":
            pool = ["modules", "options"]
        elif words[0] in {"set", "unset"} and self.module:
            pool = [o.name for o in self.module.options]
        else:
            pool = []
        matches = [item + " " for item in pool if item.startswith(text)]
        return matches[state] if state < len(matches) else None


def _split(line: str) -> list[str]:
    """Pecah baris seperti shell, tanpa memakan backslash di path Windows."""
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    # Default shlex menganggap '#' awal komentar, sehingga hashtag seperti
    # "#mager" hilang diam-diam. Baris yang diawali '#' sudah disaring di execute().
    lexer.commenters = ""
    return list(lexer)
