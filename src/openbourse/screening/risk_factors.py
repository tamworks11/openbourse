"""Extract the "Item 1A. Risk Factors" section from a 10-K HTML document.

EDGAR doesn't structurally tag sections - they're just bolded headings in
the HTML. We rely on three observations:

* Modern 10-Ks consistently use the heading "Item 1A. Risk Factors" (case
  varies; sometimes the period is missing; sometimes there's a non-breaking
  space between "Item" and "1A").
* The section ends at one of "Item 1B" (Unresolved Staff Comments),
  "Item 2." (Properties), or rarely "Item 1C" (Cybersecurity, post-2023).
* Filers occasionally split the heading across HTML tags, so we work on
  cleaned plain text rather than the DOM.

If we can't find the heading, return the whole text - better to scan
everything than fail. The downstream scanner is robust to noisy input.
"""

from __future__ import annotations

import re

from lxml import html as lxml_html

# Python's ``\s`` already matches NBSP under the default Unicode flag,
# so the patterns below cover both regular spaces and NBSPs without any
# explicit literal NBSP escape in the source.
_RISK_FACTORS_START = re.compile(
    r"item\s*1\s*a\.?\s+risk\s+factors",
    flags=re.IGNORECASE,
)
# End-of-section markers in priority order. We pick the earliest match
# AFTER the start position.
_RISK_FACTORS_END = re.compile(
    r"item\s*(?:1\s*b\.?|1\s*c\.?|2\.)\s+"
    r"(?:unresolved\s+staff\s+comments|cybersecurity|properties)",
    flags=re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    r"""Strip HTML tags and return cleaned UTF-8 text.

    Whitespace is collapsed but paragraph breaks are preserved as ``\n``,
    which keeps the regex anchors (which use ``\s+``) reliable across
    filers' wildly different markup styles.
    """
    if not html.strip():
        return ""
    tree = lxml_html.fromstring(html)
    # Drop scripts/styles before extracting text - modern 10-Ks include
    # MathJax-like script blocks that would otherwise pollute the output.
    for bad in tree.xpath("//script | //style | //noscript"):
        bad.getparent().remove(bad)
    raw = tree.text_content()
    # Collapse runs of in-line whitespace (incl. NBSP) but keep line breaks.
    # ``[^\S\n]+`` is "any whitespace that isn't a newline".
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_risk_factors(html_or_text: str) -> str:
    """Extract Item 1A from a 10-K HTML document (or pre-extracted text).

    Auto-detects whether the input is HTML or already-stripped text.
    Returns the empty string only if the input is empty; if the heading
    can't be found, falls back to the full document text on the theory
    that scanning too much is better than scanning nothing.
    """
    if not html_or_text:
        return ""
    text = html_to_text(html_or_text) if "<" in html_or_text else html_or_text

    # Most 10-Ks repeat "Item 1A. Risk Factors" once in the table of
    # contents and once at the actual section. We want the second match.
    starts = list(_RISK_FACTORS_START.finditer(text))
    if not starts:
        return text  # heading not found; return everything

    # Skip the TOC entry; if there's only one match, that's the heading
    # (some smaller filers omit the TOC).
    start_match = starts[1] if len(starts) >= 2 else starts[0]
    section_start = start_match.end()
    end_match = _RISK_FACTORS_END.search(text, section_start)
    section_end = end_match.start() if end_match else len(text)
    return text[section_start:section_end].strip()
