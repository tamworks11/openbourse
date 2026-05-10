"""Provider abstractions.

Three small protocols describe everything the screening service needs from
the outside world:

* :class:`FundamentalsProvider` — point-in-time financial ratios.
* :class:`FilingsProvider` — recent SEC filings.
* :class:`BriefProvider` — AI-generated qualitative summaries.

Concrete implementations live alongside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from openbourse.domain import (
    AiBrief,
    ConcernFinding,
    FundamentalsSnapshot,
    Instrument,
    Quote,
)


@dataclass(frozen=True, slots=True)
class Filing:
    """A single SEC filing surfaced by a :class:`FilingsProvider`."""

    cik: str
    form_type: str
    filed_at: date
    accession_number: str
    url: str
    title: str = ""


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Fetches fundamentals for a single instrument."""

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Return the most recent :class:`FundamentalsSnapshot` for ``ticker``."""
        ...

    async def history(self, ticker: str, *, limit: int = 8) -> list[FundamentalsSnapshot]:
        """Return up to ``limit`` historical snapshots for ``ticker``.

        Snapshots are returned ascending by ``as_of`` so callers can feed
        them straight into a chart. Implementations should silently return
        an empty list when no history is available rather than raising.
        """
        ...

    async def metadata(self, ticker: str) -> Instrument:
        """Return identity metadata (name, sector, exchange, CIK) for ``ticker``.

        Used by the universe ingest pipeline so the ``instruments`` table
        stores proper company names rather than just the ticker. Should
        raise :class:`KeyError` when the ticker is unknown to this provider.
        """
        ...

    async def price_history(
        self, ticker: str, *, period: str = "3y", interval: str = "1d"
    ) -> list[tuple[date, float]]:
        """Return ``(date, close_price)`` pairs ascending by date.

        ``period`` follows yfinance's mini-DSL (``1y``, ``3y``, ``5y``,
        ``max``); ``interval`` is the bar size (``1d``, ``1wk``, ``1mo``).
        Implementations should return an empty list when no data is
        available rather than raising — the chart widget renders a clean
        "insufficient data" placeholder for empty input.
        """
        ...


@runtime_checkable
class FilingsProvider(Protocol):
    """Fetches recent filings for an instrument's CIK."""

    async def recent_filings(self, cik: str, *, limit: int = 5) -> list[Filing]:
        """Return up to ``limit`` recent filings for ``cik``, newest first."""
        ...

    async def fetch_document(self, filing: Filing) -> str:
        """Return the primary document (typically HTML) for ``filing``.

        Used by the concern scanner to pull 10-K text for evidence-based
        analysis. Implementations should return the raw response body —
        callers handle markup stripping. Stub providers can return an
        empty string when no canned document is available.
        """
        ...


@runtime_checkable
class BriefProvider(Protocol):
    """Generates an AI-authored qualitative brief."""

    async def write_brief(
        self,
        instrument: Instrument,
        snapshot: FundamentalsSnapshot,
        filings: list[Filing] | None = None,
        concerns: list[str] | None = None,
    ) -> AiBrief:
        """Return an :class:`AiBrief` with bull / bear / risks / concerns sections.

        ``concerns`` is the user-supplied list of issues to evaluate
        (e.g. "Customer concentration"). Implementations should produce a
        :class:`~openbourse.domain.ConcernFinding` per supplied concern,
        even if the status is ``"unknown"``. Falls back to a sensible
        default list when ``None`` is passed.
        """
        ...


@runtime_checkable
class QuoteProvider(Protocol):
    """Fetches latest price quotes for one or more tickers.

    Distinct from :class:`FundamentalsProvider` — quotes refresh on the
    seconds-to-minutes timescale and only carry price/volume, while
    fundamentals refresh on the weeks-to-quarters timescale and carry
    the full snapshot. Splitting them lets the TUI tick the price column
    independently of the (expensive) full snapshot pipeline.
    """

    async def fetch_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        """Return latest :class:`Quote` keyed by ticker.

        Tickers without a quote are simply omitted from the dict — the
        caller treats absence as "no fresh data" and keeps the previous
        value. Implementations should batch when the upstream supports
        it (e.g., FMP's comma-separated multi-symbol endpoint) and run
        sequential per-ticker fetches in parallel otherwise.
        """
        ...


@runtime_checkable
class ConcernScanner(Protocol):
    """Scans 10-K filing text for evidence of user-defined concerns.

    Distinct from :class:`BriefProvider` — the brief provider asks the LLM
    to *summarize* a company; the concern scanner asks it to *find evidence*
    in primary-source filing text and return verbatim quotes. Separating
    them keeps prompts focused, lets us cache scans independently, and
    means a brief regeneration doesn't pay for an expensive re-scan.
    """

    async def scan(
        self,
        *,
        ticker: str,
        filing_text: str,
        concerns: list[str],
    ) -> list[ConcernFinding]:
        """Return one :class:`ConcernFinding` per concern in ``concerns``.

        ``filing_text`` is typically the Item 1A. Risk Factors section.
        Implementations must produce a finding for every supplied concern,
        defaulting to ``status="unknown"`` when the text doesn't contain
        evidence either way. Quotes in ``note`` should be verbatim from
        ``filing_text``; do not paraphrase.
        """
        ...


@dataclass(frozen=True, slots=True)
class Providers:
    """Bundle of every provider the application needs.

    The four ``*_mode`` fields are either ``"live"`` or ``"stub"`` per
    provider. They power the status-bar indicators and let the registry
    mix-and-match so a missing Claude key doesn't disable a working FMP
    setup.
    """

    fundamentals: FundamentalsProvider
    filings: FilingsProvider
    brief: BriefProvider
    scanner: ConcernScanner
    quotes: QuoteProvider
    fundamentals_mode: str = field(default="stub")
    filings_mode: str = field(default="stub")
    brief_mode: str = field(default="stub")
    scanner_mode: str = field(default="stub")
    quotes_mode: str = field(default="stub")

    @property
    def using_stubs(self) -> bool:
        """True iff every provider is a stub. Kept for backwards compatibility."""
        return (
            self.fundamentals_mode == "stub"
            and self.filings_mode == "stub"
            and self.brief_mode == "stub"
            and self.scanner_mode == "stub"
            and self.quotes_mode == "stub"
        )

    @property
    def all_live(self) -> bool:
        """True iff every provider is live."""
        return (
            self.fundamentals_mode == "live"
            and self.filings_mode == "live"
            and self.brief_mode == "live"
            and self.scanner_mode == "live"
            and self.quotes_mode == "live"
        )
