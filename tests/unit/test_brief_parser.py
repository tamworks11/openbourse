"""Tests for the Claude brief response parser.

We don't want to depend on the live Anthropic API for unit tests, so these
exercise the parser/builder helpers directly with hand-crafted JSON payloads
that mimic what the model returns.
"""

from __future__ import annotations

from openbourse.providers.claude import _build_brief, _parse_brief_json


class TestParseBriefJson:
    def test_strips_markdown_fences(self) -> None:
        text = '```json\n{"summary": "ok", "bull": ["x"]}\n```'
        parsed = _parse_brief_json(text)
        assert parsed["summary"] == "ok"
        assert parsed["bull"] == ["x"]

    def test_extracts_first_json_object_with_preamble(self) -> None:
        text = 'Here is the brief: {"summary": "hi", "bull": []}'
        assert _parse_brief_json(text)["summary"] == "hi"

    def test_returns_empty_dict_on_invalid_json(self) -> None:
        assert _parse_brief_json("totally not json") == {}

    def test_returns_empty_dict_on_partial_response(self) -> None:
        assert _parse_brief_json('{"summary": "incomplete') == {}


class TestBuildBrief:
    def test_builds_concerns_for_each_requested(self) -> None:
        parsed = {
            "summary": "Test Co",
            "bull": ["Strong growth"],
            "bear": ["Cyclical"],
            "risks": ["Supply chain"],
            "concerns": {
                "Customer concentration": {"status": "flagged", "note": "Top 3 = 40%"},
            },
        }
        brief = _build_brief(
            "TST",
            "claude-test",
            parsed,
            requested_concerns=[
                "Customer concentration",
                "Insider selling",
            ],
            raw={},
        )
        assert brief.summary == "Test Co"
        assert brief.bull == ("Strong growth",)
        assert brief.bear == ("Cyclical",)
        assert brief.risks == ("Supply chain",)
        # Two findings, one populated, one defaulted to "unknown".
        assert len(brief.concerns) == 2
        flagged = brief.concerns[0]
        assert flagged.status == "flagged"
        assert flagged.note == "Top 3 = 40%"
        unknown = brief.concerns[1]
        assert unknown.status == "unknown"
        assert unknown.note == ""

    def test_drops_non_string_bullets(self) -> None:
        parsed = {"bull": ["valid", 123, "", "  ", None, "also valid"]}
        brief = _build_brief("TST", "m", parsed, requested_concerns=[], raw={})
        assert brief.bull == ("valid", "also valid")

    def test_invalid_status_falls_back_to_unknown(self) -> None:
        parsed = {
            "concerns": {"Made up concern": {"status": "wibble", "note": "x"}},
        }
        brief = _build_brief("TST", "m", parsed, requested_concerns=["Made up concern"], raw={})
        assert brief.concerns[0].status == "unknown"

    def test_empty_response_yields_empty_sections(self) -> None:
        brief = _build_brief("TST", "m", {}, requested_concerns=[], raw={})
        assert brief.summary == ""
        assert brief.bull == ()
        assert brief.bear == ()
        assert brief.risks == ()
        assert brief.concerns == ()
