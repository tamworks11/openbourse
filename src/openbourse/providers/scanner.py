"""Concern scanner — pulls filing text and asks Claude for verbatim evidence.

The Claude implementation feeds the Item 1A. Risk Factors section into a
strict-JSON prompt, asking the model to mark each concern as ``flagged``,
``clear``, or ``unknown`` and supply a verbatim quote when ``flagged``.
Quotes are validated post-hoc — if the returned ``note`` doesn't actually
appear in the filing text, we drop it (the concern stays flagged but the
note is blanked) so users can trust that quotes are real.

The stub implementation is deliberately uninformative: it returns
``unknown`` for every concern. This keeps tests deterministic and stops
the offline UX from claiming evidence it doesn't have.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from openbourse.domain import ConcernFinding

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import AsyncAnthropic

# Cap how much of the filing we send. Most 10-Ks have Risk Factors of
# 30k-80k tokens; truncating to ~60k chars (~15k tokens) keeps cost
# bounded while preserving the parts that contain the bulk of distinct
# risks. Filings tend to lead with the most material risks anyway.
MAX_FILING_CHARS = 60_000

SCANNER_SYSTEM_PROMPT = (
    "You are a forensic accounting analyst examining 10-K Risk Factors. "
    "For each concern the user supplies, find direct evidence in the "
    "filing text. Quote the filing verbatim — do not paraphrase. If the "
    "filing doesn't address the concern, return status=unknown. Only "
    "return status=clear when the filing explicitly states the concern "
    "doesn't apply. Reply in strict JSON; no preamble or markdown."
)

SCANNER_SCHEMA_INSTRUCTIONS = (
    "Return a JSON object: {\n"
    '  "<concern verbatim>": {"status": "flagged"|"clear"|"unknown", '
    '"quote": "<verbatim quote from filing, or empty>"},\n'
    "  ...\n"
    "}\n"
    "Include every concern the user listed. Quotes must be 1-3 sentences, "
    "copied character-for-character from the filing text."
)


class StubConcernScanner:
    """Deterministic scanner that returns ``unknown`` for every concern."""

    async def scan(
        self,
        *,
        ticker: str,
        filing_text: str,
        concerns: list[str],
    ) -> list[ConcernFinding]:
        """Return one ``unknown`` finding per concern. ``filing_text`` is ignored."""
        return [
            ConcernFinding(
                concern=concern,
                status="unknown",
                note="stub scanner — no analysis performed",
            )
            for concern in concerns
        ]


class ClaudeConcernScanner:
    """Claude-backed scanner that searches filing text for verbatim evidence."""

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

    async def scan(
        self,
        *,
        ticker: str,
        filing_text: str,
        concerns: list[str],
    ) -> list[ConcernFinding]:
        """Render the prompt, call Claude, and validate the returned quotes."""
        if not concerns:
            return []
        if not filing_text.strip():
            # Without filing text, we genuinely don't know — return
            # unknowns instead of paying for an empty scan.
            return [
                ConcernFinding(concern=c, status="unknown", note="no filing text available")
                for c in concerns
            ]

        truncated = filing_text[:MAX_FILING_CHARS]
        user_text = _render_user_message(ticker, truncated, concerns)
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SCANNER_SYSTEM_PROMPT + "\n\n" + SCANNER_SCHEMA_INSTRUCTIONS,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
        from anthropic.types import TextBlock

        text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
        parsed = _parse_scan_json(text)
        return _build_findings(parsed, concerns, filing_text=truncated)


def _render_user_message(ticker: str, filing_text: str, concerns: list[str]) -> str:
    """Build the user-side prompt sent to Claude."""
    concern_lines = "\n".join(f"- {c}" for c in concerns)
    return (
        f"Ticker: {ticker}\n\n"
        f"Concerns to evaluate against the filing text below:\n{concern_lines}\n\n"
        f"--- BEGIN FILING TEXT ---\n{filing_text}\n--- END FILING TEXT ---"
    )


def _parse_scan_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of Claude's reply. Tolerates markdown fences."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(0)
    try:
        return dict(json.loads(cleaned))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _build_findings(
    parsed: dict[str, Any],
    concerns: list[str],
    *,
    filing_text: str,
) -> list[ConcernFinding]:
    """Turn the parsed dict into a list of :class:`ConcernFinding`.

    Any quote that doesn't actually appear in ``filing_text`` is dropped —
    we'd rather show "flagged with no quote" than risk fabricated quotes.
    Whitespace differences are normalized before the substring check
    because the model sometimes collapses or expands spacing.
    """
    normalized_filing = _normalize_whitespace(filing_text)
    findings: list[ConcernFinding] = []
    for concern in concerns:
        entry = parsed.get(concern) if isinstance(parsed, dict) else None
        if not isinstance(entry, dict):
            findings.append(ConcernFinding(concern=concern, status="unknown", note=""))
            continue
        status = str(entry.get("status") or "unknown").lower()
        if status not in {"flagged", "clear", "unknown"}:
            status = "unknown"
        quote = str(entry.get("quote") or "").strip()
        # Validate verbatim quote — drop it if the model paraphrased.
        if quote and _normalize_whitespace(quote) not in normalized_filing:
            quote = ""
        findings.append(ConcernFinding(concern=concern, status=status, note=quote))
    return findings


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including line breaks) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()
