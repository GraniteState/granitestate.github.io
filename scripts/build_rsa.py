#!/usr/bin/env python3
"""Build hyperlinked RSA pages from the General Court HTML scrape.

Standard library only. The HTML is not stored in this repository. Pass the
``rsa_html`` directory from a checkout of GraniteState/nh-rsa-data:

  python3 scripts/build_rsa.py --source /path/to/rsa_html
  python3 scripts/build_rsa.py --self-test

The default scope is every title whose table-of-contents heading contains
"election". ``--all`` builds every title. ``--titles LXIII`` builds one
title. Chaptered-law text is not fetched; see rsa/GC_AUGMENTATION.md.

Address scheme
--------------
A citation ``RSA 659:21`` has chapter ``659`` and section ``21``.
A letter on a chapter stays uppercase (``662-A``). A letter on a section
stays lowercase (``20-a``). The colon becomes a hyphen in the section slug.

  identifier   https://granitestate.github.io/rsa/659/659-21
  HTML         /rsa/659/659-21.html
  JSON-LD      /rsa/659/659-21.jsonld

Chapter ``659`` is ``/rsa/659/`` (index.html and index.jsonld).
Title ``LXIII`` is ``/rsa/title/LXIII/``. GitHub Pages does not rewrite a
bare section identifier to the HTML file; agents append ``.jsonld``, and
the pages link to ``.html``.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from kb_common import CONTEXT_URI, ROOT, SITE, dump_json

SOURCE_REPO = "GraniteState/nh-rsa-data"
RSA_DIR = ROOT / "rsa"
SCHEME_ID = SITE + "rsa/scheme"

# Explicit mappings. A link is written only when the catchline still
# contains catchline_contains. The KB records do not point back.
KB_LINKS = [
    {
        "citation": "662:1",
        "catchline_contains": "U.S. Representative",
        "targets": [
            (SITE + "kb/districts/2022/office/us-house", "U.S. House office"),
            (SITE + "kb/districts/2022/plan/2022-us_house-norelli", "2022 U.S. House plan"),
        ],
        "why": (
            "Catchline is U.S. Representative Districts. The 2022 U.S. House plan "
            "note names RSA 662:1 and says the statute text was not amended, so the "
            "boundaries in force come from the court order rather than this section."
        ),
    },
    {
        "citation": "662:2",
        "catchline_contains": "Councilor",
        "targets": [
            (SITE + "kb/districts/2022/office/executive-council", "Executive Council office"),
            (SITE + "kb/districts/2022/plan/2022-executive_council-sb241", "2022 Executive Council plan"),
        ],
        "why": "Catchline is Councilor Districts. The plan citation is Laws 2022, 46:1 (RSA 662:2).",
    },
    {
        "citation": "662:3",
        "catchline_contains": "State Senate",
        "targets": [
            (SITE + "kb/districts/2022/office/nh-senate", "State Senate office"),
            (SITE + "kb/districts/2022/plan/2022-nh_senate-sb240", "2022 State Senate plan"),
        ],
        "why": "Catchline is State Senate Districts. The plan citation is Laws 2022, 45:1 (RSA 662:3).",
    },
    {
        "citation": "662:4",
        "catchline_contains": "County Commissioner",
        "targets": [
            (SITE + "kb/districts/2022/office/county-commissioner", "county commissioner office"),
            (SITE + "kb/districts/2022/plan/2022-county_commissioner-hb54", "2022 county commissioner plan"),
            (
                SITE + "kb/districts/2022/plan/2023-county_commissioner-hb75-strafford",
                "2023 Strafford county commissioner plan",
            ),
        ],
        "why": (
            "Catchline is County Commissioner Districts. The plan citations are "
            "Laws 2022, 4:1 (RSA 662:4) and Laws 2023, 177:2, 3 (RSA 662:4, IX)."
        ),
    },
    {
        "citation": "662:5",
        "catchline_contains": "State Representative",
        "targets": [
            (SITE + "kb/districts/2022/office/nh-house", "State House office"),
            (SITE + "kb/districts/2022/plan/2022-nh_house-hb50", "2022 State House plan"),
        ],
        "why": "Catchline is State Representative Districts. The plan citation is Laws 2022, 9:1 (RSA 662:5).",
    },
]

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_ROMAN_VALUES = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def int_to_roman(number: int) -> str:
    parts = []
    for value, glyph in _ROMAN_VALUES:
        while number >= value:
            parts.append(glyph)
            number -= value
    return "".join(parts)


def roman_to_int(token: str) -> int | None:
    return _roman_value(token)


def _roman_value(token: str) -> int | None:
    token = token.upper()
    total = 0
    i = 0
    glyphs = {glyph: value for value, glyph in _ROMAN_VALUES}
    # longest glyph first
    ordered = sorted(glyphs, key=len, reverse=True)
    while i < len(token):
        for glyph in ordered:
            if token.startswith(glyph, i):
                total += glyphs[glyph]
                i += len(glyph)
                break
        else:
            return None
    if total <= 0 or int_to_roman(total) != token:
        return None
    return total


ROMAN = "|".join(int_to_roman(n) for n in range(40, 0, -1))
CHAP = r"\d+(?:-[A-Za-z])?"
SECT = r"\d+(?:-[A-Za-z])?"
CITE = rf"{CHAP}:{SECT}"
# A session year is "1979, 436:" — four digits, a comma, then a chapter number.
# A date year is "July 1, 1979" and is not followed by a chapter number.
YEAR_START = re.compile(r"(?<!\d)(\d{4}),\s+(?=\d+:)")
# A session-law section is "1", "20-a", a printed range "1-3", or "1(53)".
SESSION_ATOM = r"\d+(?:-[A-Za-z]|-\d+)?(?:\(\d+\))?"
CLAUSE_RE = re.compile(
    rf"^(\d+):((?:{SESSION_ATOM})(?:\s*,\s*{SESSION_ATOM})*)(?:\s*,\s*|\s+)?(.*)$"
)
DATE_RE = re.compile(
    r"^([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})(?:\s*,)?(?:\s+at\s+(.+))?$",
    re.I,
)
HEADING_CITE = re.compile(
    rf"({CHAP}):({SECT})(?:\s+to\s+({CHAP}):({SECT}))?",
    re.I,
)

STYLE = """
:root { color-scheme: light dark; }
body {
  font-family: "Iowan Old Style", Palatino, Georgia, serif;
  line-height: 1.5;
  max-width: 46rem;
  margin: 2rem auto;
  padding: 0 1.25rem 3rem;
}
h1 { font-weight: 600; letter-spacing: -0.02em; font-size: 1.6rem; }
h2 { font-size: 1.15rem; margin-top: 1.6rem; }
a { color: inherit; }
a:hover, a:focus { text-decoration-thickness: 2px; }
.skip {
  position: absolute;
  left: -999px;
  top: 0;
}
.skip:focus { left: 1rem; background: Canvas; padding: 0.3rem 0.6rem; }
nav { font-size: 0.95rem; }
.statute { white-space: pre-wrap; font-family: inherit; }
.catch { font-weight: 600; }
aside, footer { margin-top: 1.5rem; }
footer, .note { font-size: 0.95rem; }
ul { padding-left: 1.2rem; }
li { margin: 0.25rem 0; }
"""


def fix_windows_chars(text: str) -> str:
    """Map C1 controls produced by Windows-1252 numeric entities.

    The scrape writes an en dash as ``&#150;``. In HTML that is U+0096.
    The pages display the Windows-1252 character, U+2013. The same applies
    to the other bytes in 0x80-0x9F.
    """
    out = []
    for ch in text:
        code = ord(ch)
        if 0x80 <= code <= 0x9F:
            out.append(bytes([code]).decode("cp1252"))
        else:
            out.append(ch)
    return "".join(out)


def norm(text: str) -> str:
    text = fix_windows_chars(text).replace("\xa0", " ")
    return " ".join(text.split())


def norm_chapter(token: str) -> str:
    match = re.fullmatch(r"(\d+)(?:-([A-Za-z]))?", token.strip())
    if not match:
        raise ValueError(f"not a chapter: {token!r}")
    number = str(int(match.group(1)))
    if match.group(2):
        return f"{number}-{match.group(2).upper()}"
    return number


def norm_section(token: str) -> str:
    match = re.fullmatch(r"(\d+)(?:-([A-Za-z]))?", token.strip())
    if not match:
        raise ValueError(f"not a section: {token!r}")
    number = str(int(match.group(1)))
    if match.group(2):
        return f"{number}-{match.group(2).lower()}"
    return number


def session_section(token: str) -> str:
    """Keep a printed session-law range such as 1-3 as one token."""
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token.strip())
    if match:
        return f"{int(match.group(1))}-{int(match.group(2))}"
    return norm_section(token)


def norm_cite(chapter: str, section: str) -> str:
    return f"{norm_chapter(chapter)}:{norm_section(section)}"


def chapter_key(chapter: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)(?:-([A-Za-z]))?", chapter)
    if not match:
        raise ValueError(chapter)
    letter = match.group(2).upper() if match.group(2) else ""
    return (int(match.group(1)), letter)


def section_sort_key(citation: str) -> tuple:
    chapter, section = citation.split(":", 1)
    match = re.fullmatch(r"(\d+)(?:-([a-z]))?", section)
    letter = match.group(2) or ""
    return (chapter_key(chapter), int(match.group(1)), letter)


def section_slug(citation: str) -> str:
    chapter, section = citation.split(":", 1)
    return f"{chapter}-{section}"


def heading_citations(text: str) -> list[str]:
    """Citations named by a section heading, expanding a closed 'to' range."""
    found: list[str] = []
    for match in HEADING_CITE.finditer(text):
        if match.group(3):
            found.extend(
                expand_range(match.group(1), match.group(2), match.group(3), match.group(4))
            )
        else:
            found.append(norm_cite(match.group(1), match.group(2)))
    deduped = []
    for citation in found:
        if citation not in deduped:
            deduped.append(citation)
    return deduped


def expand_range(ch1: str, sec1: str, ch2: str, sec2: str) -> list[str]:
    left = norm_cite(ch1, sec1)
    right = norm_cite(ch2, sec2)
    chapter = norm_chapter(ch1)
    if norm_chapter(ch2) != chapter:
        return [left, right]
    a = re.fullmatch(r"(\d+)(?:-([a-z]))?", norm_section(sec1))
    b = re.fullmatch(r"(\d+)(?:-([a-z]))?", norm_section(sec2))
    if a.group(1) == b.group(1) and a.group(2) and b.group(2):
        start, end = ord(a.group(2)), ord(b.group(2))
        if 0 <= end - start <= 26:
            return [f"{chapter}:{a.group(1)}-{chr(code)}" for code in range(start, end + 1)]
        return [left, right]
    if not a.group(2) and not b.group(2):
        start, end = int(a.group(1)), int(b.group(1))
        if 0 <= end - start <= 100:
            return [f"{chapter}:{number}" for number in range(start, end + 1)]
    return [left, right]


def parse_effective(phrase: str) -> tuple[str | None, str]:
    """Return (ISO date or None, the original phrase)."""
    text = phrase.strip().rstrip(".")
    match = DATE_RE.match(text)
    if not match:
        return None, text
    month = MONTHS.get(match.group(1).lower())
    if month is None:
        return None, text
    day = int(match.group(2))
    year = int(match.group(3))
    try:
        iso = date(year, month, day).isoformat()
    except ValueError:
        return None, text
    if match.group(4):
        text = f"{match.group(1).rstrip('.').title() if False else text}"
        # Keep the printed phrase, including the time, as effectiveText.
        return iso, text
    return iso, text


def parse_session_laws(text: str) -> list[dict]:
    """Parse session-law citations. Unparsed text is kept and not filled in."""
    if not text:
        return []
    body = re.sub(r"^Source\.\s*", "", norm(text)).strip()
    matches = list(YEAR_START.finditer(body))
    laws = []
    for index, match in enumerate(matches):
        year = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        raw_group = body[match.start() : end].strip().rstrip(".")
        clause_body = body[match.end() : end].strip().rstrip(".")
        clauses = [part.strip() for part in re.split(r";\s*", clause_body) if part.strip()]
        if not clauses:
            laws.append({"citation": raw_group, "sessionYear": year, "note": "No chapter:section followed this year."})
            continue
        for clause in clauses:
            clause = clause.strip().rstrip(".").strip(" –—-").strip().rstrip(".")
            parsed = CLAUSE_RE.match(clause)
            item = {"citation": f"{year}, {clause}", "sessionYear": year}
            if not parsed or not parsed.group(2):
                item["note"] = "The clause did not match year, chapter:section."
                laws.append(item)
                continue
            sections = []
            parentheses = []
            for part in re.split(r"\s*,\s*", parsed.group(2)):
                marked = re.fullmatch(r"(\d+(?:-[A-Za-z]|-\d+)?)\((\d+)\)", part)
                if marked:
                    sections.append(session_section(marked.group(1)))
                    parentheses.append(f"({marked.group(2)})")
                else:
                    sections.append(session_section(part))
            item["sessionChapter"] = str(int(parsed.group(1)))
            item["sessionSection"] = sections
            remainder = (parsed.group(3) or "").strip().rstrip(".")
            if parentheses:
                prefix = " ".join(parentheses)
                remainder = f"{prefix}, {remainder}".strip(" ,") if remainder else prefix
            if remainder:
                eff = re.search(r"(?:,\s*)?eff\.\s+(.+)$", remainder, re.I)
                if eff:
                    prefix = remainder[: eff.start()].strip(" ,")
                    iso, printed = parse_effective(eff.group(1))
                    item["effectiveText"] = printed
                    if iso:
                        item["effectiveDate"] = iso
                    if prefix:
                        item["sessionRemainder"] = prefix
                else:
                    item["sessionRemainder"] = remainder
            laws.append(item)
    return laws


def parse_repeal_laws(catchline: str) -> list[dict]:
    match = re.search(r"Repealed by\s+(.+)$", catchline, re.I)
    if not match:
        return []
    return parse_session_laws(match.group(1))


@dataclass
class Section:
    citation: str
    chapter: str
    title: str
    catchline: str
    part_heading: str
    lines: list[str]
    history_note: str
    session_laws: list[dict]
    repealed: bool
    source_file: str
    chapter_name: str = ""
    combined: list[str] = field(default_factory=list)
    paragraphs: set[str] = field(default_factory=set)
    related: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return section_slug(self.citation)

    @property
    def identifier(self) -> str:
        return f"{SITE}rsa/{self.chapter}/{self.slug}"


@dataclass
class Chapter:
    slug: str
    title: str
    name: str
    sections: list[str] = field(default_factory=list)
    toc_entries: list[tuple[str, str]] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        return f"{SITE}rsa/{self.slug}"


@dataclass
class Title:
    roman: str
    name: str
    start: str
    end: str
    repealed: bool
    chapters: list[str] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        return f"{SITE}rsa/title/{self.roman}"


@dataclass
class Unresolved:
    section: str
    text: str
    reason: str


@dataclass
class Catalog:
    titles: dict[str, Title]
    chapters: dict[str, Chapter]
    sections: dict[str, Section]
    ranges: list[Title]
    counts: dict[str, int] = field(default_factory=lambda: {"internal": 0, "external": 0, "unresolved": 0})
    unresolved: list[Unresolved] = field(default_factory=list)

    def title_for_chapter(self, chapter: str) -> Title | None:
        key = chapter_key(chapter)
        found = [title for title in self.ranges if chapter_key(title.start) <= key <= chapter_key(title.end)]
        if len(found) > 1:
            raise SystemExit(f"chapter {chapter} is in more than one title: {[t.roman for t in found]}")
        return found[0] if found else None


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.h3 = ""
        self.catchline = ""
        self.lines: list[str] = []
        self.history = ""
        self._capture: list[str] | None = None
        self._capture_kind = ""
        self._line: list[str] = []
        self._in_code = False
        self._in_source = False
        self._source: list[str] = []
        self._in_table = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self._start(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._start(tag)
        if tag.lower() in {"br", "meta", "link", "img"}:
            self._end(tag)

    def _start(self, tag: str) -> None:
        tag = tag.lower()
        self.stack.append(tag)
        if tag in {"h1", "h2", "h3"}:
            self._capture = []
            self._capture_kind = tag
        elif tag == "b" and not self.catchline and not self._in_source and not self._in_code:
            self._capture = []
            self._capture_kind = "b"
        elif tag == "codesect":
            self._in_code = True
            self._line = []
        elif tag == "sourcenote":
            self._in_source = True
            self._source = []
        elif tag == "br":
            if self._capture is not None and self._capture_kind in {"h1", "h2", "h3"}:
                self._capture.append(" ")
            elif self._in_table:
                self._cell.append(" ")
            elif self._in_code:
                self._finish_line()
        elif tag == "table" and self._in_code:
            self._finish_line()
            self._in_table = True
            self._rows = []
            self._row = []
            self._cell = []
        elif tag == "td" and self._in_table:
            self._cell = []
        elif tag in {"p", "center"} and self._in_code and not self._in_table:
            self._finish_line()

    def handle_endtag(self, tag: str) -> None:
        self._end(tag)

    def _end(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3"} and self._capture_kind == tag and self._capture is not None:
            text = norm("".join(self._capture))
            if tag == "h1":
                self.h1.append(text)
            elif tag == "h2":
                self.h2.append(text)
            else:
                self.h3 = text
            self._capture = None
            self._capture_kind = ""
        elif tag == "b" and self._capture_kind == "b" and self._capture is not None:
            self.catchline = norm("".join(self._capture))
            self._capture = None
            self._capture_kind = ""
        elif tag == "codesect":
            self._finish_line()
            self._in_code = False
        elif tag == "sourcenote":
            self._in_source = False
            self.history = norm("".join(self._source))
        elif tag == "td" and self._in_table:
            self._row.append(norm("".join(self._cell)))
            self._cell = []
        elif tag == "tr" and self._in_table:
            if any(self._row):
                self._rows.append(self._row)
            self._row = []
        elif tag == "table" and self._in_table:
            for row in self._rows:
                cells = [cell for cell in row if cell]
                if cells:
                    self.lines.append(" ".join(cells))
            self._in_table = False
            self._rows = []
        elif tag in {"p", "center"} and self._in_code and not self._in_table:
            self._finish_line()
        if tag in self.stack:
            while self.stack:
                if self.stack.pop() == tag:
                    break

    def handle_data(self, data: str) -> None:
        data = fix_windows_chars(data)
        if self._capture is not None:
            self._capture.append(data)
        if self._in_table and self.stack and self.stack[-1] == "td":
            self._cell.append(data)
        elif self._in_code and not self._in_table:
            self._line.append(data)
        elif self._in_source:
            self._source.append(data)

    def _finish_line(self) -> None:
        text = norm("".join(self._line))
        self._line = []
        if text:
            self.lines.append(text)


def paragraph_labels(lines: list[str]) -> set[str]:
    labels = set()
    pattern = re.compile(rf"^({ROMAN})\.\s+\S")
    for line in lines:
        match = pattern.match(line)
        if match and roman_to_int(match.group(1)):
            labels.add(match.group(1).upper())
    return labels


def strip_trailing_dash(text: str) -> str:
    return re.sub(r"\s+[–—-]\s*$", "", text).strip()


def pref_label(catchline: str, citation: str) -> str:
    text = strip_trailing_dash(catchline) or citation
    if text.upper().startswith("RSA "):
        return text
    return "RSA " + text


def definition_of(catchline: str, citation: str) -> str:
    text = strip_trailing_dash(catchline)
    prefix = citation
    if text.upper().startswith(prefix.upper()):
        rest = text[len(prefix) :].strip(" .")
        if rest:
            return rest if rest.endswith(".") else rest
    return text


def rsa_pin() -> dict:
    """The nh-rsa-data commit this site is built from. Bump it in provenance.json."""
    doc = json.loads((ROOT / "sources/provenance.json").read_text(encoding="utf-8"))
    pin = doc.get("rsa")
    if not isinstance(pin, dict) or not pin.get("commit"):
        raise SystemExit("sources/provenance.json has no rsa.commit")
    return pin


def blob_url(path_under_rsa_html: str) -> str:
    pin = rsa_pin()
    commit = pin["commit"]
    rel = path_under_rsa_html.lstrip("/")
    return f"https://github.com/{SOURCE_REPO}/blob/{commit}/rsa_html/{rel}"


def section_blob(section: Section) -> str:
    path = Path(section.source_file) if section.source_file else None
    if path is not None and "rsa_html" in path.parts:
        index = path.parts.index("rsa_html")
        return blob_url("/".join(path.parts[index + 1 :]))
    return blob_url(f"{section.title}/{section.chapter}/{section.slug}.htm")


def provenance_line(blob: str) -> str:
    pin = rsa_pin()
    commit = pin["commit"]
    retrieved = pin.get("commit_date") or pin.get("retrieved") or ""
    when = f", retrieved {retrieved}" if retrieved else ""
    return (
        f"Source: NH General Court RSA HTML{when}, nh-rsa-data@{commit[:12]}. "
        f'<a href="{html.escape(blob, quote=True)}">Raw HTML in nh-rsa-data</a>.'
    )


def html_href_for(citation: str, catalog: Catalog, paragraph: str | None) -> str | None:
    """Return an on-site href, or None when this build has no such section."""
    section = catalog.sections.get(citation)
    if section is None:
        return None
    href = f"/rsa/{section.chapter}/{section.slug}.html"
    if paragraph:
        if paragraph not in section.paragraphs:
            return None
        href += f"#p-{paragraph}"
    return href


def record_unresolved(catalog: Catalog, section: str, text: str, reason: str) -> None:
    catalog.unresolved.append(Unresolved(section, text, reason))
    catalog.counts["unresolved"] += 1


def linkify(text: str, here: str, catalog: Catalog) -> str:
    pattern = citation_pattern()
    pieces = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() < cursor:
            continue
        pieces.append(html.escape(text[cursor : match.start()]))
        pieces.append(render_citation(match, text, here, catalog))
        cursor = match.end()
    pieces.append(html.escape(text[cursor:]))
    return "".join(pieces)


def citation_pattern() -> re.Pattern[str]:
    # Longer forms first. Python tries alternatives left to right.
    return re.compile(
        rf"""
        (?P<range>
            (?P<rword>RSA\s+|sections?\s+)
            (?P<c1>{CITE})
            (?P<p1>\s*,\s*(?P<para1>{ROMAN})(?:\([A-Za-z0-9]+\))?)?
            \s+(?:through|to|[-–—])\s+
            (?P<c2>{CITE}|(?P<same>\d+(?:-[A-Za-z])?))
            (?P<p2>\s*,\s*(?P<para2>{ROMAN})(?:\([A-Za-z0-9]+\))?)?
        )
        |
        (?P<section>
            (?<![A-Za-z])RSA\s+
            (?P<sc>{CITE})
            (?P<sp>\s*,\s*(?P<spara>{ROMAN})(?:\([A-Za-z0-9]+\))?)?
        )
        |
        (?P<chapter>
            (?<![A-Za-z])RSA\s+
            (?P<ch>{CHAP})
            (?![:\w-])
        )
        |
        (?P<bare>
            (?<![A-Za-z])sections?\s+
            (?P<bc>{CITE})
            (?P<bp>\s*,\s*(?P<bpara>{ROMAN})(?:\([A-Za-z0-9]+\))?)?
        )
        |
        (?P<paras>
            (?<!sub)(?<![A-Za-z])paragraphs?\s+
            (?P<body>{ROMAN}(?:\([A-Za-z0-9]+\))?(?:\s*(?:,|and|or|through|to)\s*{ROMAN}(?:\([A-Za-z0-9]+\))?)*)
            (?:\s+of\s+(?:this\s+section|(?:RSA\s+|section\s+)(?P<pc>{CITE})))?
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )


