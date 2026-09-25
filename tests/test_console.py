"""Test konsol msfconsole-style lewat NgulikConsole.execute(), tanpa input interaktif."""

from __future__ import annotations

import re

import click
import pytest

from ngulik.cli import cli
from ngulik.config import Config
from ngulik.console import MODULES, NgulikConsole
from tests.conftest import insert_comments


@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("NGULIK_DATABASE", str(tmp_path / "console.db"))
    ctx = click.Context(cli, obj=Config.load())
    return NgulikConsole(ctx)


def test_use_by_index_loads_config_defaults(console):
    index = next(i for i, m in enumerate(MODULES) if m.path == "lexicon/kbbj")
    console.execute(f"use {index}")

    assert console.module.path == "lexicon/kbbj"
    assert console.values["LIMIT"] == str(console.config.get("lexicon.max_entries_per_run"))
    assert console.values["REFRESH"] == "false"


def test_set_validates_and_is_case_insensitive(console, capsys):
    console.execute("use lexicon/kbbj")
    console.execute("set limit abc")
    console.execute("set limit 7")

    assert console.values["LIMIT"] == "7"
    assert "expected a whole number" in capsys.readouterr().err


def test_modules_of_future_phases_refuse_to_run(console, capsys):
    from ngulik.console import Module

    console._modules["future/thing"] = Module("future/thing", "Not built yet", None,
                                              phase="phase 9")
    console.execute("use future/thing")
    console.execute("run")

    assert "not available yet" in capsys.readouterr().err


def test_analysis_and_discovery_modules_are_ready():
    ready = {m.path for m in MODULES if m.ready}
    assert {"analysis/all", "analysis/tfidf", "discovery/candidates"} <= ready


def test_run_module_invokes_pipeline(console, capsys):
    from ngulik.db import Database

    with Database(console.config) as db:
        db.initialize()
        insert_comments(db, ["Penjelasan di video ini jelas dan runtut sekali"])

    console.execute("use cleaning/pipeline")
    console.execute("run")

    out = capsys.readouterr().out
    assert "Processed:" in out
    assert "Module cleaning/pipeline completed" in out


def test_pipeline_commands_pass_through_and_errors_are_reported(console, capsys):
    console.execute("keyword add satu dua")
    console.execute("keyword list")
    console.execute("nonsense")

    captured = capsys.readouterr()
    assert "satu" in captured.out and "dua" in captured.out
    assert "Unknown command: nonsense" in captured.err


def test_exit_stops_the_loop(console):
    console.execute("exit")
    assert console.running is False


def test_browse_commands_show_matches_and_details(console, capsys):
    from ngulik.db import Database

    with Database(console.config) as db:
        db.initialize()
        insert_comments(db, ["ayo rek nonton bareng", "komentar lain tanpa kata itu"])

    console.execute("keyword add rek")
    console.execute("keyword match")
    console.execute("comments list --matched")
    console.execute("comments show 1")
    console.execute("videos list")

    out = capsys.readouterr().out
    assert "1 of 2 comments contain known keywords" in out
    assert "Comments (1 shown, 2 stored)" in out
    assert re.search(r"Known keywords:\s+rek", out)
    assert "no videos yet" in out


def test_keyword_export_round_trips(console, tmp_path, capsys):
    target = tmp_path / "out.yaml"
    console.execute("keyword add gabut 'gabut parah' #mager")
    console.execute(f"keyword export --file {target.as_posix()}")

    text = target.read_text(encoding="utf-8")
    assert "gabut parah" in text and "'#mager'" in text
    assert "Keyword export" in capsys.readouterr().out
