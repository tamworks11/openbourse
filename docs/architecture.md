# Architecture

`openbourse` is a small, layered application. Each layer talks to the next
through narrow interfaces so providers, the database, and the TUI can evolve
independently.

```
┌──────────────────────────────────────────────────────────────────┐
│                         Textual TUI (tui/)                       │
│  app.py · screens/screener.py · screens/brief.py · widgets/      │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Screening service (screening/)                │
│  service.run(screen, universe) → ScreenResult                    │
│  pure functions: passes_screen(), composite_score(), verdict_for │
└──────────────────────────────────────────────────────────────────┘
       │                                            │
       ▼                                            ▼
┌─────────────────────┐                  ┌──────────────────────────┐
│  Database (db/)     │                  │   Providers (providers/) │
│  SQLAlchemy 2.0     │                  │   FundamentalsProvider   │
│  + Alembic          │                  │   FilingsProvider        │
│  Repositories       │                  │   BriefProvider          │
└─────────────────────┘                  │   real ↔ stub            │
                                         └──────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────────┐
                │ Domain dataclasses (domain/) │
                │ Instrument, Snapshot,        │
                │ Candidate, Verdict, Screen,  │
                │ ScreenResult, AiBrief        │
                └──────────────────────────────┘
```

## Why these boundaries

- **Domain dataclasses** are the lingua franca. They are framework-free, so
  the screening logic and tests never depend on SQLAlchemy or HTTP clients.
- **Providers** are protocols, not classes — anything implementing
  `async fetch(...)` is a `FundamentalsProvider`. This keeps the door open
  for new data sources without touching call sites.
- **Repositories** convert ORM rows to and from domain objects. The TUI and
  CLI never see SQLAlchemy types directly.
- **Screening** is fully synchronous and pure. It takes a universe iterator
  and returns a `ScreenResult`. This makes it trivial to test exhaustively.
- **TUI** orchestrates the rest. It loads a universe (DB → fixture
  fallback), runs the screen, and renders. Nothing in the lower layers
  knows about Textual.

## Async story

Textual runs on `asyncio`. To match it cleanly we use:

- `sqlalchemy[asyncio]` with `AsyncEngine` and `AsyncSession`.
- `httpx.AsyncClient` for provider HTTP calls.
- `alembic` invoked through `async_engine_from_config` plus `run_sync` —
  Alembic itself is sync inside, but the connection it uses is async.

The screening service is intentionally synchronous: feeding it pre-loaded
data keeps the "math" deterministic and trivially testable, and the TUI
already runs it on a worker if it ever becomes expensive.

## Configuration

`config.py` exposes a single `Settings` model loaded from the environment
(via `pydantic-settings`) with the `OPENBOURSE_` prefix. `get_settings()`
caches the instance for the lifetime of the process; `reset_settings_cache()`
exists so tests can mutate the environment cleanly.

## Stubs vs real providers

`providers.build_providers()` reads `Settings.use_stubs`. Stub providers
load fixtures from `src/openbourse/data/seed.json` and return synchronously
from in-memory dictionaries. This means:

- The full app — TUI included — runs without any API keys.
- Tests can exercise every code path without network access.
- New contributors get a working dev loop in seconds.

When you implement a real provider, follow the same protocol and toggle
the registry. Real-API tests should be marked `@pytest.mark.live` and
skipped unless the relevant credential is present in the environment.

## Database schema

| Table                    | Purpose                                       |
| ------------------------ | --------------------------------------------- |
| `instruments`            | Master list — ticker, name, sector, CIK.      |
| `fundamentals_snapshots` | Point-in-time financial ratios per ticker.    |
| `screens`                | Persisted screen definitions.                 |
| `screen_runs`            | Audit trail of historical screen executions.  |
| `watchlist_entries`      | User-curated tickers with notes.              |
| `ai_briefs`              | Cached Claude-generated qualitative briefs.   |

All schema changes go through Alembic. The initial migration is
`alembic/versions/0001_initial_schema.py`.

## Scoring formula

Composite score is a weighted average of five normalized components:

| Component   | Source                  | Default weight | Notes                       |
| ----------- | ----------------------- | -------------- | --------------------------- |
| `growth`    | revenue growth %        | 0.30           | capped at 30%               |
| `margin`    | gross margin %          | 0.25           | capped at 100%              |
| `leverage`  | net debt / EBITDA       | 0.15           | inverted; 0x=1.0, ≥3x=0.0   |
| `fcf_yield` | free-cash-flow yield %  | 0.20           | capped at 8%                |
| `size`      | log market cap          | 0.10           | $1B → 0.0, ≥$100B → 1.0     |

The result is multiplied by 100 and rounded to an integer in `[0, 100]`.
Verdict thresholds: `≥90 STRONG_INTEREST`, `≥80 INTERESTING`, `≥70 PASS`,
`<70 REJECT`.

Weights are tunable via the `Weights` dataclass; tests assert the defaults
sum to 1.0.
