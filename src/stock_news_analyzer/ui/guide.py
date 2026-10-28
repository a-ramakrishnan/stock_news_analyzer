"""The Guide page's text: guide.md, split into its `## ` sections.

The same file is readable on GitHub before installing (linked from the README).
"""

import re
from pathlib import Path

GUIDE_FILE = Path(__file__).with_name("guide.md")


def slug(title: str) -> str:
    """'A daily routine' -> 'a-daily-routine', for links like /guide?section=a-daily-routine."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def sections(text: str | None = None) -> dict[str, str]:
    """{section title: its text}, in the file's order."""
    text = GUIDE_FILE.read_text(encoding="utf-8") if text is None else text
    out: dict[str, str] = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        out[title.strip()] = body.strip()
    return out