def render_citation(match: re.Match[str], text: str, here: str, catalog: Catalog) -> str:
    raw = match.group(0)
    if match.group("range"):
        return render_range(match, here, catalog)
    if match.group("section") or match.group("bare"):
        cite = normalize_match_cite(match.group("sc") or match.group("bc"))
        para = (match.group("spara") or match.group("bpara") or "").upper() or None
        return anchor_cite(raw, cite, para, here, catalog, paragraph_in_text=bool(para))
    if match.group("chapter"):
        return anchor_chapter(raw, norm_chapter(match.group("ch")), here, catalog)
    if match.group("paras"):
        return render_paragraphs(match, here, catalog)
    return html.escape(raw)


def normalize_match_cite(token: str) -> str:
    chapter, section = token.split(":", 1)
    return norm_cite(chapter, section)


def render_range(match: re.Match[str], here: str, catalog: Catalog) -> str:
    first = normalize_match_cite(match.group("c1"))
    second_token = match.group("c2")
    if match.group("same") and ":" not in second_token:
        second = norm_cite(first.split(":", 1)[0], second_token)
    else:
        second = normalize_match_cite(second_token)
    para1 = (match.group("para1") or "").upper() or None
    para2 = (match.group("para2") or "").upper() or None
    # Rebuild around the two citation tokens so "through" stays plain text.
    word = match.group("rword")
    left = match.group("c1") + (match.group("p1") or "")
    right = match.group("c2") + (match.group("p2") or "")
    prefix = word
    middle_start = match.start("c1") + len(left) - match.start()
    # Use the raw match slices.
    raw = match.group(0)
    left_at = raw.lower().find(left.lower())
    right_at = raw.lower().rfind(right.lower())
    if left_at < 0 or right_at < 0 or right_at < left_at:
        return html.escape(raw)
    return (
        html.escape(raw[:left_at])
        + anchor_cite(raw[left_at : left_at + len(left)], first, para1, here, catalog, paragraph_in_text=bool(para1))
        + html.escape(raw[left_at + len(left) : right_at])
        + anchor_cite(raw[right_at : right_at + len(right)], second, para2, here, catalog, paragraph_in_text=bool(para2))
        + html.escape(raw[right_at + len(right) :])
    )


