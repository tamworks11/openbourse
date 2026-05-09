"""Read ticker lists from text files or the bundled defaults.

The file format is intentionally tiny: one ticker per line, ``#`` introduces a
comment to end-of-line, blank lines ignored. This makes the lists easy to
maintain in version control, paste into Discord, or generate from any other
tool.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

DEFAULT_BUNDLED_LIST = "popular_us"


def load_tickers(path: Path | str) -> list[str]:
    """Read tickers from a path on disk.

    Lines beginning with ``#`` (after trimming whitespace) are treated as
    comments. A trailing inline comment (``AAPL  # note``) is also stripped.
    Tickers are uppercased and de-duplicated while preserving first-seen
    order — handy when concatenating multiple lists.
    """
    text = Path(path).read_text(encoding="utf-8")
    return _parse_text(text)


def load_bundled_list(name: str = DEFAULT_BUNDLED_LIST) -> list[str]:
    """Load one of the lists shipped under ``src/openbourse/data/lists/``.

    Pass ``"popular_us"`` (the default) to grab the curated set of well-known
    US tickers shipped with the package.
    """
    text = (
        resources.files("openbourse.data.lists").joinpath(f"{name}.txt").read_text(encoding="utf-8")
    )
    return _parse_text(text)


def _parse_text(text: str) -> list[str]:
    """Strip comments/blanks and dedupe; preserve first-seen ordering."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        ticker = line.upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out
