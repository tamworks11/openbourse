"""SEC EDGAR filings provider.

The real implementation calls the EDGAR submissions endpoint. EDGAR requires
a descriptive ``User-Agent`` identifying the requester — see
``OPENBOURSE_EDGAR_USER_AGENT``.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from typing import Any

import httpx

from openbourse.providers.base import Filing

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def _zero_pad_cik(cik: str) -> str:
    return cik.lstrip("0").zfill(10)


class EdgarFilingsProvider:
    """Real EDGAR client. Network access required."""

    def __init__(
        self,
        user_agent: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                f"EDGAR requires a User-Agent containing a contact email; got {user_agent!r}"
            )
        self._user_agent = user_agent
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": user_agent}
        )
        self._owns_client = client is None

    async def recent_filings(self, cik: str, *, limit: int = 5) -> list[Filing]:
        """Fetch the EDGAR submissions feed for ``cik`` and return ``limit`` filings."""
        padded = _zero_pad_cik(cik)
        url = EDGAR_SUBMISSIONS_URL.format(cik=padded)
        response = await self._client.get(url)
        response.raise_for_status()
        return _parse_submissions(padded, response.json(), limit=limit)

    async def fetch_document(self, filing: Filing) -> str:
        """Fetch the primary document for ``filing`` as a UTF-8 string.

        EDGAR primary documents are HTML for modern filings; the caller is
        responsible for stripping markup. We just guarantee the bytes
        decode cleanly.
        """
        response = await self._client.get(filing.url)
        response.raise_for_status()
        return response.text

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider owns it."""
        if self._owns_client:
            await self._client.aclose()


def _parse_submissions(cik: str, payload: Any, *, limit: int) -> list[Filing]:
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    titles = recent.get("primaryDocDescription", [])

    out: list[Filing] = []
    for form, filed, accession, doc, title in zip(
        forms, dates, accessions, primary_docs, titles, strict=False
    ):
        accession_clean = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{doc}"
        out.append(
            Filing(
                cik=cik,
                form_type=form,
                filed_at=date.fromisoformat(filed),
                accession_number=accession,
                url=url,
                title=title or form,
            )
        )
        if len(out) >= limit:
            break
    return out


class StubFilingsProvider:
    """Returns fixture filings from the bundled seed dataset."""

    def __init__(self, fixture: dict[str, list[Filing]] | None = None) -> None:
        self._fixture = fixture or _load_default_fixture()

    async def recent_filings(self, cik: str, *, limit: int = 5) -> list[Filing]:
        """Return up to ``limit`` fixture filings for ``cik`` (empty list if unknown)."""
        padded = _zero_pad_cik(cik)
        return self._fixture.get(padded, [])[:limit]

    async def fetch_document(self, filing: Filing) -> str:  # pragma: no cover
        """Stub returns an empty string — there's no canned 10-K text to scan."""
        return ""


def _load_default_fixture() -> dict[str, list[Filing]]:
    raw = json.loads(resources.files("openbourse.data").joinpath("seed.json").read_text())
    fixture: dict[str, list[Filing]] = {}
    for entry in raw.get("filings", []):
        cik = _zero_pad_cik(entry["cik"])
        fixture.setdefault(cik, []).append(
            Filing(
                cik=cik,
                form_type=entry["form_type"],
                filed_at=date.fromisoformat(entry["filed_at"]),
                accession_number=entry["accession_number"],
                url=entry["url"],
                title=entry.get("title", entry["form_type"]),
            )
        )
    return fixture