def render_paragraphs(match: re.Match[str], here: str, catalog: Catalog) -> str:
    target = here
    if match.group("pc"):
        target = normalize_match_cite(match.group("pc"))
    body = match.group("body")
    tokens = re.findall(rf"{ROMAN}(?:\([A-Za-z0-9]+\))?", body, re.I)
    romans = []
    for token in tokens:
        roman = re.match(rf"({ROMAN})", token, re.I).group(1).upper()
        if roman not in romans:
            romans.append(roman)
    if re.search(r"\b(?:through|to)\b", body, re.I) and len(romans) == 2:
        start, end = roman_to_int(romans[0]), roman_to_int(romans[1])
        if start and end and 0 <= end - start <= 15:
            romans = [int_to_roman(n) for n in range(start, end + 1)]
    # Link each printed roman. Expanded through-range romans that are not
    # printed stay as the two endpoint links only when we did not expand
    # into the visible words. Expansion is represented by linking the
    # endpoints; intermediate paragraphs are not inserted into the sentence.
    visible = [re.match(rf"({ROMAN})", token, re.I).group(1).upper() for token in tokens]
    raw = match.group(0)
    cursor = 0
    pieces = []
    search_from = 0
    lower = raw.lower()
    for roman in visible:
        at = lower.find(roman.lower(), search_from)
        if at < 0:
            continue
        pieces.append(html.escape(raw[cursor:at]))
        word = raw[at : at + len(roman)]
        # Include a following (c) in the link text when it is glued to the roman.
        tail = ""
        tail_match = re.match(r"\([A-Za-z0-9]+\)", raw[at + len(roman) :])
        if tail_match:
            tail = tail_match.group(0)
        pieces.append(anchor_paragraph(word + tail, roman, target, here, catalog))
        cursor = at + len(roman) + len(tail)
        search_from = cursor
    pieces.append(html.escape(raw[cursor:]))
    return "".join(pieces)


