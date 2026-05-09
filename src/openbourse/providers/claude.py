"""Anthropic Claude AI brief provider.

The real implementation uses the official ``anthropic`` SDK with prompt
caching on the system prompt. The stub returns a deterministic, formula-
generated brief so the rest of the application is exercised in tests.

Output shape — both providers produce the same JSON-style structure:

* ``summary`` — one-line headline
* ``bull``    — strongest pro-ownership arguments
* ``bear``    — strongest anti-ownership arguments
* ``risks``   — specific failure modes / what could go wrong
* ``concerns``— per-user-supplied-concern findings
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from openbourse.domain import AiBrief, ConcernFinding, FundamentalsSnapshot, Instrument
from openbourse.providers.base import Filing
from openbourse.screening.concerns import DEFAULT_CONCERNS

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import AsyncAnthropic

SYSTEM_PROMPT = (
    "You are an experienced equity research analyst. Given an instrument and "
    "its latest fundamentals, produce a structured, neutral brief in strict "
    "JSON form. Stick to what the data and recent filings actually say — "
    "avoid directional recommendations or price targets. The user wants "
    "decision support, not decision making."
)

JSON_SCHEMA_INSTRUCTIONS = (
    "Return a JSON object with these exact keys and types — no preamble, no "
    "trailing prose, no markdown fences:\n"
    "{\n"
    '  "summary": "<one or two sentences>",\n'
    '  "bull":  ["<arg>", "<arg>", ...],\n'
    '  "bear":  ["<arg>", "<arg>", ...],\n'
    '  "risks": ["<failure mode>", "<failure mode>", ...],\n'
    '  "concerns": {\n'
    '     "<concern verbatim>": {"status": "flagged"|"clear"|"unknown", '
    '"note": "<short reason>"},\n'
    "     ...\n"
    "  }\n"
    "}\n"
    'Each list should have 2-4 entries. "status" must be one of "flagged", '
    '"clear", or "unknown". Use "unknown" rather than fabricating evidence.'
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
        concerns: list[str] | None = None,
    ) -> AiBrief:
        """Render the prompt, call Claude, and parse the JSON response.

        The system prompt is marked ``cache_control: ephemeral`` so every brief
        in a session reuses the cached prefix and pays only for the user-side
        delta in tokens.
        """
        active_concerns = list(concerns) if concerns is not None else list(DEFAULT_CONCERNS)
        user_text = _render_prompt(instrument, snapshot, filings or [], active_concerns)
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT + "\n\n" + JSON_SCHEMA_INSTRUCTIONS,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
        from anthropic.types import TextBlock

        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        parsed = _parse_brief_json(text)
        return _build_brief(
            instrument.ticker,
            self._model,
            parsed,
            active_concerns,
            raw={
                "id": message.id,
                "usage": message.usage.model_dump() if message.usage else {},
            },
        )


def _render_prompt(
    instrument: Instrument,
    snapshot: FundamentalsSnapshot,
    filings: list[Filing],
    concerns: list[str],
) -> str:
    """Format the user-side message for Claude. Plain text, no JSON yet."""
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
    if instrument.business_summary:
        lines.append("")
        lines.append("Business: " + instrument.business_summary)
    if filings:
        lines.append("")
        lines.append("Recent filings:")
        for f in filings[:5]:
            lines.append(f"- {f.filed_at} {f.form_type} {f.title}")
    lines.append("")
    lines.append("Concerns to evaluate (return one entry per concern, status + note):")
    for concern in concerns:
        lines.append(f"- {concern}")
    return "\n".join(lines)


def _parse_brief_json(text: str) -> dict[str, Any]:
    """Extract the JSON object from Claude's response.

    Anthropic models occasionally wrap output in markdown fences or add a
    short preamble despite the strict-JSON instruction; we strip both.
    Falls back to an empty dict if the response can't be parsed — the
    builder treats missing keys as empty sections.
    """
    cleaned = text.strip()
    # Strip markdown code fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        # Otherwise grab the first {...} block — anchored greedy match.
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(0)
    try:
        return dict(json.loads(cleaned))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _build_brief(
    ticker: str,
    model: str,
    parsed: dict[str, Any],
    requested_concerns: list[str],
    *,
    raw: dict[str, Any],
) -> AiBrief:
    """Assemble an :class:`AiBrief` from the parsed JSON dict."""
    summary = str(parsed.get("summary") or "").strip()
    bull = _to_string_tuple(parsed.get("bull"))
    bear = _to_string_tuple(parsed.get("bear"))
    risks = _to_string_tuple(parsed.get("risks"))

    concern_payload = parsed.get("concerns") or {}
    findings: list[ConcernFinding] = []
    for concern in requested_concerns:
        entry = concern_payload.get(concern) if isinstance(concern_payload, dict) else None
        if isinstance(entry, dict):
            status = str(entry.get("status") or "unknown").lower()
            if status not in {"flagged", "clear", "unknown"}:
                status = "unknown"
            note = str(entry.get("note") or "")
        else:
            status = "unknown"
            note = ""
        findings.append(ConcernFinding(concern=concern, status=status, note=note))

    return AiBrief(
        ticker=ticker,
        generated_at=datetime.now(UTC),
        model=model,
        summary=summary,
        bull=bull,
        bear=bear,
        risks=risks,
        concerns=tuple(findings),
        raw=raw,
    )


def _to_string_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a JSON list-of-strings into a clean tuple, dropping empty entries."""
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


