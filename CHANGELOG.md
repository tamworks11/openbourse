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
- **Filing-text concern scanner** — separate `ConcernScanner` provider that
  pulls the actual 10-K Risk Factors section from EDGAR and asks Claude
  to find verbatim evidence for each concern. Quotes returned by the
  model are validated against the filing text — fabricated quotes are
  dropped. Runs as a background worker on the brief screen so the
  initial brief renders instantly and the concerns section refines in
  place when the scan completes. Results are cached in a new
  `concern_scans` table keyed by `(accession, concerns_hash)` so repeat
  visits hit the cache instead of re-paying for the LLM call.
- **Manual rescan** — press `r` on the brief screen to force a fresh
  concern scan that bypasses the cache. Useful when a new 10-K has been
  filed but our cache key still points at the prior accession.
  Successful rescans still update the cache.
- **Risk score (0-100) + risk-tolerance filter** — new pure-function
  metric in `screening.risk` that captures vulnerability (high leverage,
  small cap, thin margins, low FCF yield) as a single transparent
  number. Filterable as `max_risk_score` in the screen definition; the
  filter editor adds a "Risk score ≤ N" row alongside the existing
  threshold knobs. Surfaces on the screener detail pane and brief header
  next to the existing composite score, so a high-quality but high-risk
  name is visibly distinct from a high-quality low-risk name. Lookup CLI
  output (text + JSON) includes the risk score.
- **Risk-band glyph in tickers table** — new `RISK` column shows a
  coloured `●` plus the score: green for low (≤30), yellow for moderate
  (30-60), red for high (≥60). Same colouring is applied to the `Risk N`
  value in the detail pane and brief header for consistency, so the user
  can scan the screener for high-risk outliers at a glance.
- **Polled live quotes** — new `QuoteProvider` protocol with stub,
  yfinance (parallel `fast_info`), and FMP (batched `/quote?symbols=…`)
  implementations. The screener fires a background poll every
  `OPENBOURSE_QUOTE_REFRESH_SECONDS` (default 60s, set 0 to disable)
  and updates the `PRICE` cell in place via `update_cell_at` — no full
  repaint, no detail-pane flicker. Status bar grows a "Quotes · 12s
  ago / off" indicator that ticks every second so freshness is always
  visible. The polled value also flows into the detail pane so the
  focused row stays consistent.
- **Viewport-aware polling** — the polling loop now refreshes the rows
  currently visible in the table (plus a 20-row buffer above and below)
  rather than just the top 100 by score. Scrolling into row 500 of a
  1000-name universe gets fresh quotes on the next poll cycle instead
  of staying stuck at snapshot prices. Hard-capped at 100 tickers per
  cycle to protect against extra-tall terminals or huge universes.
- **Valuation panel** — new section on the brief screen showing P/E,
  EV/EBITDA, EV/Revenue, and P/FCF for the focused ticker, each with a
  percentile-rank bar against its own 5-year history. Bar colour
  encodes cheap (green ≤30th pct), fair (yellow), or expensive (red
  ≥70th pct) — same band logic as the risk-score column on the
  screener so the visual language stays consistent. Loads independently
  of the AI brief so the price chart and trend grid don't wait for
  multiples. New `FundamentalsProvider.valuation()` Protocol method
  with stub, yfinance, and FMP implementations; FMP free-tier returns
  current-only bands and the panel renders gracefully without history.
- **ROIC trend chart** — separate full-width chart on the brief screen
  between the 2x2 fundamentals grid and the valuation panel. Plots
  Return on Invested Capital over the same annual snapshots as the
  trend grid, with the current value and percentage-point change in
  the title. New `FundamentalsSnapshot.roic_pct` field; yfinance
  computes from operating income / invested capital, FMP pulls
  `roicTTM` from `/key-metrics-ttm`, the stub synthesises from gross
  margin + FCF yield. Snapshots with ROIC=0 (provider couldn't compute)
  are dropped before charting so the line doesn't dip to zero.

### Changed

- **yfinance history default 4 → 8 years** — the small fundamentals
  charts on the brief screen now render up to 7 data points (8 minus the
  YoY pad) instead of 3, giving more historical context per metric.
  `history_period` also bumped from 6y to 10y so the underlying
  price/statement fetch has the data it needs. FMP's default stays at 4
  to keep free-tier requests under FMP's 5-row endpoint cap; FMP paid
  users can override.

### Changed

- `AiBrief` no longer carries a single `bullets` field; consumers should
  use `bull` / `bear` / `risks` / `concerns` instead. CLI `--output json`
  output for `bourse lookup --brief` mirrors the new shape.

### Fixed

- **DB-sync marker no longer truncated.** The status bar packed identity,
  screen path, and the DB-sync freshness marker into a single content
  row; on normal-width terminals the marker (last in line) was clipped
  off the right edge and appeared missing. The status bar is now a
  genuine two-row header — identity + clock on top, DB-sync + provider
  markers below — so each marker has room to render in full.

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
