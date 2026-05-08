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
    """Bundle of every provider the application needs."""

    fundamentals: FundamentalsProvider
    filings: FilingsProvider
    brief: BriefProvider
    using_stubs: bool = field(default=False)
