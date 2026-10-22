"""Small text helpers shared by sources."""

import html
import re


def clean(text: str | None) -> str:
    """Source text has stray HTML (<BR>), entities and doubled quotes; make it plain.

    NUL characters, which PostgreSQL text columns reject, are dropped.
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = re.sub(r"<[^>]+>", " ", html.unescape(text)).replace("''", "'")
    return " ".join(text.split())
