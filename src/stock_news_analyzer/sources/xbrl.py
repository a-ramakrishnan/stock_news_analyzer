"""XBRL results files: the figures of a results filing, each tagged with what it is.

Listed companies file their results in XBRL as well as PDF. Each figure is a fact: a tag
from the taxonomy (e.g. RevenueFromOperations), the context it belongs to (which period,
consolidated or standalone) and its value, so no text has to be read.
"""

import xml.etree.ElementTree as ET


def facts(content: bytes) -> list[tuple[str, str, str]]:
    """(tag without its namespace, context, value) of every fact that has a value."""
    root = ET.fromstring(content)
    out = []
    for el in root.iter():
        context = el.get("contextRef")
        if context is None or not (el.text or "").strip():
            continue
        out.append((el.tag.rsplit("}", 1)[-1], context, el.text.strip()))
    return out


def contexts(content: bytes) -> dict[str, str]:
    """{context id: its period and dimensions as text}, e.g. 'OneD': '2026-04-01..2026-06-30'."""
    root = ET.fromstring(content)
    out = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "context" or not el.get("id"):
            continue
        dates = [
            d.text
            for d in el.iter()
            if d.tag.rsplit("}", 1)[-1] in ("startDate", "endDate", "instant")
        ]
        members = [m.text for m in el.iter() if m.tag.rsplit("}", 1)[-1] == "explicitMember"]
        out[el.get("id")] = "..".join(d for d in dates if d) + (f" {members}" if members else "")
    return out
