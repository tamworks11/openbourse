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

from openbourse.domain import AiBrief, FundamentalsSnapshot, Instrument


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


@runtime_checkable
class FilingsProvider(Protocol):
    """Fetches recent filings for an instrument's CIK."""

    async def recent_filings(self, cik: str, *, limit: int = 5) -> list[Filing]:
        """Return up to ``limit`` recent filings for ``cik``, newest first."""
        ...


@runtime_checkable
class BriefProvider(Protocol):
    """Generates an AI-authored qualitative brief."""

    async def write_brief(
        self,
        instrument: Instrument,
        snapshot: FundamentalsSnapshot,
        filings: list[Filing] | None = None,
    ) -> AiBrief:
        """Return an :class:`AiBrief` summarising the instrument and its filings."""
        ...


@dataclass(frozen=True, slots=True)
class Providers:
    """Bundle of every provider the application needs.

    The three ``*_mode`` fields are either ``"live"`` or ``"stub"`` per
    provider. They power the status-bar indicators and let the registry
    mix-and-match so a missing Claude key doesn't disable a working FMP
    setup.
    """

    fundamentals: FundamentalsProvider
    filings: FilingsProvider
    brief: BriefProvider
    fundamentals_mode: str = field(default="stub")
    filings_mode: str = field(default="stub")
    brief_mode: str = field(default="stub")

    @property
    def using_stubs(self) -> bool:
        """True iff every provider is a stub. Kept for backwards compatibility."""
        return (
            self.fundamentals_mode == "stub"
            and self.filings_mode == "stub"
            and self.brief_mode == "stub"
        )

    @property
    def all_live(self) -> bool:
        """True iff every provider is live."""
        return (
            self.fundamentals_mode == "live"
            and self.filings_mode == "live"
            and self.brief_mode == "live"
        )
