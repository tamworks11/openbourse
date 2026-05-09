"""External ticker-list sources — Wikipedia, iShares ETF holdings, more later.

Two parser families today:

* **Wikipedia HTML tables** for indices small enough to maintain by hand
  (S&P 500, Nasdaq-100, Dow 30). We walk every ``<table>`` on the page
  and pick the first one with a ticker-shaped column and at least
  ``MIN_TICKER_TABLE_ROWS`` rows.
* **iShares ETF holdings CSV** for larger indices like the Russell 1000 /
  2000 / 3000. Wikipedia doesn't keep a 2,000-name list current; the
  IWB / IWM / IWV ETFs do, by fund-management mandate. We download the
  daily holdings CSV from iShares and filter to equity holdings.

Each source is a :class:`Source` value with a ``fetch`` callable, so
adding a new vendor means adding one constructor and one entry in
:data:`KNOWN_SOURCES`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from io import StringIO

import httpx
import pandas as pd  # type: ignore[import-untyped]

# Wikipedia and iShares are friendly but ratelimit anonymous bots — a
# descriptive UA also helps if you hit a 403.
HTTP_TIMEOUT_SECONDS = 30.0
HTTP_USER_AGENT = "openbourse/0.1 (https://github.com/OpenBourse/openbourse)"

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKIPEDIA_NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
WIKIPEDIA_DOW30_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"

# iShares URLs are stable but a bit verbose. The ``1467271812596`` segment
# is the same site-wide identifier across every iShares fund page.
ISHARES_AJAX_TEMPLATE = (
    "https://www.ishares.com/us/products/{product_id}/{slug}/"
    "1467271812596.ajax"
    "?fileType=csv&fileName={etf}_holdings&dataType=fund"
)
# IWV (Russell 3000) is intentionally absent: that ETF uses stratified
# sampling rather than full replication, so its published holdings file
# only covers ~400 names — useless as a Russell 3000 ticker list.
# We synthesise russell3000 by unioning IWB + IWM instead.
ISHARES_FUNDS = {
    "IWB": ("239707", "ishares-russell-1000-etf"),
    "IWM": ("239710", "ishares-russell-2000-etf"),
}

MIN_TICKER_TABLE_ROWS = 20


@dataclass(frozen=True)
class Source:
    """A named ticker-list source plus a callable that returns its tickers."""

    name: str
    label: str
    url: str
    fetch: Callable[[], list[str]]


def _wiki_source(name: str, label: str, url: str, columns: tuple[str, ...]) -> Source:
    return Source(
        name=name,
        label=label,
        url=url,
        fetch=lambda: _fetch_wikipedia_table(url, columns),
    )


def _ishares_source(name: str, label: str, etf: str) -> Source:
    product_id, slug = ISHARES_FUNDS[etf]
    url = ISHARES_AJAX_TEMPLATE.format(product_id=product_id, slug=slug, etf=etf)
    return Source(
        name=name,
        label=label,
        url=url,
        fetch=lambda: _fetch_ishares_holdings(url, etf),
    )


def _combined_source(name: str, label: str, members: tuple[str, ...]) -> Source:
    """Build a synthetic source that unions other sources' tickers, in order."""

    def fetch() -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for member in members:
            for ticker in KNOWN_SOURCES[member].fetch():
                if ticker not in seen:
                    seen.add(ticker)
                    out.append(ticker)
        return out

    return Source(name=name, label=label, url="(synthetic)", fetch=fetch)


KNOWN_SOURCES: dict[str, Source] = {
    "sp500": _wiki_source(
        "sp500", "S&P 500 (Wikipedia)", WIKIPEDIA_SP500_URL, ("Symbol", "Ticker")
    ),
    "nasdaq100": _wiki_source(
        "nasdaq100", "Nasdaq-100 (Wikipedia)", WIKIPEDIA_NASDAQ100_URL, ("Ticker", "Symbol")
    ),
    "dow30": _wiki_source("dow30", "Dow 30 (Wikipedia)", WIKIPEDIA_DOW30_URL, ("Symbol", "Ticker")),
    "russell1000": _ishares_source("russell1000", "Russell 1000 (iShares IWB holdings)", "IWB"),
    "russell2000": _ishares_source("russell2000", "Russell 2000 (iShares IWM holdings)", "IWM"),
}
# Synthetic union — added after the dict so it can reference its members.
KNOWN_SOURCES["russell3000"] = _combined_source(
    "russell3000",
    "Russell 3000 (Russell 1000 + Russell 2000)",
    ("russell1000", "russell2000"),
)


