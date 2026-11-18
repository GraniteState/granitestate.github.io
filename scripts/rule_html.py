#!/usr/bin/env python3
"""Read Office of Legislative Services rule HTML into heading bodies.

The snapshot stores Word HTML. Headings are paragraphs, not real h1–h3
tags, and a paragraph often is not closed before the next one opens.
This parser follows that shape: body paragraphs and table rows, with
appendix tables left out of the section text.

Adapted from the heading walker in GraniteState/adm-rules-data
scripts/nhrules.py at the commit pinned in sources/provenance.json.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

PREFIX_RE = r"[A-Z][A-Za-z]{0,8}(?:-[A-Za-z]{1,3})?"
NUMBER_RE = r"\d{2,4}(?:\.\d{1,3})?"
HEADING_RE = re.compile(
    rf"^(?:(CHAPTER|PART|SECTION)\s+)?({PREFIX_RE})\s+({NUMBER_RE})(?:\.(?=\s|$))?(?![0-9.(])\s*(.*)$",
    re.I,
)


def clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t\r\n]+", " ", text)
    return text.strip()


def decode_html(data: bytes) -> str:
    head = data[:6000].decode("latin1", errors="replace")
    meta = None
    match = re.search(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", head, re.I)
    if match:
        meta = match.group(1)
    for enc in (meta, "utf-8", "cp1252"):
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("cp1252", errors="replace")


def canonical_prefix(prefix: str, prefix_map: dict[str, str]) -> str:
    key = prefix.strip().casefold()
    if key in prefix_map:
        return prefix_map[key]
    parts = re.split(r"\s*-\s*", prefix.strip())
    out = []
    for part in parts:
        if len(part) == 1:
            out.append(part.upper())
        elif part.isupper() or part.islower():
            out.append(part.capitalize())
        else:
            out.append(part[:1].upper() + part[1:])
    return "-".join(out)


def parse_heading(text: str, pending_keyword: str | None, prefix_map: dict[str, str]) -> dict | None:
    match = HEADING_RE.match(text.strip())
    if not match:
        return None
    keyword = (match.group(1) or pending_keyword or "").lower()
    prefix = canonical_prefix(match.group(2), prefix_map)
    if prefix.casefold() not in prefix_map:
        return None
    number = match.group(3)
    rest = match.group(4) or ""
    if not keyword and "." not in number:
        if len(text) > 180 or re.search(r"\b(shall|means|must|pursuant|including)\b", text, re.I):
            return None
    if keyword == "chapter":
        level = "chapter"
    elif keyword == "part":
        level = "part"
    elif keyword == "section":
        level = "section"
    elif "." in number:
        level = "section"
    elif int(number) % 100 == 0:
        level = "chapter"
    else:
        level = "part"
    return {"id": f"{prefix} {number}", "prefix": prefix, "number": number, "level": level, "rest": rest}


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.in_body = False
        self.seen_body = False
        self.skip = 0
        self.buf: list[str] = []
        self.open_p = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.cell: list[str] = []
        self.row: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in ("script", "style"):
            self.skip += 1
            return
        if t == "body":
            self.in_body = True
            self.seen_body = True
            return
        if self.skip or not self.in_body:
            return
        if t == "br":
            self._text(" ")
            return
        if t == "table":
            self.table_depth += 1
            return
        if t == "tr" and self.table_depth == 1:
            self._flush_p()
            self.in_row = True
            self.row = []
            return
        if t in ("td", "th") and self.in_row and not self.in_cell:
            self.in_cell = True
            self.cell = []
            return
        if t == "p" and not self.in_cell and self.table_depth == 0:
            self._flush_p()
            self.open_p = True
            self.buf = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style") and self.skip:
            self.skip -= 1
            return
        if t == "body":
            self._flush_p()
            self._flush_row()
            self.in_body = False
            return
        if self.skip or not self.seen_body:
            return
        if t in ("td", "th") and self.in_cell:
            self.row.append(clean("".join(self.cell)))
            self.cell = []
            self.in_cell = False
            return
        if t == "tr" and self.in_row:
            self._flush_row()
            return
        if t == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.blocks.append({"type": "table_end"})
            return
        if t == "p" and self.open_p and not self.in_cell:
            self._flush_p()

    def handle_data(self, data: str) -> None:
        if self.skip or not self.in_body:
            return
        self._text(data)

    def _text(self, data: str) -> None:
        if self.in_cell:
            self.cell.append(data)
        elif self.open_p and self.table_depth == 0:
            self.buf.append(data)

    def _flush_p(self) -> None:
        if not self.open_p:
            return
        text = clean("".join(self.buf))
        self.open_p = False
        self.buf = []
        if text:
            self.blocks.append({"type": "p", "text": text})

    def _flush_row(self) -> None:
        if not self.in_row:
            return
        if self.in_cell:
            self.row.append(clean("".join(self.cell)))
            self.cell = []
            self.in_cell = False
        row = self.row
        self.in_row = False
        self.row = []
        if any(row):
            self.blocks.append({"type": "tr", "cells": row})


def blocks_from_html(html: str) -> list[dict]:
    parser = _BlockParser()
    parser.feed(html)
    parser.close()
    if parser.blocks:
        return parser.blocks
    if "<body" not in html.lower():
        return blocks_from_html("<html><body>" + html + "</body></html>")
    return []


def _is_appendix(rows: list[list[str]]) -> bool:
    head = " ".join(" ".join(row) for row in rows[:4]).lower()
    return "implement" in head and ("statute" in head or "rule" in head)


def extract_bodies(html: str, prefix_map: dict[str, str]) -> dict[str, list[str]]:
    """Paragraphs from each heading through the line before the next heading.

    A heading whose prefix is not in prefix_map stays in the previous body.
    An authority appendix table is omitted; the Authority list is built
    from the crosswalk instead.
    """
    spans: dict[str, list[list[str]]] = {}
    current: list[str] | None = None
    pending: str | None = None
    rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal rows
        if not rows:
            return
        taken = rows
        rows = []
        if _is_appendix(taken) or current is None:
            return
        for row in taken:
            line = " | ".join(cell for cell in row if cell)
            if line:
                current.append(line)

    for block in blocks_from_html(html):
        if block["type"] == "tr":
            rows.append(block["cells"])
            continue
        if block["type"] == "table_end":
            flush_table()
            continue
        flush_table()
        text = block["text"]
        if re.fullmatch(r"(CHAPTER|PART|SECTION)", text, flags=re.I):
            pending = text
            continue
        heading = parse_heading(text, pending, prefix_map)
        pending = None
        if heading:
            rule_id = heading["id"]
            current = []
            spans.setdefault(rule_id, []).append(current)
            current.append(text)
            continue
        if current is not None:
            current.append(text)
    flush_table()
    # A chapter file often repeats a heading in a short contents line and
    # again as the operative text. Keep the longer span.
    bodies: dict[str, list[str]] = {}
    for rule_id, chunks in spans.items():
        bodies[rule_id] = max(chunks, key=lambda chunk: sum(len(line) for line in chunk))
    return bodies


def self_test() -> None:
    html = """<html><body>
