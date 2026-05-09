# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Structured AI brief** — replaces the single-paragraph summary with three
  parallel sections (Bull case, Bear case, Risks to monitor) plus a
  user-defined Concerns checklist. Forces the model to make the bear case
  visible instead of burying it.
- **Style-fit score** — per-screen 0-100 score showing how closely a
  candidate's metrics match the active screen's enabled criteria. Surfaced
  alongside the composite score on the screener detail pane and brief
  header. Distinct from the composite score, which is style-agnostic.
- **Concern findings** — every brief evaluates a default list of concerns
  (customer concentration, SBC weight, insider selling, accounting
  aggressiveness, …) and renders a per-concern flagged/clear/unknown
  status. The list can be overridden per `write_brief` call; an editor UI
  is on the roadmap.

### Changed

- `AiBrief` no longer carries a single `bullets` field; consumers should
  use `bull` / `bear` / `risks` / `concerns` instead. CLI `--output json`
  output for `bourse lookup --brief` mirrors the new shape.

## [0.1.0] - 2026-05-08

### Added

- **TUI** — Bloomberg-style full-bleed Textual app with status bar, screen
  metadata + live filter line, candidate table, focused-row detail pane,
  bottom command bar, and footer keybinds.
- **Screens** — `all`, `quality_compounders`, `deep_value`, `high_growth`
  built-in. Per-criterion thresholds (rev growth, gross margin, net debt /
  EBITDA, market cap, FCF yield) plus an optional verdict-set filter.
- **Filter editor** — `f` key opens a modal that toggles each criterion on
  or off and edits its threshold; live re-runs the screen on Apply.
- **Composite scoring** — pure-function score (0–100) and verdict thresholds
  (`STRONG_INTEREST` ≥90, `INTERESTING` ≥80, `PASS` ≥70, else `REJECT`),
  with adjustable component weights.
- **History charts** — 2×2 plotext grid (revenue growth, gross margin, FCF
  yield, net debt/EBITDA) on the brief screen.
- **Fast-scroll keys** — `g`/`G` jump to top/bottom, `[`/`]` ±25 rows,
  `{`/`}` ±100 rows, plus the standard arrows / page-up / page-down.
- **Lookup** — `bourse lookup TICKER` (CLI) or `:lookup TICKER` (TUI command
  bar) for ad-hoc research; `--history` persists annual snapshots.
- **Universe ingest** — `bourse universe ingest --source [sp500|nasdaq100|
  dow30|russell1000|russell2000|russell3000]` builds your screening
  universe via Wikipedia (small indices) + iShares ETF holdings (Russell).
- **Providers** —
  - `yfinance` (default, free): fetch + history + metadata + business summary.
  - `fmp` (paid optional): same surface against FMP's `/stable` API.
  - `edgar` (free): SEC filings list, polite User-Agent.
  - `anthropic` (paid optional): AI-generated qualitative briefs.
  - All three protocols (`FundamentalsProvider`, `FilingsProvider`,
    `BriefProvider`) ship with a stub variant for offline use and tests.
- **Database** — SQLAlchemy 2.0 async + Alembic. Tables: `instruments`,
  `fundamentals_snapshots`, `screens`, `screen_runs`, `watchlist_entries`,
  `ai_briefs`. Repository-pattern data access.
- **CLI** — Typer-based `bourse run` / `lookup` / `universe ingest|sources|
  fetch-list` / `db migrate|seed` / `screen list|run` / `version`.
- **Tooling** — Poetry 2 (PEP 621), ruff (with pydocstyle), mypy strict,
  pytest with `integration` and `live` markers, pre-commit, docker-compose
  for Postgres on port 5433.
- **Docs** — README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY,
  `docs/architecture.md`, `docs/development.md`, `docs/providers.md`.
- **CI** — GitHub Actions: lint + mypy + pytest on Python 3.11 / 3.12 / 3.13,
  plus integration job with a Postgres service.

### Notes

- The bundled `seed.json` contains 10 hand-curated tickers with 8 quarters
  of synthetic but plausible fundamentals — useful for offline demos and
  tests, not for actual investment decisions.
- The default fundamentals provider is **yfinance** (no API key, no
  quota). FMP requires a key and runs against the modern `/stable` API
  with free-tier-friendly endpoint choices.

[Unreleased]: https://github.com/OpenBourse/openbourse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OpenBourse/openbourse/releases/tag/v0.1.0
