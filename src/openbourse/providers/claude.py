"""Anthropic Claude AI brief provider.

The real implementation uses the official ``anthropic`` SDK with prompt
caching on the system prompt. The stub returns a deterministic, formula-
generated brief so the rest of the application is exercised in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from openbourse.domain import AiBrief, FundamentalsSnapshot, Instrument
from openbourse.providers.base import Filing

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import AsyncAnthropic

SYSTEM_PROMPT = (
    "You are an experienced equity research analyst. Given an instrument and "
    "its latest fundamentals, write a concise, neutral brief: 2-3 sentences "
    "of summary and 3-5 bullet points covering moat, growth drivers, key "
    "risks, and recent filings if provided. Avoid recommendations."
)


class ClaudeBriefProvider:
    """Real Claude client. Network access and API key required."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-sonnet-4-6",
        client: AsyncAnthropic | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Claude API key is required")
        from anthropic import AsyncAnthropic

        self._model = model
        self._client = client or AsyncAnthropic(api_key=api_key)

    async def write_brief(
        self,
        instrument: Instrument,
        snapshot: FundamentalsSnapshot,
        filings: list[Filing] | None = None,
    ) -> AiBrief:
        user_text = _render_prompt(instrument, snapshot, filings or [])
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
        from anthropic.types import TextBlock

        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        summary, bullets = _split_brief(text)
        return AiBrief(
            ticker=instrument.ticker,
            generated_at=datetime.now(UTC),
            model=self._model,
            summary=summary,
            bullets=tuple(bullets),
            raw={"id": message.id, "usage": message.usage.model_dump() if message.usage else {}},
        )


def _render_prompt(
    instrument: Instrument, snapshot: FundamentalsSnapshot, filings: list[Filing]
) -> str:
    lines = [
        f"Ticker: {instrument.ticker}",
        f"Name: {instrument.name}",
        f"Sector: {instrument.sector or 'unknown'}",
        f"Market cap: ${snapshot.market_cap_usd / 1e9:.1f}B",
        f"Revenue growth: {snapshot.revenue_growth_pct:.1f}%",
        f"Gross margin: {snapshot.gross_margin_pct:.1f}%",
        f"Net debt / EBITDA: {snapshot.net_debt_to_ebitda:.2f}",
        f"FCF yield: {snapshot.fcf_yield_pct:.1f}%",
    ]
    if filings:
        lines.append("Recent filings:")
        for f in filings[:5]:
            lines.append(f"- {f.filed_at} {f.form_type} {f.title}")
    return "\n".join(lines)


def _split_brief(text: str) -> tuple[str, list[str]]:
    """Best-effort parse of the model's response into summary + bullets."""

    summary_lines: list[str] = []
    bullets: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "•")):
            bullets.append(line.lstrip("-*• ").strip())
        elif bullets:
            bullets[-1] = f"{bullets[-1]} {line}"
        else:
            summary_lines.append(line)
    return " ".join(summary_lines), bullets


class StubBriefProvider:
    """Deterministic brief generator for offline development and testing."""

    def __init__(self, model: str = "stub-claude-sonnet-4-6") -> None:
        self._model = model

    async def write_brief(
        self,
        instrument: Instrument,
        snapshot: FundamentalsSnapshot,
        filings: list[Filing] | None = None,
    ) -> AiBrief:
        summary = (
            f"{instrument.name} ({instrument.ticker}) — "
            f"{snapshot.gross_margin_pct:.0f}% gross margin business growing revenue "
            f"{snapshot.revenue_growth_pct:.1f}% with leverage at "
            f"{snapshot.net_debt_to_ebitda:.1f}x net debt/EBITDA."
        )
        bullets = [
            f"Market cap: ${snapshot.market_cap_usd / 1e9:.1f}B "
            f"({instrument.sector or 'sector unknown'}).",
            f"Free cash flow yield: {snapshot.fcf_yield_pct:.1f}%.",
            "Watch: durability of unit economics and customer concentration.",
            "Risk: macro / rate sensitivity in valuation multiple.",
        ]
        if filings:
            bullets.append(f"Most recent filing: {filings[0].form_type} on {filings[0].filed_at}.")
        return AiBrief(
            ticker=instrument.ticker,
            generated_at=datetime.now(UTC),
            model=self._model,
            summary=summary,
            bullets=tuple(bullets),
            raw={"stub": True},
        )
