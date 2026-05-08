"""Tests for the Typer CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from openbourse import __version__
from openbourse.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_screen_list_lists_builtin_screens() -> None:
    result = runner.invoke(app, ["screen", "list"])
    assert result.exit_code == 0
    assert "quality_compounders" in result.stdout
    assert "deep_value" in result.stdout


def test_screen_run_unknown_screen_errors() -> None:
    result = runner.invoke(app, ["screen", "run", "no_such_screen"])
    assert result.exit_code != 0


def test_screen_run_outputs_table_by_default(monkeypatch) -> None:
    # The CLI falls back to the bundled fixture when the DB is unreachable;
    # point it at a non-existent DB so we exercise that path.
    monkeypatch.setenv("OPENBOURSE_DATABASE_URL", "sqlite+aiosqlite:////dev/null/missing")
    from openbourse import config

    config.reset_settings_cache()
    result = runner.invoke(app, ["screen", "run", "quality_compounders"])
    assert result.exit_code == 0
    assert "CDNS" in result.stdout


def test_screen_run_json_output(monkeypatch) -> None:
    monkeypatch.setenv("OPENBOURSE_DATABASE_URL", "sqlite+aiosqlite:////dev/null/missing")
    from openbourse import config

    config.reset_settings_cache()
    result = runner.invoke(app, ["screen", "run", "quality_compounders", "--output", "json"])
    assert result.exit_code == 0
    assert '"candidates"' in result.stdout


def test_lookup_known_ticker_prints_table() -> None:
    result = runner.invoke(app, ["lookup", "CDNS"])
    assert result.exit_code == 0
    assert "CDNS" in result.stdout
    assert "Score" in result.stdout
    assert "Verdict" in result.stdout


def test_lookup_unknown_ticker_exits_nonzero() -> None:
    result = runner.invoke(app, ["lookup", "ZZZZ"])
    assert result.exit_code == 1
    assert "unknown ticker" in result.stdout.lower()


def test_lookup_with_brief_includes_summary() -> None:
    result = runner.invoke(app, ["lookup", "CDNS", "--brief"])
    assert result.exit_code == 0
    assert "Summary" in result.stdout


def test_lookup_json_output_is_machine_readable() -> None:
    import json

    result = runner.invoke(app, ["lookup", "CDNS", "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["instrument"]["ticker"] == "CDNS"
    assert "score" in payload
    assert "verdict" in payload