def fetch_source(name: str) -> list[str]:
    """Fetch a known source's tickers, normalised for Yahoo Finance.

    Raises :class:`KeyError` if ``name`` isn't in :data:`KNOWN_SOURCES`.
    Network errors propagate to the caller — letting the CLI surface a
    clean message rather than swallowing transient failures here.
    """
    if name not in KNOWN_SOURCES:
        raise KeyError(f"unknown source: {name!r} — available: {sorted(KNOWN_SOURCES)}")
    return KNOWN_SOURCES[name].fetch()


def fetch_sp500_from_wikipedia() -> list[str]:
    """Return the current S&P 500 constituents (alias for ``fetch_source('sp500')``)."""
    return fetch_source("sp500")


# --- Wikipedia HTML tables --------------------------------------------------


def _fetch_wikipedia_table(url: str, candidate_columns: tuple[str, ...]) -> list[str]:
    """Find the constituents table on a Wikipedia page and extract its tickers.

    Walks every ``<table>`` on the page and returns the first one whose
    columns include any of ``candidate_columns`` AND has at least
    ``MIN_TICKER_TABLE_ROWS`` rows (filters out footer/legend tables that
    happen to share a column name).

    Uses ``httpx`` to fetch the HTML rather than letting pandas/urllib do it
    directly — that way we don't depend on the system certificate store
    (an issue on the python.org Python 3.14 installer for macOS, among
    others) and we get to set a polite User-Agent.
    """
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": HTTP_USER_AGENT},
    )
    response.raise_for_status()
    # pandas.read_html treats bare strings as paths; wrap in StringIO to
    # force HTML parsing on the in-memory document we just fetched.
    tables = pd.read_html(StringIO(response.text))

    seen_columns: list[list[str]] = []
    for df in tables:
        cols = [str(c) for c in df.columns]
        seen_columns.append(cols)
        if len(df) < MIN_TICKER_TABLE_ROWS:
            continue
        for column in candidate_columns:
            if column in df.columns:
                raw = df[column].astype(str).tolist()
                return _dedupe_preserving_order(_normalize_ticker(t) for t in raw)

    raise RuntimeError(
        f"Wikipedia layout changed: no table on {url} has any of "
        f"{list(candidate_columns)} as a column with ≥{MIN_TICKER_TABLE_ROWS} "
        f"rows. Saw {len(tables)} tables; columns were: {seen_columns}"
    )


# --- iShares ETF holdings ---------------------------------------------------


def _fetch_ishares_holdings(url: str, etf: str) -> list[str]:
    """Download an iShares ETF holdings CSV and return its equity tickers.

    iShares CSVs lead with several rows of fund metadata (date, NAV,
    distribution detail) before the actual holdings table. We locate the
    real header by finding the first line that begins with ``Ticker,``
    and parse from there. Non-equity holdings (cash, futures, money-market
    funds used for collateral) are filtered out via ``Asset Class``.
    """
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": HTTP_USER_AGENT},
    )
    response.raise_for_status()
    return _parse_ishares_csv(response.text, etf)


def _parse_ishares_csv(text: str, etf: str) -> list[str]:
    """Pure-text parser for iShares holdings CSVs."""
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("Ticker,")),
        -1,
    )
    if header_idx < 0:
        raise RuntimeError(
            f"iShares CSV layout changed for {etf}: no 'Ticker,' header row found "
            f"in {len(lines)} lines"
        )
    csv_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(StringIO(csv_text))
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].astype(str).str.strip() == "Equity"]
    if "Ticker" not in df.columns:
        raise RuntimeError(
            f"iShares CSV layout changed for {etf}: no 'Ticker' column after "
            f"filtering. Saw columns: {list(df.columns)}"
        )
    raw = df["Ticker"].astype(str).tolist()
    return _dedupe_preserving_order(_normalize_ticker(t) for t in raw)


# --- Shared helpers ---------------------------------------------------------


def _normalize_ticker(ticker: str) -> str:
    """Yahoo Finance uses ``BRK-B`` where Wikipedia/iShares print ``BRK.B``.

    Strips whitespace, uppercases, and converts dot class-share separators
    to the dash Yahoo expects. ``BF.B`` -> ``BF-B``. Also strips trailing
    common suffixes like ``-`` that iShares occasionally leaves behind.
    """
    cleaned = ticker.strip().upper()
    return cleaned.replace(".", "-")


def _dedupe_preserving_order(it: Iterable[str]) -> list[str]:
    """Yield unique tickers in first-seen order, dropping blanks/NaN-as-string."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in it:
        if not isinstance(raw, str):
            continue
        ticker = raw.strip()
        if not ticker or ticker.lower() == "nan":
            continue
        # iShares pads many cash/futures lines with "-" — drop them.
        if ticker in {"-", "—"}:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out
