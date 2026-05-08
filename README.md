# openbourse

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A terminal-first equity research workstation. `openbourse` screens public
companies against quantitative criteria, scores them with a transparent
composite formula, and surfaces AI-generated briefs — all from a Textual TUI
backed by PostgreSQL.

> **Status:** early scaffold. Provider integrations (FMP, EDGAR, Anthropic
> Claude) ship as stubs returning fixture data so contributors can run the
> full app without API keys.

```text
BOURSE v0.1.0                ● FMP stub  ● EDGAR stub  ● Claude stub
screen://quality_compounders                                  UTC

[SCREEN] Quality Compounders — rev growth ≥15%, gross margin ≥40%,
         net debt/EBITDA ≤1.0, mkt cap ≥$1B
Universe: 3,247 US-listed · Filtered: 47 candidates · Analyzed: 12

 #  TICKER  NAME                    MKT CAP   REV GR   GM    FCF YLD  SCORE  VERDICT
 01 CDNS    Cadence Design Systems  $78.2B   +18.4%   89.1%  2.8%      94    STRONG_INTEREST
 02 VEEV    Veeva Systems           $32.8B   +16.1%   74.2%  3.4%      91    STRONG_INTEREST
 ...

 ↓ navigate   ↵ view brief   f filter   s sort   e export   w watchlist   ? help
```

## Highlights

- **Textual TUI** — keyboard-driven research over a live PostgreSQL dataset.
- **Pluggable providers** — `FmpProvider`, `EdgarProvider`, `ClaudeProvider`
  share a small async interface; swap stubs for real clients via env vars.
- **Transparent scoring** — composite score and verdict thresholds are pure
  functions in `openbourse.screening.scoring`, fully unit-tested.
- **SQLAlchemy 2.0 async + Alembic** — typed `Mapped[]` models, versioned
  migrations, repository-pattern data access.
- **Apache 2.0 licensed** — designed to be forked, vendored, and extended.

## Quick start

### Prerequisites

- Python 3.11 or newer
- [Poetry](https://python-poetry.org/) 2.0+
- PostgreSQL 14+ (or run the bundled `docker compose` service)

### Install

```bash
git clone https://github.com/your-org/openbourse.git
cd openbourse
poetry install
cp .env.example .env
```

### Database

Start a local Postgres with the bundled compose file, then run migrations and
load a small seed dataset:

```bash
docker compose up -d postgres
poetry run bourse db migrate
poetry run bourse db seed
```

### Launch the TUI

```bash
poetry run bourse run
```

Press `?` inside the app for keybindings.

## CLI

```text
bourse run                Launch the TUI.
bourse db migrate         Apply Alembic migrations to the configured DB.
bourse db seed            Load the bundled fixture dataset.
bourse screen list        Show available screens (text mode, no TUI).
bourse screen run NAME    Run a screen and print results as JSON.
bourse version            Print version and exit.
```

All commands respect the `OPENBOURSE_*` environment variables in `.env`.

## Project layout

```
src/openbourse/
  cli.py            Typer entry point — exposes the `bourse` command.
  config.py         pydantic-settings config from environment.
  db/               SQLAlchemy 2.0 models, engine, repositories.
  domain/           Plain dataclasses representing business objects.
  providers/        FMP, EDGAR, Claude clients (real + stubbed).
  screening/        Criteria, composite scoring, verdict thresholds.
  tui/              Textual app, screens, widgets, styles.
alembic/            Migration environment + versioned scripts.
tests/              pytest suites — unit and integration.
docs/               Architecture and contribution docs.
```

See [docs/architecture.md](docs/architecture.md) for the design walkthrough.

## Development

```bash
poetry install --with dev
poetry run pre-commit install
poetry run pytest                 # unit tests, no DB needed
poetry run pytest -m integration  # requires Postgres from docker compose
poetry run ruff check .
poetry run mypy src
```

The CI workflow at `.github/workflows/ci.yml` runs the same checks on every
push and pull request.

## Contributing

Bug reports, feature ideas, and provider implementations are welcome. Please
read [CONTRIBUTING.md](CONTRIBUTING.md) and our
[Code of Conduct](CODE_OF_CONDUCT.md) before opening a pull request.

## License

`openbourse` is licensed under the [Apache License, Version 2.0](LICENSE).
See [NOTICE](NOTICE) for attribution requirements.

## Disclaimer

`openbourse` is a research tool. Outputs are for informational purposes only
and do not constitute financial, investment, legal, or tax advice. The
authors and contributors assume no liability for decisions made using this
software. Always do your own research.