class StubBriefProvider:
    """Deterministic brief generator for offline development and testing."""

    def __init__(self, model: str = "stub-claude-sonnet-4-6") -> None:
        self._model = model

    async def write_brief(
        self,
        instrument: Instrument,
        snapshot: FundamentalsSnapshot,
        filings: list[Filing] | None = None,
        concerns: list[str] | None = None,
    ) -> AiBrief:
        """Return a deterministic, formula-generated brief for offline use."""
        active_concerns = list(concerns) if concerns is not None else list(DEFAULT_CONCERNS)
        summary = (
            f"{instrument.name} ({instrument.ticker}) — "
            f"{snapshot.gross_margin_pct:.0f}% gross margin business growing revenue "
            f"{snapshot.revenue_growth_pct:.1f}% with leverage at "
            f"{snapshot.net_debt_to_ebitda:.1f}x net debt/EBITDA."
        )
        bull = (
            f"Gross margin of {snapshot.gross_margin_pct:.1f}% suggests durable pricing power.",
            f"Revenue growth at {snapshot.revenue_growth_pct:+.1f}% above broad-market average.",
            f"Leverage at {snapshot.net_debt_to_ebitda:.2f}x net debt/EBITDA leaves balance-sheet headroom.",
        )
        bear = (
            f"FCF yield of {snapshot.fcf_yield_pct:.1f}% may be thin if growth slows.",
            f"Market cap of ${snapshot.market_cap_usd / 1e9:.1f}B exposes investors to multiple compression.",
            "Quality multiples typically compress in higher-rate regimes.",
        )
        risks: tuple[str, ...] = (
            "Customer or end-market concentration could reverse the growth trend.",
            "Macro / rate sensitivity in the valuation multiple.",
            "Watch for capex acceleration or working-capital deterioration.",
        )
        if filings:
            risks = (
                *risks,
                f"Most recent filing: {filings[0].form_type} on {filings[0].filed_at}.",
            )
        # Stub returns "unknown" for every requested concern — honest about
        # the fact that it isn't actually scanning anything.
        findings = tuple(
            ConcernFinding(concern=c, status="unknown", note="stub provider — no analysis performed")
            for c in active_concerns
        )

        return AiBrief(
            ticker=instrument.ticker,
            generated_at=datetime.now(UTC),
            model=self._model,
            summary=summary,
            bull=bull,
            bear=bear,
            risks=risks,
            concerns=findings,
            raw={"stub": True},
        )