<p>CHAPTER Elec 100 DEFINITIONS</p>
<p>Statutory Authority: RSA 541-A:16, I(a)</p>
<p>PART Elec 101 PURPOSE</p>
<p>Elec 101.01 Purpose. The purpose is to set requirements.</p>
<p>Source. #10421, eff 9-25-13</p>
<p>Elec 101.02 Scope. (a) First.</p>
<p>(b) Second.</p>
<table>
<tr><td>Rule</td><td>Specific State or Federal Statutes the Rule Implements</td></tr>
<tr><td>Elec 101.01</td><td>RSA 319-C:2</td></tr>
</table>
<p>And 102 is not a heading.</p>
</body></html>"""
    bodies = extract_bodies(html, {"elec": "Elec"})
    assert list(bodies) == ["Elec 100", "Elec 101", "Elec 101.01", "Elec 101.02"], list(bodies)
    assert any(line.startswith("Statutory Authority") for line in bodies["Elec 100"])
    assert any(line.startswith("Source.") for line in bodies["Elec 101.01"])
    assert not any("Purpose" in line for line in bodies["Elec 101.02"])
    assert any(line.startswith("(b)") for line in bodies["Elec 101.02"])
    assert all("319-C" not in line for line in bodies["Elec 101.02"])
    assert any("And 102" in line for line in bodies["Elec 101.02"])
    print("rule_html self-test ok")


if __name__ == "__main__":
    self_test()
