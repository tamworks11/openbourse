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


def test_universe_sync_command_is_registered() -> None:
    result = runner.invoke(app, ["universe", "sync", "--help"])
    assert result.exit_code == 0
    # The default sources are listed in the --source help text.
    assert "sp500" in result.stdout
    assert "nasdaq100" in result.stdout


def test_universe_sync_rejects_unknown_source() -> None:
    # Validation happens before any network call, so this is a pure unit test.
    result = runner.invoke(app, ["universe", "sync", "--source", "not_a_real_index"])
    assert result.exit_code != 0
    assert "unknown source" in result.output.lower()


def test_run_command_exposes_sync_flag() -> None:
    """`bourse run` must expose a ``--sync`` option.

    Introspects the command callback rather than scraping ``--help``
    output: the rendered help is Rich-formatted and its exact bytes vary
    with terminal width, ANSI support, and Rich version, which made the
    substring check flaky on CI. The OptionInfo on the callback is the
    source of truth — if it carries ``--sync``, Typer exposes the flag.
    """
    import inspect

    from openbourse.cli import run

    sync_param = inspect.signature(run).parameters.get("sync")
    assert sync_param is not None, "run() has no 'sync' parameter"
    option = sync_param.default
    assert "--sync" in getattr(option, "param_decls", ())


def test_alembic_config_resolves_ini_and_url(monkeypatch) -> None:
    from pathlib import Path

    monkeypatch.setenv("OPENBOURSE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    from openbourse import config

    config.reset_settings_cache()
    from openbourse.cli import _alembic_config

    cfg = _alembic_config()
    # script_location is rewritten to an absolute path so migrations resolve
    # regardless of the working directory (e.g. inside the scheduler container).
    script_location = cfg.get_main_option("script_location")
    assert script_location is not None
    assert Path(script_location).is_absolute()
    assert Path(script_location).name == "alembic"
    assert cfg.get_main_option("sqlalchemy.url") == "sqlite+aiosqlite:///:memory:"