def anchor_paragraph(label: str, roman: str, target: str, here: str, catalog: Catalog) -> str:
    section = catalog.sections.get(target)
    if section and roman in section.paragraphs:
        catalog.counts["internal"] += 1
        href = f"/rsa/{section.chapter}/{section.slug}.html#p-{roman}"
        return f'<a class="cite-internal" href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'
    if target not in catalog.sections:
        record_unresolved(catalog, here, label.strip() or roman, f"section {target} is not in this build")
        return html.escape(label)
    record_unresolved(catalog, here, label.strip() or roman, f"paragraph {roman} is not in {target}")
    return html.escape(label)


def anchor_cite(
    label: str,
    citation: str,
    paragraph: str | None,
    here: str,
    catalog: Catalog,
    paragraph_in_text: bool,
) -> str:
    placed = html_href_for(citation, catalog, paragraph if paragraph_in_text else None)
    if placed is None and paragraph_in_text and citation in catalog.sections:
        placed = html_href_for(citation, catalog, None)
    if placed is None:
        record_unresolved(catalog, here, label, f"section {citation} is not in this build")
        return html.escape(label)
    catalog.counts["internal"] += 1
    return f'<a class="cite-internal" href="{html.escape(placed, quote=True)}">{html.escape(label)}</a>'


def anchor_chapter(label: str, chapter: str, here: str, catalog: Catalog) -> str:
    if chapter in catalog.chapters:
        catalog.counts["internal"] += 1
        href = f"/rsa/{chapter}/"
        return f'<a class="cite-internal" href="{href}">{html.escape(label)}</a>'
    record_unresolved(catalog, here, label, f"chapter {chapter} is not in this build")
    return html.escape(label)


def render_lines(lines: list[str], here: str, catalog: Catalog) -> str:
    rendered = []
    seen_para: set[str] = set()
    pattern = re.compile(rf"^({ROMAN})\.(\s+)(.*)$")
    for line in lines:
        match = pattern.match(line)
        if match and roman_to_int(match.group(1)):
            roman = match.group(1).upper()
            if roman not in seen_para:
                seen_para.add(roman)
                rest = linkify(match.group(3), here, catalog)
                rendered.append(
                    f'<span id="p-{roman}">{html.escape(match.group(1))}.</span>'
                    f'{html.escape(match.group(2))}{rest}'
                )
            else:
                rendered.append(linkify(line, here, catalog))
        else:
            rendered.append(linkify(line, here, catalog))
    return "\n".join(rendered)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="alternate" type="application/ld+json" href="{jsonld}">
  <style>{style}</style>
</head>
<body>
  <a class="skip" href="#content">Skip to statute text</a>
  <nav aria-label="Breadcrumb">{breadcrumb}</nav>
  <header>
    <h1 id="section">{h1}</h1>
    {part}
  </header>
  <main id="content">
    <div class="statute">{body}</div>
  </main>
  {source_block}
  {related_block}
  {rules_block}
  <footer>
    <p>{provenance}</p>
    <p>Machine-readable form: <a href="{jsonld}">JSON-LD</a>.</p>
  </footer>
