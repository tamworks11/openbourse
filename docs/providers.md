# Providers

`openbourse` separates *what data we need* from *where the data comes from*.
Three small protocols in `providers/base.py` define the contract:

| Protocol               | Method                                  | Returns                        |
| ---------------------- | --------------------------------------- | ------------------------------ |
| `FundamentalsProvider` | `fetch(ticker)`                         | `FundamentalsSnapshot`         |
| `FilingsProvider`      | `recent_filings(cik, *, limit)`         | `list[Filing]`                 |
| `BriefProvider`        | `write_brief(instrument, snapshot, …)`  | `AiBrief`                      |

Concrete implementations come in pairs: one calls a real API, the other
returns fixture data so contributors can run the app without keys.

## FMP — Financial Modeling Prep

- **Real**: `FmpFundamentalsProvider(api_key=...)`. Uses `httpx.AsyncClient`
  to hit `https://financialmodelingprep.com/api/v3`. Combines the
  `/profile` and `/key-metrics-ttm` endpoints into a single
  `FundamentalsSnapshot`.
- **Stub**: `StubFundamentalsProvider`. Reads from
  `src/openbourse/data/seed.json`. Raises `KeyError` for unknown tickers.

Free FMP plans cap requests/day; production users typically need a paid tier.

## EDGAR — SEC filings

- **Real**: `EdgarFilingsProvider(user_agent=...)`. EDGAR requires a
  descriptive User-Agent containing a contact email. The provider validates
  this on construction. It hits the `data.sec.gov/submissions/CIK*.json`
  endpoint and parses the `recent` block.
- **Stub**: `StubFilingsProvider`. Returns whatever filings are listed in
  `seed.json`. Unknown CIKs return an empty list.

EDGAR has a polite rate limit (10 req/s). Don't parallelize aggressively.

## Claude — AI briefs

- **Real**: `ClaudeBriefProvider(api_key=..., model="claude-sonnet-4-6")`.
  Uses the official `anthropic` SDK with prompt caching enabled on the
  system prompt — every brief in a session shares the cache, dropping
  per-request token cost meaningfully. Splits the response into a summary
  paragraph and bullet points.
- **Stub**: `StubBriefProvider`. Generates a deterministic brief from the
  fundamentals so tests never depend on the network.

If you switch models, update both `OPENBOURSE_CLAUDE_MODEL` and
`docs/providers.md`. Use the latest available Sonnet (`claude-sonnet-4-6`)
for routine briefs and Opus (`claude-opus-4-7`) for deeper analysis.

## Selecting real vs stub at runtime

```python
from openbourse.providers import build_providers

# Defaults to use_stubs=True.
providers = build_providers()

# Override via settings.
from openbourse.config import Settings
providers = build_providers(Settings(use_stubs=False, ...))
```

The `Providers.using_stubs` flag is surfaced in the TUI status bar so users
can tell at a glance whether they're looking at real or fixture data.

## Adding a new provider

1. Define the Protocol in `providers/base.py` (or extend an existing one).
2. Implement the real client in `providers/<source>.py` with `httpx`.
3. Implement a stub returning fixture data from `seed.json`.
4. Wire the real/stub choice into `providers/registry.py`.
5. Add unit tests for the parser using static payloads.
6. Mark live integration tests with `@pytest.mark.live`.