</body>
</html>
"""


def page_shell(
    title: str,
    h1: str,
    breadcrumb: str,
    body: str,
    jsonld: str,
    provenance: str,
    source_block: str,
    related_block: str,
    part: str,
    rules_block: str = "",
) -> str:
    return PAGE.format(
        title=html.escape(title),
        h1=h1,
        breadcrumb=breadcrumb,
        body=body,
        jsonld=html.escape(jsonld, quote=True),
        style=STYLE,
        provenance=provenance,
        source_block=source_block,
        related_block=related_block,
        part=part,
        rules_block=rules_block,
    )


def breadcrumb(section: Section | None, chapter: Chapter | None, title: Title | None) -> str:
    parts = ['<a href="/rsa/">Revised Statutes</a>']
    if title:
        parts.append(f'<a href="/rsa/title/{title.roman}/">{html.escape(title.name or title.roman)}</a>')
    if chapter:
        parts.append(f'<a href="/rsa/{chapter.slug}/">Chapter {html.escape(chapter.slug)}</a>')
    if section:
        parts.append(html.escape(section.citation))
    return " / ".join(parts)


def write_section_page(section: Section, catalog: Catalog) -> str:
    chapter = catalog.chapters[section.chapter]
    title = catalog.titles[section.title]
    lines = []
    if section.catchline:
        lines.append(section.catchline)
    if section.lines:
        lines.append("")
        lines.extend(section.lines)
    body = render_lines(lines, section.citation, catalog)
    source_block = ""
    if section.history_note:
        source_block = (
            "<aside><h2>Source</h2><div class=\"statute\">"
            + linkify(section.history_note, section.citation, catalog)
            + "</div></aside>"
        )
    related_block = ""
    if section.related:
        items = []
        for uri in section.related:
            label = next(
                (name for link in KB_LINKS for target, name in link["targets"] if target == uri),
                uri,
            )
            items.append(f'<li><a href="{html.escape(uri, quote=True)}">{html.escape(label)}</a></li>')
        related_block = "<aside><h2>Knowledge base</h2><ul>" + "".join(items) + "</ul></aside>"
    part = f'<p>{html.escape(section.part_heading)}</p>' if section.part_heading else ""
    return page_shell(
        title=pref_label(section.catchline, section.citation),
        h1=html.escape(pref_label(section.catchline, section.citation)),
        breadcrumb=breadcrumb(section, chapter, title),
        body=body,
        jsonld=f"/rsa/{section.chapter}/{section.slug}.jsonld",
        provenance=provenance_line(section_blob(section)),
        source_block=source_block,
        related_block=related_block,
        part=part,
        rules_block=(
            "<aside>\n    <h2>Implementing rules</h2>\n"
            '    <ul id="implementing-rules"></ul>\n  </aside>'
        ),
    )


def section_document(section: Section, catalog: Catalog) -> dict:
    title = catalog.titles[section.title]
    chapter = catalog.chapters[section.chapter]
    text_lines = []
    if section.catchline:
        text_lines.append(section.catchline)
    if section.lines:
        text_lines.append("")
        text_lines.extend(section.lines)
    doc = {
        "@context": CONTEXT_URI,
        "@id": section.identifier,
        "@type": "Concept",
        "prefLabel": pref_label(section.catchline, section.citation),
        "notation": section.citation,
        "inScheme": SCHEME_ID,
        "broader": chapter.identifier,
        "recordType": "statute-section",
        "rsaTitle": section.title,
        "source": section_blob(section),
        "officialHtml": section_blob(section),
        "statuteText": "\n".join(text_lines),
        "repealed": section.repealed,
    }
    definition = definition_of(section.catchline, section.citation)
    if definition:
        doc["catchline"] = strip_trailing_dash(section.catchline)
        doc["definition"] = definition
    if section.part_heading:
        doc["partHeading"] = section.part_heading
    if section.history_note:
        doc["historyNote"] = section.history_note
    if section.session_laws:
        doc["sessionLaw"] = section.session_laws
    if section.combined:
        doc["combinedWith"] = [catalog.sections[cite].identifier for cite in section.combined if cite in catalog.sections]
        doc["note"] = "This General Court heading also covers " + ", ".join(section.combined) + "."
    if section.related:
        doc["related"] = section.related
        if section.citation == "662:1":
            doc["note"] = (
                "From the 2022 U.S. House plan record: the opinion of 2022-05-12 found RSA 662:1 "
                "malapportioned; the court adopted the special master's least-change map on 2022-05-31. "
                "The plan record says this section's text was not amended, so the boundaries in force "
                "come from the court order."
            )
    return doc


def parse_nhtoc(path: Path) -> list[Title]:
    text = path.read_text(encoding="utf-8")
    titles = []
    pattern = re.compile(
        r"TITLE\s+([IVXLCDM]+(?:-[A-Z])?)\s*:\s*([^<]+?)\s*</a>.*?class=\"chapter_list\">\((.*?)\)</p>",
        re.I | re.S,
    )
    for roman, name, blurb in pattern.findall(text):
        name = norm(name)
        blurb_norm = norm(blurb)
        span = re.search(
            r"(\d+(?:-[A-Za-z])?)\s*(?:-|–|—)\s*(\d+(?:-[A-Za-z])?)",
            blurb_norm,
        )
        if span:
            start, end = norm_chapter(span.group(1)), norm_chapter(span.group(2))
        else:
            only = re.search(r"(\d+(?:-[A-Za-z])?)", blurb_norm)
            if not only:
                raise SystemExit(f"title {roman} has no chapter range: {blurb_norm}")
            start = end = norm_chapter(only.group(1))
        titles.append(
            Title(
                roman=roman.upper(),
                name=name,
                start=start,
                end=end,
                repealed="repeal" in blurb_norm.lower(),
            )
        )
    if not titles:
        raise SystemExit(f"no titles in {path}")
    return titles


def parse_title_toc(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"CHAPTER\s+(\d+(?:-[A-Za-z])?)\s*:\s*([^<]+)", text, re.I):
        found.append((norm_chapter(match.group(1)), norm(match.group(2))))
    return found


def parse_chapter_toc(path: Path) -> list[str]:
    """Source filenames in table-of-contents order, without the merged chapter file."""
    return [name for _cite, _label, name in parse_chapter_entries(path)]


def parse_chapter_entries(path: Path) -> list[tuple[str, str, str]]:
    """(citation, label, filename) from a chapter table of contents."""
    text = path.read_text(encoding="utf-8")
    found = []
    seen = set()
    for href, label in re.findall(r'href="([^"]+\.htm)"[^>]*>\s*([^<]+)', text, re.I):
        name = href.rsplit("/", 1)[-1]
        if name.endswith("-mrg.htm") or name in seen:
            continue
        seen.add(name)
        label = norm(label)
        match = re.search(r"(\d+(?:-[A-Za-z])?):(\d+(?:-[A-Za-z])?)", label)
        cite = ""
        if match:
            try:
                cite = f"{norm_chapter(match.group(1))}:{norm_section(match.group(2))}"
            except ValueError:
                cite = ""
        found.append((cite, label, name))
    return found


def load_section_file(path: Path, title: Title) -> list[Section]:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    if not parser.h3 and not parser.catchline:
        return []
    citations = heading_citations(parser.h3 or parser.catchline)
    if not citations:
        raise SystemExit(f"{path} has no section citation in {parser.h3!r}")
    part = ""
    chapter_heading = ""
    for heading in parser.h2:
        if re.match(r"CHAPTER\s+", heading, re.I):
            chapter_heading = heading
        elif not part:
            part = heading
    chapter = citations[0].split(":", 1)[0]
    chapter_name = ""
    if chapter_heading:
        match = re.search(r"CHAPTER\s+(\d+(?:-[A-Za-z])?)\s*(.*)$", chapter_heading, re.I)
        if match:
            headed = norm_chapter(match.group(1))
            chapter_name = norm(match.group(2))
            if citations[0].split(":", 1)[0] != headed:
                citations = [f"{headed}:{cite.split(':', 1)[1]}" for cite in citations]
            chapter = headed
    laws = parse_session_laws(parser.history)
    if not laws:
        laws = parse_repeal_laws(parser.catchline)
    else:
        extra = parse_repeal_laws(parser.catchline)
        seen = {
            (item.get("sessionYear"), item.get("sessionChapter"), tuple(item.get("sessionSection") or []))
            for item in laws
        }
        for item in extra:
            key = (item.get("sessionYear"), item.get("sessionChapter"), tuple(item.get("sessionSection") or []))
            if key not in seen:
                laws.append(item)
    repealed = "repeal" in parser.catchline.lower()
    labels = paragraph_labels(parser.lines)
    sections = []
    for citation in citations:
        if citation.split(":", 1)[0] != chapter:
            chapter = citation.split(":", 1)[0]
        sections.append(
            Section(
                citation=citation,
                chapter=chapter,
                title=title.roman,
                catchline=parser.catchline,
                part_heading=part,
                lines=list(parser.lines),
                history_note=parser.history,
                session_laws=laws,
                repealed=repealed,
                source_file=str(path),
                chapter_name=chapter_name,
                combined=[cite for cite in citations if cite != citation],
                paragraphs=set(labels),
            )
        )
    return sections


def apply_kb_links(sections: dict[str, Section]) -> list[dict]:
    rows = []
    for spec in KB_LINKS:
        section = sections.get(spec["citation"])
        catchline = section.catchline if section else ""
        applied = bool(section) and spec["catchline_contains"].lower() in catchline.lower()
        if applied:
            section.related = [uri for uri, _name in spec["targets"]]
        rows.append(
            {
                "citation": spec["citation"],
                "applied": applied,
                "catchline": strip_trailing_dash(catchline),
                "targets": spec["targets"],
                "why": spec["why"],
            }
        )
    return rows


def election_titles(titles: list[Title]) -> list[str]:
    return [title.roman for title in titles if "election" in title.name.casefold()]


def build(source: Path, selected: list[str] | None, build_all: bool) -> Catalog:
    toc_path = source / "nhtoc.htm"
    if not toc_path.is_file():
        raise SystemExit(f"missing {toc_path}")
    titles = parse_nhtoc(toc_path)
    if build_all:
        chosen = [title.roman for title in titles]
    elif selected:
        known = {title.roman for title in titles}
        missing = [roman for roman in selected if roman not in known]
        if missing:
            raise SystemExit(f"unknown title: {', '.join(missing)}")
        chosen = selected
    else:
        chosen = election_titles(titles)
        if not chosen:
            raise SystemExit("no election title in nhtoc.htm")
    by_roman = {title.roman: title for title in titles}
    catalog = Catalog(titles={}, chapters={}, sections={}, ranges=titles)
    for roman in chosen:
        title = by_roman[roman]
        catalog.titles[roman] = title
        folder = source / roman
        toc = source / "NHTOC" / f"NHTOC-{roman}.htm"
        if title.repealed and not folder.is_dir():
            continue
        if not folder.is_dir():
            raise SystemExit(f"missing title folder {folder}")
        chapter_order = parse_title_toc(toc) if toc.is_file() else []
        names = {slug: name for slug, name in chapter_order}
        slugs = [slug for slug, _name in chapter_order]
        for child in sorted(folder.iterdir()):
            if child.is_dir() and child.name not in names and re.fullmatch(r"\d+(?:-[A-Za-z])?", child.name):
                slugs.append(norm_chapter(child.name))
        for slug in slugs:
            chapter_dir = folder / slug
            if not chapter_dir.is_dir():
                # The TOC uses the official chapter token. The folder does too.
                alt = next((p for p in folder.iterdir() if p.is_dir() and p.name.upper() == slug.upper()), None)
                if alt is None:
                    raise SystemExit(f"missing chapter folder for {roman} {slug}")
                chapter_dir = alt
                slug = norm_chapter(alt.name)
            chapter = Chapter(slug=slug, title=roman, name=names.get(slug, ""))
            toc_file = source / "NHTOC" / f"NHTOC-{roman}-{slug}.htm"
            order = parse_chapter_toc(toc_file) if toc_file.is_file() else []
            missing_files = [name for name in order if not (chapter_dir / name).is_file()]
            if missing_files:
                raise SystemExit(f"chapter {slug} TOC lists files that are not on disk: {missing_files[:8]}")
            by_name = {}
            for path in sorted(chapter_dir.glob("*.htm")):
                if path.name.endswith("-mrg.htm"):
                    continue
                parsed = load_section_file(path, title)
                for section in parsed:
                    if section.citation in catalog.sections:
                        raise SystemExit(f"duplicate {section.citation} in {path}")
                    if not chapter.name:
                        chapter.name = names.get(slug, "")
                    catalog.sections[section.citation] = section
                    by_name.setdefault(path.name, []).append(section.citation)
            ordered = []
            for name in order:
                ordered.extend(by_name.pop(name, []))
            leftovers = [cite for cites in by_name.values() for cite in cites]
            leftovers.sort(key=section_sort_key)
            chapter.sections = ordered + leftovers
            if not chapter.sections:
                raise SystemExit(f"chapter {slug} produced no sections")
            catalog.chapters[slug] = chapter
            title.chapters.append(slug)
    absorb_other_sections(source, catalog, titles)
    return catalog


def absorb_other_sections(source: Path, catalog: Catalog, titles: list[Title]) -> None:
    """Add section files on disk that the selected titles did not already load.

    Citation closure drops those files next to the election scrape. A chapter
    index lists only the sections present in this snapshot.
    """
    by_roman = {title.roman: title for title in titles}
    loaded = {Path(section.source_file).resolve() for section in catalog.sections.values() if section.source_file}
    fresh_chapters: set[str] = set()
    for path in sorted(source.rglob("*.htm")):
        if path.name.endswith("-mrg.htm") or path.name.lower() == "nhtoc.htm":
            continue
        if "NHTOC" in path.parts:
            continue
        rel = path.relative_to(source)
        if len(rel.parts) != 3 or path.resolve() in loaded:
            continue
        roman = rel.parts[0]
        title = by_roman.get(roman)
        if title is None:
            continue
        if roman not in catalog.titles:
            catalog.titles[roman] = title
        title = catalog.titles[roman]
        parsed = load_section_file(path, title)
        if not parsed:
            continue
        slug = parsed[0].chapter
        chapter = catalog.chapters.get(slug)
        if chapter is None:
            chapter = Chapter(slug=slug, title=roman, name=parsed[0].chapter_name)
            catalog.chapters[slug] = chapter
            title.chapters.append(slug)
            fresh_chapters.add(slug)
        elif not chapter.name and parsed[0].chapter_name:
            chapter.name = parsed[0].chapter_name
        for section in parsed:
            if section.citation in catalog.sections:
                raise SystemExit(f"duplicate {section.citation} in {path}")
            catalog.sections[section.citation] = section
            chapter.sections.append(section.citation)
        loaded.add(path.resolve())
    for slug in fresh_chapters:
        catalog.chapters[slug].sections.sort(key=section_sort_key)
    absorb_chapter_outlines(source, catalog, titles)


def absorb_chapter_outlines(source: Path, catalog: Catalog, titles: list[Title]) -> None:
    """Create a chapter page from a downloaded table of contents when a page cites the chapter."""
    by_roman = {title.roman: title for title in titles}
    toc_dir = source / "NHTOC"
    if not toc_dir.is_dir():
        return
    for path in sorted(toc_dir.glob("NHTOC-*-*.htm")):
        match = re.fullmatch(r"NHTOC-([IVXLCDM]+(?:-[A-Z])?)-(.+)\.htm", path.name, re.I)
        if not match:
            continue
        roman = match.group(1).upper()
        slug = norm_chapter(match.group(2)) if re.fullmatch(r"\d+(?:-[A-Za-z])?", match.group(2)) else match.group(2)
        try:
            slug = norm_chapter(match.group(2))
        except ValueError:
            continue
        title = by_roman.get(roman)
        if title is None or slug in catalog.chapters and catalog.chapters[slug].title != roman:
            continue
        entries = [(cite, label) for cite, label, _name in parse_chapter_entries(path) if cite or label]
        if slug in catalog.chapters:
            if not catalog.chapters[slug].toc_entries:
                catalog.chapters[slug].toc_entries = entries
            if not catalog.chapters[slug].name:
                catalog.chapters[slug].name = chapter_name_from_toc(path)
            continue
        if roman not in catalog.titles:
            catalog.titles[roman] = title
        title = catalog.titles[roman]
        chapter = Chapter(slug=slug, title=roman, name=chapter_name_from_toc(path), toc_entries=entries)
        catalog.chapters[slug] = chapter
        title.chapters.append(slug)


def chapter_name_from_toc(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"CHAPTER\s+\d+(?:-[A-Za-z])?\s*:\s*([^<]+)", text, re.I)
    return norm(match.group(1)) if match else ""


def clean_output() -> None:
    if not RSA_DIR.exists():
        return
    keep = {"GC_AUGMENTATION.md"}
    for path in sorted(RSA_DIR.rglob("*"), reverse=True):
        if path.is_file() and path.name not in keep:
            path.unlink()
        elif path.is_dir() and path != RSA_DIR and not any(path.iterdir()):
            path.rmdir()


def write_output(catalog: Catalog, link_rows: list[dict], source: Path) -> None:
    clean_output()
    RSA_DIR.mkdir(parents=True, exist_ok=True)
    # Link after every section and its paragraphs are known.
    for section in catalog.sections.values():
        html_text = write_section_page(section, catalog)
        path = RSA_DIR / section.chapter / f"{section.slug}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
        (RSA_DIR / section.chapter / f"{section.slug}.jsonld").write_text(
            dump_json(section_document(section, catalog)),
            encoding="utf-8",
        )
    for chapter in catalog.chapters.values():
        write_chapter(chapter, catalog)
    for title in catalog.titles.values():
        write_title(title, catalog)
    write_scheme(catalog)
    write_home(catalog)
    write_index_json(catalog, source)
    write_unresolved(catalog)
    write_kb_links(link_rows)


def write_chapter(chapter: Chapter, catalog: Catalog) -> None:
    title = catalog.titles[chapter.title]
    items = []
    current_part = None
    listed = set()
    rows = chapter.toc_entries or [(cite, catalog.sections[cite].catchline) for cite in chapter.sections]
    for citation, label in rows:
        section = catalog.sections.get(citation)
        if section is not None:
            listed.add(citation)
            if section.part_heading != current_part:
                current_part = section.part_heading
                if current_part:
                    items.append(
                        f'<li style="list-style:none;margin-top:0.8rem"><strong>{html.escape(current_part)}</strong></li>'
                    )
            shown = strip_trailing_dash(section.catchline) or label or citation
            items.append(
                f'<li><a href="/rsa/{chapter.slug}/{section.slug}.html">{html.escape(shown)}</a></li>'
            )
        else:
            items.append(f"<li>{html.escape(label or citation)}</li>")
    for citation in chapter.sections:
        if citation in listed:
            continue
        section = catalog.sections[citation]
        items.append(
            f'<li><a href="/rsa/{chapter.slug}/{section.slug}.html">{html.escape(strip_trailing_dash(section.catchline) or citation)}</a></li>'
        )
    body = "<ul>" + "".join(items) + "</ul>" if items else "<p>No sections of this chapter are in the snapshot.</p>"
    page = page_shell(
        title=f"RSA {chapter.slug} {chapter.name}".strip(),
        h1=html.escape(f"Chapter {chapter.slug}" + (f" — {chapter.name}" if chapter.name else "")),
        breadcrumb=breadcrumb(None, None, title) + f" / Chapter {html.escape(chapter.slug)}",
        body=body,
        jsonld=f"/rsa/{chapter.slug}/index.jsonld",
        provenance=provenance_line(blob_url(f"NHTOC/NHTOC-{title.roman}-{chapter.slug}.htm")),
        source_block="",
        related_block="",
        part="",
    )
    directory = RSA_DIR / chapter.slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(page, encoding="utf-8")
    doc = {
        "@context": CONTEXT_URI,
        "@id": chapter.identifier,
        "@type": "Concept",
        "prefLabel": f"RSA {chapter.slug}" + (f" {chapter.name}" if chapter.name else ""),
        "notation": chapter.slug,
        "inScheme": SCHEME_ID,
        "broader": title.identifier,
        "narrower": [catalog.sections[cite].identifier for cite in chapter.sections],
        "recordType": "statute-chapter",
        "rsaTitle": title.roman,
        "source": blob_url(f"NHTOC/NHTOC-{title.roman}-{chapter.slug}.htm"),
        "officialHtml": blob_url(f"NHTOC/NHTOC-{title.roman}-{chapter.slug}.htm"),
    }
    if chapter.name:
        doc["definition"] = chapter.name
    (directory / "index.jsonld").write_text(dump_json(doc), encoding="utf-8")


def write_title(title: Title, catalog: Catalog) -> None:
    if title.repealed and not title.chapters:
        body = (
            "<p>Entire Title was repealed.</p>"
            f"<p>The table of contents covers chapters {html.escape(title.start)} through {html.escape(title.end)}. "
            "The General Court HTML for this title is a repeal notice, with no section pages in nh-rsa-data.</p>"
        )
    else:
        items = []
        for slug in title.chapters:
            chapter = catalog.chapters[slug]
            label = f"Chapter {slug}" + (f": {chapter.name}" if chapter.name else "")
            items.append(f'<li><a href="/rsa/{slug}/">{html.escape(label)}</a></li>')
        body = "<ul>" + "".join(items) + "</ul>"
    page = page_shell(
        title=f"Title {title.roman} {title.name}",
        h1=html.escape(f"Title {title.roman}"),
        breadcrumb=f'<a href="/rsa/">Revised Statutes</a> / Title {html.escape(title.roman)}',
        body=f"<p>{html.escape(title.name)}</p>" + body,
        jsonld=f"/rsa/title/{title.roman}/index.jsonld",
        provenance=provenance_line(blob_url(f"NHTOC/NHTOC-{title.roman}.htm")),
        source_block="",
        related_block="",
        part="",
    )
    directory = RSA_DIR / "title" / title.roman
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(page, encoding="utf-8")
    doc = {
        "@context": CONTEXT_URI,
        "@id": title.identifier,
        "@type": "Concept",
        "prefLabel": f"Title {title.roman} {title.name}".strip(),
        "notation": title.roman,
        "definition": title.name,
        "inScheme": SCHEME_ID,
        "topConceptOf": SCHEME_ID,
        "narrower": [catalog.chapters[slug].identifier for slug in title.chapters],
        "recordType": "statute-title",
        "rsaTitle": title.roman,
        "repealed": title.repealed,
        "source": blob_url(f"NHTOC/NHTOC-{title.roman}.htm"),
        "officialHtml": blob_url(f"NHTOC/NHTOC-{title.roman}.htm"),
    }
    (directory / "index.jsonld").write_text(dump_json(doc), encoding="utf-8")


def write_scheme(catalog: Catalog) -> None:
    doc = {
        "@context": CONTEXT_URI,
        "@id": SCHEME_ID,
        "@type": "ConceptScheme",
        "prefLabel": "New Hampshire Revised Statutes",
        "definition": (
            "RSA sections built from the General Court HTML. "
            "This scheme lists the titles. Chapters and sections are narrower concepts. "
            "The inventory is rsa/index.json."
        ),
        "hasTopConcept": [title.identifier for title in catalog.titles.values()],
    }
    (RSA_DIR / "scheme.jsonld").write_text(dump_json(doc), encoding="utf-8")


def write_home(catalog: Catalog) -> None:
    items = []
    for title in catalog.titles.values():
        extra = " (repealed)" if title.repealed else ""
        items.append(
            f'<li><a href="/rsa/title/{title.roman}/">Title {html.escape(title.roman)}: {html.escape(title.name)}</a>{extra}</li>'
        )
    if "659:21" in catalog.sections:
        example = (
            "<p>Section identifiers have no file suffix. The HTML file ends in "
            "<code>.html</code> and the JSON-LD file ends in <code>.jsonld</code>. "
            "RSA 659:21 is <a href=\"/rsa/659/659-21.html\">/rsa/659/659-21.html</a> "
            "and <a href=\"/rsa/659/659-21.jsonld\">/rsa/659/659-21.jsonld</a>.</p>"
        )
    else:
        example = (
            "<p>Section identifiers have no file suffix. The HTML file ends in "
            "<code>.html</code> and the JSON-LD file ends in <code>.jsonld</code>.</p>"
        )
    body = (
        example
        + "<ul>"
        + "".join(items)
        + "</ul>"
        "<ul>"
        "<li><a href=\"/rsa/index.json\">rsa/index.json</a> for agents</li>"
        "<li><a href=\"/rsa/KB_LINKS.md\">Knowledge-base links</a></li>"
        "<li><a href=\"/rsa/UNRESOLVED_CITATIONS.md\">Unresolved citations</a></li>"
        "<li><a href=\"/rsa/GC_AUGMENTATION.md\">General Court notes</a></li>"
        "<li><a href=\"/AGENTS.md\">How to look a section up</a></li>"
        "</ul>"
    )
    page = page_shell(
        title="New Hampshire Revised Statutes",
        h1="Revised Statutes",
        breadcrumb="<a href=\"/\">GraniteState</a>",
        body=body,
        jsonld="/rsa/index.json",
        provenance=provenance_line(blob_url("nhtoc.htm")),
        source_block="",
        related_block="",
        part="<p>Election law, plus every other section cited from these pages and present in the nh-rsa-data snapshot.</p>",
    )
    (RSA_DIR / "index.html").write_text(page, encoding="utf-8")


def write_index_json(catalog: Catalog, source: Path) -> None:
    toc_citations = []
    for chapter in catalog.chapters.values():
        toc_citations.extend(chapter.sections)
    doc = {
        "addressScheme": (
            "RSA 659:21 is https://granitestate.github.io/rsa/659/659-21. "
            "Chapter letters are uppercase and section letters are lowercase. "
            "The colon becomes a hyphen in the section slug. "
            "Fetch the identifier plus .jsonld. Humans open the .html file. "
            "A chapter is the directory /rsa/659/ (index.jsonld). "
            "A title is /rsa/title/LXIII/."
        ),
        "context": CONTEXT_URI,
        "scheme": SCHEME_ID,
        "generatedFrom": {
            "repo": SOURCE_REPO,
            "commit": rsa_pin()["commit"],
            "commitDate": rsa_pin().get("commit_date"),
            "path": "rsa_html/",
            "retrieved": rsa_pin().get("commit_date"),
            "note": "Pages link to this repository and to the raw HTML in nh-rsa-data at this commit. They do not link to the General Court site.",
            "sourceDirectory": str(source),
        },
        "scope": {
            "rule": "Titles whose nhtoc.htm heading contains ELECTION, unless --titles or --all is set.",
            "titles": list(catalog.titles),
        },
        "counts": {
            "titles": len(catalog.titles),
            "chapters": len(catalog.chapters),
            "sections": len(catalog.sections),
        },
        "citations": dict(catalog.counts),
        "titles": [
            {
                "id": title.identifier,
                "notation": title.roman,
                "prefLabel": f"Title {title.roman} {title.name}".strip(),
                "html": f"rsa/title/{title.roman}/index.html",
                "jsonld": f"rsa/title/{title.roman}/index.jsonld",
                "repealed": title.repealed,
                "chapters": list(title.chapters),
                "chapterRange": [title.start, title.end],
            }
            for title in catalog.titles.values()
        ],
        "chapters": [
            {
                "id": chapter.identifier,
                "notation": chapter.slug,
                "prefLabel": f"RSA {chapter.slug} {chapter.name}".strip(),
                "html": f"rsa/{chapter.slug}/index.html",
                "jsonld": f"rsa/{chapter.slug}/index.jsonld",
                "title": chapter.title,
                "sections": list(chapter.sections),
            }
            for chapter in catalog.chapters.values()
        ],
        "sections": [
            {
                "citation": section.citation,
                "id": section.identifier,
                "html": f"rsa/{section.chapter}/{section.slug}.html",
                "jsonld": f"rsa/{section.chapter}/{section.slug}.jsonld",
                "chapter": section.chapter,
                "title": section.title,
                "repealed": section.repealed,
                "sourceFile": str(Path(section.source_file).relative_to(source)) if section.source_file.startswith(str(source)) else section.source_file,
            }
            for section in sorted(catalog.sections.values(), key=lambda item: section_sort_key(item.citation))
        ],
        "tocCitations": toc_citations,
    }
    (RSA_DIR / "index.json").write_text(dump_json(doc), encoding="utf-8")


def write_unresolved(catalog: Catalog) -> None:
    lines = [
        "# Unresolved RSA citations",
        "",
        "A citation matched an RSA pattern and could not be linked on this site.",
        "A section or chapter row has no HTML file in the pinned nh-rsa-data snapshot. It is left as plain text.",
        "A paragraph row names a section that was built, but that paragraph marker is not in the section text.",
        "Session-law notes (for example `1979, 436:1`) are not RSA citations and are not listed here.",
        "Those notes stay unlinked until chaptered-law text is snapshotted into GraniteState/gc-data.",
        "",
        f"Unresolved: {catalog.counts['unresolved']}. Internal links: {catalog.counts['internal']}. External links: 0.",
        "",
    ]
    if not catalog.unresolved:
        lines.append("None.")
    else:
        lines.append("| In section | Citation | Reason |")
        lines.append("| --- | --- | --- |")
        for item in catalog.unresolved:
            cite = item.text.replace("|", "\\|")
            reason = item.reason.replace("|", "\\|")
            lines.append(f"| {item.section} | {cite} | {reason} |")
    lines.append("")
    (RSA_DIR / "UNRESOLVED_CITATIONS.md").write_text("\n".join(lines), encoding="utf-8")


def write_kb_links(rows: list[dict]) -> None:
    lines = [
        "# RSA links into the knowledge base",
        "",
        "A row is applied only when the section exists and the catchline still contains the expected words.",
        "The statute points at the KB concept with `related`. The generated KB files do not point back.",
        "Chapter 662-A (division of state representative districts) is not linked: no KB record cites it.",
        "Chapter 653 names offices that are elected and is not linked: the KB offices are the 2022 districts, and no KB record cites chapter 653.",
        "",
        "| RSA | Applied | Catchline | KB concepts | Why |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        targets = ", ".join(f"[{name}]({uri})" for uri, name in row["targets"])
        catchline = row["catchline"].replace("|", "\\|")
        lines.append(
            f"| {row['citation']} | {'yes' if row['applied'] else 'no'} | {catchline} | {targets} | {row['why']} |"
        )
    lines.append("")
    (RSA_DIR / "KB_LINKS.md").write_text("\n".join(lines), encoding="utf-8")


def self_test() -> int:
    errors = []

    def check(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    check(norm_cite("659", "21") == "659:21", "659:21")
    check(norm_cite("659", "20-A") == "659:20-a", "section letter")
    check(norm_cite("662-a", "1") == "662-A:1", "chapter letter")
    check(section_slug("659:20-a") == "659-20-a", "slug 20-a")
    check(section_slug("662-A:1") == "662-A-1", "slug 662-A")
    check(heading_citations("Section 659:1, 659:2") == ["659:1", "659:2"], "pair")
    check(heading_citations("Section 655:55 to 655:80") == [f"655:{n}" for n in range(55, 81)], "numeric range")
    check(heading_citations("Section 664:5-a to 664:5-b") == ["664:5-a", "664:5-b"], "letter range")
    check(fix_windows_chars("\x96") == "\u2013", "en dash")

    laws = parse_session_laws("Source. 1979, 436:1, eff. July 1, 1979. 2024, 4:15, eff. Feb. 1, 2024.")
    check(len(laws) == 2, f"two laws, got {laws}")
    check(laws[0]["sessionChapter"] == "436" and laws[0]["sessionSection"] == ["1"], "436:1")
    check(laws[0].get("effectiveDate") == "1979-07-01", "1979 date")
    check(laws[1]["sessionChapter"] == "4" and laws[1].get("effectiveDate") == "2024-02-01", "2024")

    laws = parse_session_laws(
        "Source. 2016, 174:1, eff. Aug. 2, 2016; 259:1, eff. June 15, 2016; 259:4, eff. Aug. 2, 2016 at 12:01 a.m."
    )
    check(len(laws) == 3, f"three 2016 clauses, got {len(laws)} {laws}")
    check(laws[2].get("effectiveDate") == "2016-08-02", "time of day still has a date")
    check("12:01" in laws[2].get("effectiveText", ""), "time kept")

    laws = parse_session_laws("Source. 2012, 284:1, 7; 289:2, 4.")
    check(
        [(item["sessionChapter"], item["sessionSection"]) for item in laws] == [("284", ["1", "7"]), ("289", ["2", "4"])],
        f"semicolon chapters {laws}",
    )
    check(all("effectiveDate" not in item for item in laws), "no invented date")

    laws = parse_session_laws(
        "Source. 2015, 276:182, eff. Sept. 1, 2015 at 12:03 a.m. 2016, 71:14, eff. May 10, 2016."
    )
    check(len(laws) == 2 and laws[0]["sessionSection"] == ["182"] and laws[1]["sessionYear"] == 2016, f"a.m. split {laws}")

    laws = parse_session_laws("Source. 2024, 378:6, 7, 10, IV and V, eff. Nov. 11, 2024.")
    check(laws[0]["sessionSection"] == ["6", "7", "10"], f"sections {laws}")
    check(laws[0].get("sessionRemainder") == "IV and V", f"remainder {laws}")
    check(laws[0].get("effectiveDate") == "2024-11-11", "Nov date")

    laws = parse_session_laws("Repealed by 2024, 378:10, III, eff. Nov. 11, 2024.")
    check(laws[0]["sessionSection"] == ["10"] and laws[0].get("sessionRemainder") == "III", f"repeal III {laws}")

    laws = parse_session_laws("Source. 1994, 324:3, eff. June 8, 1994, at 12:01 a.m.")
    check(laws[0].get("effectiveDate") == "1994-06-08", f"comma before at {laws}")

    laws = parse_session_laws("Source. 2014, 131:1-3. 2020, 23:2-7, eff. July 17, 2020.")
    check(laws[0]["sessionSection"] == ["1-3"] and "effectiveDate" not in laws[0], f"range kept {laws}")
    check(laws[1]["sessionSection"] == ["2-7"] and laws[1].get("effectiveDate") == "2020-07-17", f"range date {laws}")

    laws = parse_session_laws("2014, 279:1-4 eff. July 28, 2014")
    check(laws[0]["sessionSection"] == ["1-4"] and laws[0].get("effectiveDate") == "2014-07-28", f"missing comma {laws}")

    laws = parse_session_laws("Repealed by 2010, 368:1(53), eff. Dec. 31, 2010. –")
    check(
        laws[0]["sessionSection"] == ["1"]
        and laws[0].get("sessionRemainder") == "(53)"
        and laws[0].get("effectiveDate") == "2010-12-31",
        f"parenthetical section {laws}",
    )

    catalog = fake_catalog()
    samples = {
        "RSA 659:21": ("cite-internal", "/rsa/659/659-21.html"),
        "RSA 659:20-a": ("cite-internal", "/rsa/659/659-20-a.html"),
        "RSA 662-A:1": ("cite-internal", "/rsa/662-A/662-A-1.html"),
        "see RSA 659.": ("cite-internal", "/rsa/659/"),
        "section 659:21": ("cite-internal", "/rsa/659/659-21.html"),
        "RSA 654:12, V": ("cite-internal", "/rsa/654/654-12.html#p-V"),
    }
    for text, (kind, href) in samples.items():
        linked = linkify(text, "659:13", catalog)
        check(kind in linked and href in linked, f"{text} -> {linked}")
    for text in ("RSA 260:21", "RSA 260:21-a", "RSA 60:1", "RSA 91-A"):
        linked = linkify(text, "659:13", catalog)
        check("<a " not in linked, f"no external href for {text}: {linked}")
        check("gc.nh.gov" not in linked and "gencourt" not in linked, f"no general court host in {text}")
    linked = linkify("RSA 659:1 through 659:5", "659:13", catalog)
    check(linked.count("cite-internal") == 2, f"range {linked}")
    linked = linkify("paragraph I", "659:13", catalog)
    check('href="/rsa/659/659-13.html#p-I"' in linked, f"paragraph I {linked}")
    before = catalog.counts["unresolved"]
    linked = linkify("paragraph IX", "659:13", catalog)
    check(catalog.counts["unresolved"] == before + 1, "missing paragraph is unresolved")
    check("cite-internal" not in linked, f"missing paragraph not linked {linked}")
    linked = linkify("1979, 436:1", "659:13", catalog)
    check("<a " not in linked, f"session law not linked {linked}")
    linked = linkify("RSA 999:1", "659:13", catalog)
    check("cite-" not in linked, f"unknown chapter {linked}")

    if errors:
        print("\n".join(errors))
        print(f"FAILED {len(errors)} self-test(s)")
        return 1
    print("self-test OK")
    return 0


def fake_catalog() -> Catalog:
    titles = [
        Title("IV", "ELECTIONS", "54", "70", True),
        Title("XXI", "MOTOR VEHICLES", "259", "269", False),
        Title("LXIII", "ELECTIONS", "652", "671", False),
        Title("I", "THE STATE AND ITS GOVERNMENT", "1", "21-V", False),
    ]
    catalog = Catalog(titles={t.roman: t for t in titles if t.roman == "LXIII"}, chapters={}, sections={}, ranges=titles)
    catalog.titles["IV"] = titles[0]
    for citation, paras in {
        "659:21": set(),
        "659:20-a": set(),
        "659:1": set(),
        "659:5": set(),
        "659:13": {"I", "II", "V"},
        "654:12": {"V"},
        "662-A:1": set(),
    }.items():
        chapter = citation.split(":", 1)[0]
        catalog.sections[citation] = Section(
            citation=citation,
            chapter=chapter,
            title="LXIII",
            catchline=citation,
            part_heading="",
            lines=[],
            history_note="",
            session_laws=[],
            repealed=False,
            source_file="",
            paragraphs=set(paras),
        )
        catalog.chapters.setdefault(chapter, Chapter(chapter, "LXIII", "")).sections.append(citation)
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build RSA HTML and JSON-LD from the General Court scrape.")
    parser.add_argument("--source", type=Path, help="Path to rsa_html from GraniteState/nh-rsa-data")
    parser.add_argument("--titles", help="Comma-separated title Roman numerals, for example LXIII,IV")
    parser.add_argument("--all", action="store_true", help="Build every title in nhtoc.htm")
    parser.add_argument("--self-test", action="store_true", help="Run parser tests and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.source is None:
        raise SystemExit("pass --source, or --self-test")
    source = args.source.expanduser().resolve()
    selected = [part.strip().upper() for part in args.titles.split(",")] if args.titles else None
    catalog = build(source, selected, args.all)
    rows = apply_kb_links(catalog.sections)
    write_output(catalog, rows, source)
    print(
        f"titles {len(catalog.titles)} chapters {len(catalog.chapters)} sections {len(catalog.sections)} "
        f"internal {catalog.counts['internal']} external 0 "
        f"unresolved {catalog.counts['unresolved']}"
    )
    print("titles:", ", ".join(f"{roman} {catalog.titles[roman].name}" for roman in catalog.titles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
