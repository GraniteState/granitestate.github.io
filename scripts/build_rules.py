#!/usr/bin/env python3
"""Build administrative-rule pages and fill RSA implementing-rule lists.

Standard library only. The Office of Legislative Services HTML is not stored
in this repository. Pass a checkout of GraniteState/adm-rules-data at the
commit in sources/provenance.json:

  python3 scripts/build_rules.py --source /path/to/adm-rules-data
  python3 scripts/build_rules.py --self-test

``--prefixes Elec,Bal`` writes those agencies and leaves other rule pages in
place. RSA implementing-rule lists are then rebuilt from every rule JSON-LD
file on disk, so a partial run stays consistent with the pages that exist.

Address scheme
--------------
Elec 101.01 is https://granitestate.github.io/rules/elec/101.01
HTML is /rules/elec/101.01.html and JSON-LD is /rules/elec/101.01.jsonld.
An agency is the directory /rules/elec/. GitHub Pages does not rewrite a
bare path to the .html file.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

from kb_common import CONTEXT_URI, ROOT, SITE, dump_json
from rule_html import decode_html, extract_bodies, self_test as html_self_test

SOURCE_REPO = "GraniteState/adm-rules-data"
RULES = ROOT / "rules"
RSA = ROOT / "rsa"
SCHEME_ID = SITE + "rules/scheme"

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
.skip { position: absolute; left: -999px; top: 0; }
.skip:focus { left: 1rem; background: Canvas; padding: 0.3rem 0.6rem; }
nav { font-size: 0.95rem; }
.statute { white-space: pre-wrap; font-family: inherit; }
aside, footer { margin-top: 1.5rem; }
footer, .note { font-size: 0.95rem; }
ul { padding-left: 1.2rem; }
li { margin: 0.25rem 0; }
"""

VIA_LABEL = {
    "appendix": "appendix",
    "statutory_authority": "statutory authority",
    "inherited_part": "inherited from the part",
    "inherited_chapter": "inherited from the chapter",
}

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
  <a class="skip" href="#content">Skip to rule text</a>
  <nav aria-label="Breadcrumb">{breadcrumb}</nav>
  <header>
    <h1 id="section">{h1}</h1>
    {part}
  </header>
  <main id="content">
    {body}
  </main>
  {extra}
  <footer>
    <p>{disclaimer}</p>
    <p>{provenance}</p>
    <p>Machine-readable form: <a href="{jsonld}">JSON-LD</a>.</p>
  </footer>
</body>
</html>
"""

RSA_ASIDE_RE = re.compile(
    r"<aside>\s*<h2>Implementing rules</h2>\s*<ul id=\"implementing-rules\">.*?</ul>\s*</aside>",
    re.S,
)
PARA_LINE = re.compile(r"^(\s*)(\(([a-z]|\d{1,2})\))(?=\s|$)")
LINKER: re.Pattern[str] | None = None


def rules_pin() -> dict:
    doc = json.loads((ROOT / "sources/provenance.json").read_text(encoding="utf-8"))
    pin = doc.get("rules")
    if not isinstance(pin, dict) or not pin.get("commit"):
        raise SystemExit("sources/provenance.json has no rules.commit")
    return pin


def rule_sort_key(rule_id: str):
    match = re.match(r"^([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)?)\s+(\d+)(?:\.(\d+))?$", rule_id)
    if not match:
        return (rule_id.casefold(), 0, 0, rule_id)
    minor = int(match.group(3)) if match.group(3) is not None else -1
    return (match.group(1).casefold(), int(match.group(2)), minor, rule_id)


def rsa_sort_key(rsa_id: str):
    match = re.fullmatch(r"(\d+)(?:-([A-Z]))?(?::(\d+)(?:-([a-z]))?)?", rsa_id)
    if not match:
        return (10**9, "", 10**9, "", rsa_id)
    section = int(match.group(3)) if match.group(3) else -1
    return (int(match.group(1)), match.group(2) or "", section, match.group(4) or "", rsa_id)


def split_id(rule_id: str) -> tuple[str, str]:
    prefix, number = rule_id.split(" ", 1)
    return prefix, number


def slug_of(prefix: str) -> str:
    return prefix.casefold()


def rule_html(rule_id: str) -> str:
    prefix, number = split_id(rule_id)
    return f"/rules/{slug_of(prefix)}/{number}.html"


def rule_jsonld_href(rule_id: str) -> str:
    prefix, number = split_id(rule_id)
    return f"/rules/{slug_of(prefix)}/{number}.jsonld"


def rule_uri(rule_id: str) -> str:
    prefix, number = split_id(rule_id)
    return f"{SITE}rules/{slug_of(prefix)}/{number}"


def agency_uri(prefix: str) -> str:
    return f"{SITE}rules/{slug_of(prefix)}"


def blob_url(source_page: str) -> str:
    rel = source_page.lstrip("/")
    return f"https://github.com/{SOURCE_REPO}/blob/{rules_pin()['commit']}/{rel}"


def publisher_text(source_page: str) -> str:
    name = source_page.rsplit("/", 1)[-1]
    return f"https://gc.nh.gov/rules/state_agencies/{name}"


def short_name(name: str) -> str:
    lead = name.split(" (", 1)[0].strip()
    return lead or name.strip()


def paragraph_ids(lines: list[str]) -> set[str]:
    found = set()
    for line in lines:
        match = PARA_LINE.match(line.strip())
        if match:
            found.add(match.group(3))
    return found


def configure_linker(prefixes: list[str]) -> None:
    global LINKER
    ordered = sorted(set(prefixes), key=len, reverse=True)
    alts = "|".join(re.escape(prefix) for prefix in ordered) or r"Elec"
    LINKER = re.compile(
        rf"(?P<rule>(?P<prefix>{alts})\s+(?P<num>\d{{2,4}}(?:\.\d{{1,3}})?)(?![0-9.])"
        rf"(?P<rpara>\s*\((?P<rlabel>[a-z]|\d{{1,2}})\))?)"
        rf"|(?P<rsa>\bRSA\s+(?:(?:chapters?|ch\.)\s+)?"
        rf"(?P<chap>\d{{1,4}})(?:-(?P<chlet>[A-Za-z]))?"
        rf"(?::(?P<sec>\d{{1,4}})(?:-(?P<seclet>[A-Za-z]))?)?)",
        re.I,
    )


def render_line(
    line: str,
    page_ids: set[str],
    rules_by_key: dict[tuple[str, str], str],
    para_ids: dict[str, set[str]],
    rsa_sections: dict[str, dict],
    rsa_chapters: dict[str, dict],
) -> str:
    assert LINKER is not None
    prefix_html = ""
    rest = line
    mark = PARA_LINE.match(line)
    if mark and mark.group(3) in page_ids:
        page_ids.remove(mark.group(3))
        prefix_html = (
            html.escape(mark.group(1))
            + f'<span id="{html.escape(mark.group(3), quote=True)}">{html.escape(mark.group(2))}</span>'
        )
        rest = line[mark.end() :]
    pieces = [prefix_html]
    cursor = 0
    for match in LINKER.finditer(rest):
        if match.start() < cursor:
            continue
        pieces.append(html.escape(rest[cursor : match.start()]))
        if match.group("rule"):
            pieces.append(render_rule_cite(match, rules_by_key, para_ids))
        else:
            pieces.append(render_rsa_cite(match, rsa_sections, rsa_chapters))
        cursor = match.end()
    pieces.append(html.escape(rest[cursor:]))
    return "".join(pieces)


def render_rule_cite(match: re.Match[str], rules_by_key: dict[tuple[str, str], str], para_ids: dict[str, set[str]]) -> str:
    prefix = match.group("prefix")
    number = match.group("num")
    rule_id = rules_by_key.get((prefix.casefold(), number))
    visible = match.group("rule")
    if rule_id is None:
        return html.escape(visible)
    label = (match.group("rlabel") or "").lower()
    fragment = ""
    if label and label in para_ids.get(rule_id, set()):
        fragment = f"#{label}"
    href = rule_html(rule_id) + fragment
    return f'<a class="cite-internal" href="{html.escape(href, quote=True)}">{html.escape(visible)}</a>'


def render_rsa_cite(match: re.Match[str], rsa_sections: dict[str, dict], rsa_chapters: dict[str, dict]) -> str:
    visible = match.group("rsa")
    chapter = match.group("chap") + (f"-{match.group('chlet').upper()}" if match.group("chlet") else "")
    if match.group("sec"):
        section = match.group("sec") + (f"-{match.group('seclet').lower()}" if match.group("seclet") else "")
        rsa_id = f"{chapter}:{section}"
        item = rsa_sections.get(rsa_id)
        if item is None:
            return html.escape(visible)
        href = "/" + item["html"]
    else:
        item = rsa_chapters.get(chapter)
        if item is None:
            return html.escape(visible)
        href = f"/rsa/{chapter}/"
    return f'<a class="cite-internal" href="{html.escape(href, quote=True)}">{html.escape(visible)}</a>'


def render_body(lines: list[str], **kwargs) -> str:
    if not lines:
        return '<p class="note">This heading has no operative text in the snapshot.</p>'
    page_ids = paragraph_ids(lines)
    rendered = [render_line(line, page_ids, **kwargs) for line in lines]
    return '<div class="statute">' + "\n\n".join(rendered) + "</div>"


def disclaimer_html(rsa_chapters: dict[str, dict]) -> str:
    lead = (
        "This text is the Office of Legislative Services online compilation "
        "in the 2026-11-15 snapshot. OLS states that the online compilation "
        "matches the certified rule in substance and is not the official version under "
    )
    tail = ", because the format differs and a later filing may not be online yet."
    if "541-A" in rsa_chapters:
        target = '<a href="/rsa/541-A/">RSA 541-A</a>'
    else:
        target = "RSA 541-A"
    return lead + target + tail


def provenance_html(source_page: str) -> str:
    pin = rules_pin()
    commit = pin["commit"]
    retrieved = pin.get("snapshot") or "2026-11-15"
    blob = blob_url(source_page)
    return (
        f"Source: NH OLS administrative rules compilation, retrieved {html.escape(retrieved)}, "
        f"adm-rules-data@{html.escape(commit[:12])}. "
        f'<a href="{html.escape(blob, quote=True)}">Raw HTML in adm-rules-data</a>. '
        f"Publisher URL (not linked): {html.escape(publisher_text(source_page))}."
    )


def page_shell(title: str, h1: str, breadcrumb: str, body: str, jsonld: str, part: str, extra: str, provenance: str, disclaimer: str) -> str:
    return PAGE.format(
        title=html.escape(title),
        h1=h1,
        breadcrumb=breadcrumb,
        body=body,
        jsonld=html.escape(jsonld, quote=True),
        style=STYLE,
        part=part,
        extra=extra,
        provenance=provenance,
        disclaimer=disclaimer,
    )


def authority_label(rsa_id: str, paragraphs: list[str]) -> str:
    if paragraphs:
        return f"RSA {rsa_id}, {', '.join(paragraphs)}"
    return f"RSA {rsa_id}"


def group_authority(citations: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for cite in citations:
        if cite.get("role") != "implements":
            continue
        rsa_id = cite["rsa_id"]
        item = grouped.get(rsa_id)
        if item is None:
            item = {"rsa_id": rsa_id, "paragraphs": [], "vias": []}
            grouped[rsa_id] = item
            order.append(rsa_id)
        for para in cite.get("paragraphs") or []:
            if para not in item["paragraphs"]:
                item["paragraphs"].append(para)
        via = cite.get("via")
        if via and via not in item["vias"]:
            item["vias"].append(via)
    return [grouped[rsa_id] for rsa_id in order]


def authority_objects(grouped: list[dict], rsa_sections: dict, rsa_chapters: dict) -> tuple[list[dict], list[str]]:
    objects = []
    linked = []
    for item in grouped:
        rsa_id = item["rsa_id"]
        obj: dict = {"citation": rsa_id, "via": item["vias"][0] if item["vias"] else "appendix"}
        if item["vias"]:
            obj["via"] = ",".join(item["vias"])
        if item["paragraphs"]:
            obj["paragraphs"] = list(item["paragraphs"])
        target = rsa_target(rsa_id, rsa_sections, rsa_chapters)
        if target is not None:
            _href, uri = target
            obj["source"] = uri
            if uri not in linked:
                linked.append(uri)
        objects.append(obj)
    return objects, linked


def rsa_target(rsa_id: str, rsa_sections: dict, rsa_chapters: dict) -> tuple[str, str] | None:
    if ":" in rsa_id:
        item = rsa_sections.get(rsa_id)
        if item is None:
            return None
        return "/" + item["html"], item["id"]
    item = rsa_chapters.get(rsa_id)
    if item is None:
        return None
    return f"/rsa/{rsa_id}/", item["id"]


def authority_html(grouped: list[dict], rsa_sections: dict, rsa_chapters: dict) -> str:
    if not grouped:
        return (
            '<aside><h2>Authority</h2>'
            '<ul id="authority"><li>No implementing RSA citation in this snapshot.</li></ul></aside>'
        )
    items = []
    for item in grouped:
        label = authority_label(item["rsa_id"], item["paragraphs"])
        via = "; ".join(VIA_LABEL.get(via, via) for via in item["vias"])
        note = f' <span class="note">{html.escape(via)}</span>' if via else ""
        target = rsa_target(item["rsa_id"], rsa_sections, rsa_chapters)
        if target is None:
            items.append(f"<li>{html.escape(label)}{note}</li>")
        else:
            href, _uri = target
            items.append(
                f'<li><a class="cite-authority" href="{html.escape(href, quote=True)}">{html.escape(label)}</a>{note}</li>'
            )
    return '<aside><h2>Authority</h2><ul id="authority">' + "".join(items) + "</ul></aside>"


def meta_line(rule: dict) -> str:
    bits = []
    if rule.get("effective"):
        bits.append(f"Effective {rule['effective']}")
    if rule.get("expiration"):
        bits.append(f"Expires {rule['expiration']}")
    if rule.get("prior_expiration"):
        bits.append(f"Earlier expiration {rule['prior_expiration']}")
    if not bits:
        return ""
    return f"<p>{html.escape('. '.join(bits))}.</p>"


def load_rsa_catalog() -> tuple[dict, dict]:
    index = json.loads((RSA / "index.json").read_text(encoding="utf-8"))
    sections = {item["citation"]: item for item in index["sections"]}
    chapters = {item["notation"]: item for item in index["chapters"]}
    return sections, chapters


def publishable(rule: dict, codes: set[str]) -> bool:
    prefix = rule["id"].split(" ", 1)[0]
    return prefix.casefold() in codes


def parent_of(rule: dict, by_id: dict[str, dict]) -> str | None:
    if rule["level"] == "chapter":
        return None
    if rule["level"] == "part":
        chapter = rule.get("chapter")
        if chapter in by_id and by_id[chapter]["level"] == "chapter":
            return chapter
        return None
    part = rule.get("part")
    if part in by_id:
        return part
    chapter = rule.get("chapter")
    if chapter in by_id:
        return chapter
    return None


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ancestor_chain(rule_id: str, by_id: dict[str, dict]) -> list[str]:
    chain = []
    seen = set()
    current = parent_of(by_id[rule_id], by_id)
    while current and current not in seen:
        seen.add(current)
        chain.append(current)
        current = parent_of(by_id[current], by_id)
    chain.reverse()
    return chain


def build(source: Path, only: set[str] | None, skip_rsa: bool) -> None:
    pin = rules_pin()
    derived = source / "derived"
    rules_doc = json.loads((derived / "rules.json").read_text(encoding="utf-8"))
    forward = json.loads((derived / "rule_to_rsa.json").read_text(encoding="utf-8"))
    if rules_doc.get("snapshot") != pin.get("snapshot"):
        raise SystemExit(
            f"snapshot {rules_doc.get('snapshot')} does not match provenance rules.snapshot {pin.get('snapshot')}"
        )
    agencies = rules_doc["agencies"]
    codes: set[str] = set()
    by_slug: dict[str, dict] = {}
    for agency in agencies:
        codes.add(agency["slug"])
        codes.add(agency["code"].casefold())
        codes.add(agency["code"].split()[0].casefold())
        by_slug.setdefault(agency["slug"], agency)
    published = [rule for rule in rules_doc["rules"] if publishable(rule, codes)]
    dropped = [rule for rule in rules_doc["rules"] if not publishable(rule, codes)]
    if only is not None:
        published = [rule for rule in published if rule["id"].split(" ", 1)[0] in only]
    by_id = {rule["id"]: rule for rule in published}
    cites_by_rule = {item["rule_id"]: item.get("citations") or [] for item in forward["rules"]}
    rsa_sections, rsa_chapters = load_rsa_catalog()
    prefix_map = {rule["id"].split(" ", 1)[0].casefold(): rule["id"].split(" ", 1)[0] for rule in published}
    # Keep every real agency prefix available to the heading parser so a
    # heading in a file is still a boundary when this run writes one prefix.
    for agency in agencies:
        token = agency["code"].split()[0]
        prefix_map.setdefault(token.casefold(), token if token[:1].isupper() else token.capitalize())
        prefix_map.setdefault(agency["slug"], prefix_map.get(agency["slug"], agency["slug"]))
    configure_linker(list({rule["id"].split(" ", 1)[0] for rule in published}))
    # The linker used while rendering must know every rule already on disk
    # when this is a partial run, plus the ones being written.
    if only is None and RULES.exists():
        shutil.rmtree(RULES)
    disk_ids = existing_rule_ids() if only is not None else set()
    all_known_ids = set(by_id) | disk_ids
    configure_linker([rule_id.split(" ", 1)[0] for rule_id in all_known_ids])

    bodies = extract_all(source, published, prefix_map)
    para_ids = {rule_id: paragraph_ids(lines) for rule_id, lines in bodies.items()}
    for rule_id in disk_ids:
        if rule_id not in para_ids:
            para_ids[rule_id] = set()
    rules_by_key = {}
    for rule_id in all_known_ids:
        prefix, number = split_id(rule_id)
        rules_by_key[(prefix.casefold(), number)] = rule_id

    RULES.mkdir(parents=True, exist_ok=True)

    children: dict[str | None, list[str]] = {}
    for rule in published:
        parent = parent_of(rule, by_id)
        children.setdefault(parent, []).append(rule["id"])
    for key in children:
        children[key].sort(key=rule_sort_key)

    link_kwargs = {
        "rules_by_key": rules_by_key,
        "para_ids": para_ids,
        "rsa_sections": rsa_sections,
        "rsa_chapters": rsa_chapters,
    }
    agency_names = names_for(published, by_slug)
    written = 0
    for rule in published:
        write_rule_page(rule, by_id, bodies.get(rule["id"]) or [], cites_by_rule.get(rule["id"]) or [], children, agency_names, link_kwargs)
        written += 1
        if written % 2000 == 0:
            print(f"wrote {written} rule pages", flush=True)
    print(f"wrote {written} rule pages", flush=True)

    prefixes = sorted({rule["id"].split(" ", 1)[0] for rule in published}, key=str.casefold)
    # Agency pages and the index describe every prefix that has pages on disk
    # after this run, so a partial run does not drop agencies already written.
    on_disk = load_rule_docs()
    disk_prefixes = sorted({doc["agencyCode"] for doc in on_disk if doc.get("agencyCode")}, key=str.casefold)
    write_agency_pages(disk_prefixes, on_disk, agency_names, by_slug, rsa_chapters)
    write_scheme(disk_prefixes)
    write_index(disk_prefixes, on_disk, agencies, by_slug, agency_names, dropped, pin)
    write_gaps(dropped, agencies, pin, on_disk)
    write_unresolved(on_disk, rsa_sections, rsa_chapters)
    if not skip_rsa:
        sync_rsa(on_disk, rsa_sections, rsa_chapters)
    print(
        f"prefixes {len(disk_prefixes)} rules {len(on_disk)} "
        f"dropped headings {len(dropped)} skip_rsa {skip_rsa}"
    )


def existing_rule_ids() -> set[str]:
    if not RULES.exists():
        return set()
    found = set()
    for path in RULES.glob("*/*.jsonld"):
        if path.name == "index.jsonld":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        notation = doc.get("notation")
        if isinstance(notation, str) and " " in notation:
            found.add(notation)
    return found


def load_rule_docs() -> list[dict]:
    docs = []
    if not RULES.exists():
        return docs
    for path in sorted(RULES.glob("*/*.jsonld")):
        if path.name == "index.jsonld":
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("recordType", "").startswith("rule-") and doc.get("recordType") != "rule-agency":
            docs.append(doc)
    return docs


def names_for(published: list[dict], by_slug: dict[str, dict]) -> dict[str, dict]:
    """prefix -> {name, full, see_also, slug}."""
    found: dict[str, dict] = {}
    for rule in published:
        prefix = rule["id"].split(" ", 1)[0]
        if prefix in found:
            continue
        agency = by_slug.get(slug_of(prefix))
        if agency is None:
            agency = next((item for item in by_slug.values() if item["code"].split()[0].casefold() == prefix.casefold() and not item.get("see_also")), None)
        if agency is None:
            found[prefix] = {"name": prefix, "full": prefix, "see_also": False, "slug": slug_of(prefix)}
            continue
        full = agency["name"].strip()
        short = short_name(full)
        if agency.get("see_also") and len(short) < 8:
            short = prefix
        found[prefix] = {
            "name": short,
            "full": full,
            "see_also": bool(agency.get("see_also")),
            "slug": agency["slug"],
        }
    return found


def extract_all(source: Path, published: list[dict], prefix_map: dict[str, str]) -> dict[str, list[str]]:
    wanted = {rule["id"]: rule.get("source_page") for rule in published}
    pages = sorted({page for page in wanted.values() if page})
    bodies: dict[str, list[str]] = {}
    for index, rel in enumerate(pages, start=1):
        path = source / rel
        if not path.is_file():
            print(f"missing source page {rel}", flush=True)
            continue
        html_text = decode_html(path.read_bytes())
        extracted = extract_bodies(html_text, prefix_map)
        for rule_id, lines in extracted.items():
            # Use the text in the rule's own source file, not a table-of-contents repeat.
            if wanted.get(rule_id) == rel:
                bodies[rule_id] = lines
        if index % 40 == 0 or index == len(pages):
            print(f"read {index}/{len(pages)} source files", flush=True)
    return bodies


def write_rule_page(rule, by_id, lines, citations, children, agency_names, link_kwargs) -> None:
    rule_id = rule["id"]
    prefix = rule_id.split(" ", 1)[0]
    info = agency_names.get(prefix) or {"name": prefix, "full": prefix}
    title = (rule.get("title") or "").strip()
    label = f"{rule_id} {title}".strip()
    rsa_sections = link_kwargs["rsa_sections"]
    rsa_chapters = link_kwargs["rsa_chapters"]
    grouped = group_authority(citations)
    authority, linked = authority_objects(grouped, rsa_sections, rsa_chapters)
    body = render_body(lines, **link_kwargs)
    crumbs = ['<a href="/rules/">Administrative rules</a>', f'<a href="/rules/{slug_of(prefix)}/">{html.escape(prefix)}</a>']
    for ancestor in ancestor_chain(rule_id, by_id):
        crumbs.append(f'<a href="{html.escape(rule_html(ancestor), quote=True)}">{html.escape(ancestor)}</a>')
    crumbs.append(html.escape(rule_id))
    part = meta_line(rule)
    extra = authority_html(grouped, rsa_sections, rsa_chapters)
    source_page = rule.get("source_page") or ""
    page = page_shell(
        title=label,
        h1=html.escape(label),
        breadcrumb=" / ".join(crumbs),
        body=body,
        jsonld=rule_jsonld_href(rule_id),
        part=part,
        extra=extra,
        provenance=provenance_html(source_page) if source_page else "",
        disclaimer=disclaimer_html(rsa_chapters),
    )
    prefix_dir = RULES / slug_of(prefix)
    number = rule_id.split(" ", 1)[1]
    write_text(prefix_dir / f"{number}.html", page)
    parent = parent_of(rule, by_id)
    broader = rule_uri(parent) if parent else agency_uri(prefix)
    doc = {
        "@context": CONTEXT_URI,
        "@id": rule_uri(rule_id),
        "@type": "Concept",
        "prefLabel": label,
        "notation": rule_id,
        "inScheme": SCHEME_ID,
        "broader": broader,
        "recordType": f"rule-{rule['level']}",
        "agencyCode": prefix,
    }
    if title:
        doc["definition"] = title
    if rule.get("toc_title") and rule["toc_title"] != title:
        doc["altLabel"] = rule["toc_title"]
    if lines:
        doc["ruleText"] = "\n\n".join(lines)
    else:
        doc["note"] = "The snapshot has no operative text for this heading."
    if rule.get("effective"):
        doc["effectiveDate"] = rule["effective"]
    if rule.get("expiration"):
        doc["expirationDate"] = rule["expiration"]
    if rule.get("prior_expiration"):
        doc["priorExpiration"] = rule["prior_expiration"]
    if rule.get("source_note"):
        doc["historyNote"] = rule["source_note"]
    if authority:
        doc["authority"] = authority
    if linked:
        doc["authorizedBy"] = linked
    narrower = [rule_uri(child) for child in children.get(rule_id, [])]
    if narrower:
        doc["narrower"] = narrower
    if source_page:
        doc["source"] = blob_url(source_page)
        doc["officialHtml"] = blob_url(source_page)
    write_text(prefix_dir / f"{number}.jsonld", dump_json(doc))


def write_agency_pages(prefixes, docs, agency_names, by_slug, rsa_chapters) -> None:
    by_prefix: dict[str, list[dict]] = {}
    for doc in docs:
        by_prefix.setdefault(doc.get("agencyCode") or "", []).append(doc)
    for prefix in prefixes:
        info = agency_names.get(prefix)
        if info is None:
            agency = by_slug.get(slug_of(prefix))
            full = agency["name"].strip() if agency else prefix
            info = {"name": short_name(full) if agency else prefix, "full": full, "see_also": bool(agency and agency.get("see_also"))}
        group = by_prefix.get(prefix, [])
        by_notation = {doc["notation"]: doc for doc in group}
        chapters = [doc for doc in group if doc.get("recordType") == "rule-chapter"]
        chapters.sort(key=lambda doc: rule_sort_key(doc["notation"]))
        items = []
        for chapter in chapters:
            parts = []
            for child in chapter.get("narrower") or []:
                number = child.rstrip("/").rsplit("/", 1)[-1]
                notation = f"{prefix} {number}"
                child_doc = by_notation.get(notation)
                if child_doc is None:
                    continue
                bits = f'<a href="/rules/{slug_of(prefix)}/{html.escape(number, quote=True)}.html">{html.escape(child_doc["prefLabel"])}</a>'
                section_count = len(child_doc.get("narrower") or [])
                if child_doc.get("recordType") == "rule-part" and section_count:
                    bits += f' <span class="note">{section_count} sections</span>'
                parts.append(f"<li>{bits}</li>")
            block = f'<a href="{html.escape(rule_html(chapter["notation"]), quote=True)}">{html.escape(chapter["prefLabel"])}</a>'
            if parts:
                block += "<ul>" + "".join(parts) + "</ul>"
            items.append(f"<li>{block}</li>")
        orphans = []
        for doc in group:
            if doc.get("recordType") == "rule-chapter":
                continue
            broader = doc.get("broader")
            if broader == agency_uri(prefix):
                number = doc["notation"].split(" ", 1)[1]
                orphans.append(
                    f'<li><a href="/rules/{slug_of(prefix)}/{html.escape(number, quote=True)}.html">{html.escape(doc["prefLabel"])}</a></li>'
                )
        body = "<ul>" + "".join(items + orphans) + "</ul>" if (items or orphans) else "<p>No chapters in this snapshot.</p>"
        if info.get("see_also"):
            body = '<p class="note">See-also compilation on the agency list.</p>' + body
        full = info.get("full") or info["name"]
        if full and full != info["name"]:
            body = f"<p>{html.escape(full)}</p>" + body
        counts = (
            f'<p>{sum(1 for doc in group if doc.get("recordType") == "rule-section")} sections, '
            f'{sum(1 for doc in group if doc.get("recordType") == "rule-part")} parts, '
            f'{len(chapters)} chapters.</p>'
        )
        page = page_shell(
            title=f"{prefix} {info['name']}",
            h1=html.escape(f"{prefix} {info['name']}"),
            breadcrumb=f'<a href="/rules/">Administrative rules</a> / {html.escape(prefix)}',
            body=counts + body,
            jsonld=f"/rules/{slug_of(prefix)}/index.jsonld",
            part="",
            extra="",
            provenance=home_provenance(),
            disclaimer=disclaimer_html(rsa_chapters),
        )
        write_text(RULES / slug_of(prefix) / "index.html", page)
        doc = {
            "@context": CONTEXT_URI,
            "@id": agency_uri(prefix),
            "@type": "Concept",
            "prefLabel": f"{prefix} {info['name']}",
            "notation": prefix,
            "inScheme": SCHEME_ID,
            "topConceptOf": SCHEME_ID,
            "recordType": "rule-agency",
            "agencyCode": prefix,
            "definition": full,
            "narrower": [rule_uri(chapter["notation"]) for chapter in chapters],
        }
        if orphans:
            doc["narrower"] = doc["narrower"] + [
                rule_uri(item["notation"])
                for item in group
                if item.get("broader") == agency_uri(prefix) and item.get("recordType") != "rule-chapter"
            ]
        write_text(RULES / slug_of(prefix) / "index.jsonld", dump_json(doc))


def write_scheme(prefixes: list[str]) -> None:
    doc = {
        "@context": CONTEXT_URI,
        "@id": SCHEME_ID,
        "@type": "ConceptScheme",
        "prefLabel": "New Hampshire administrative rules",
        "definition": (
            "Administrative rules compiled by the Office of Legislative Services. "
            "Agencies are the top concepts. Chapters, parts, and sections are narrower. "
            "The inventory is rules/index.json."
        ),
        "hasTopConcept": [agency_uri(prefix) for prefix in prefixes],
    }
    write_text(RULES / "scheme.jsonld", dump_json(doc))


def home_provenance() -> str:
    pin = rules_pin()
    commit = pin["commit"]
    retrieved = pin.get("snapshot") or "2026-11-15"
    blob = f"https://github.com/{SOURCE_REPO}/blob/{commit}/derived/summary.json"
    return (
        f"Source: NH OLS administrative rules compilation, retrieved {html.escape(retrieved)}, "
        f"adm-rules-data@{html.escape(commit[:12])}. "
        f'<a href="{html.escape(blob, quote=True)}">Derived records in adm-rules-data</a>.'
    )


def write_index(prefixes, docs, agencies, by_slug, agency_names, dropped, pin) -> None:
    by_prefix: dict[str, list[dict]] = {}
    for doc in docs:
        by_prefix.setdefault(doc.get("agencyCode") or "", []).append(doc)
    items = []
    for prefix in prefixes:
        info = agency_names.get(prefix) or {"name": prefix}
        group = by_prefix.get(prefix, [])
        sections = sum(1 for doc in group if doc.get("recordType") == "rule-section")
        items.append(
            f'<li><a href="/rules/{slug_of(prefix)}/">{html.escape(prefix)} {html.escape(info["name"])}</a> '
            f'<span class="note">{sections} sections</span></li>'
        )
    empty = [agency for agency in agencies if not agency.get("see_also") and not agency.get("rule_count")]
    empty_html = ""
    if empty:
        rows = "".join(
            f"<li>{html.escape(agency['code'])} — {html.escape(short_name(agency['name']))}</li>" for agency in empty
        )
        empty_html = "<h2>No operative rules in this snapshot</h2><ul>" + rows + "</ul>"
    slices = [agency for agency in agencies if agency.get("see_also") and agency["slug"] not in {slug_of(p) for p in prefixes}]
    slice_html = ""
    if slices:
        rows = "".join(f"<li>{html.escape(agency['code'])} ({html.escape(agency['slug'])})</li>" for agency in slices)
        slice_html = (
            "<h2>Numbered compilations folded into the parent prefix</h2>"
            "<p>He-P 6000, Stra 1100, and Plc 1500, and any similar see-also file, use the parent rule prefix. "
            "Their pages are under that prefix.</p><ul>"
            + rows
            + "</ul>"
        )
    sos = (
        "<h2>Secretary of State</h2>"
        "<p>Secretary of State rules are not in this snapshot. sos.nh.gov returned HTTP 403 "
        "(Akamai Access Denied), so election procedure published only on that site is absent. "
        "On the General Court agency list, Elec is the Electricians' Board. "
        "Ballot Law Commission rules are under <a href=\"/rules/bal/\">Bal</a>.</p>"
        "<p>Cul, the abolished Department of Cultural Resources, returned HTTP 404. "
        "Rec and Rep are repealed tables of contents with no operative sections. "
        "Historical Resources is <a href=\"/rules/cul-h/\">Cul-H</a>.</p>"
    )
    body = (
        "<p>Elec 101.01 is <a href=\"/rules/elec/101.01.html\">/rules/elec/101.01.html</a> "
        "and <a href=\"/rules/elec/101.01.jsonld\">/rules/elec/101.01.jsonld</a>. "
        "The identifier has no file suffix. GitHub Pages does not rewrite a bare path to the HTML file.</p>"
        "<ul>"
        '<li><a href="/rules/index.json">rules/index.json</a></li>'
        '<li><a href="/rules/scheme.jsonld">rules/scheme.jsonld</a></li>'
        '<li><a href="/rules/UNRESOLVED_CITATIONS.md">Unresolved RSA citations</a></li>'
        '<li><a href="/rules/KNOWN_GAPS.md">Gaps and judgment calls</a></li>'
        '<li><a href="/rsa/">Revised Statutes</a></li>'
        '<li><a href="/AGENTS.md">How to look a rule up</a></li>'
        "</ul>"
        + sos
        + "<h2>Agencies</h2><ul>"
        + "".join(items)
        + "</ul>"
        + empty_html
        + slice_html
    )
    rsa_sections, rsa_chapters = load_rsa_catalog()
    page = page_shell(
        title="New Hampshire administrative rules",
        h1="Administrative rules",
        breadcrumb='<a href="/">GraniteState</a>',
        body=body,
        jsonld="/rules/index.json",
        part="<p>Office of Legislative Services compilation. Elec is the Electricians' Board, not elections.</p>",
        extra="",
        provenance=home_provenance(),
        disclaimer=disclaimer_html(rsa_chapters),
    )
    write_text(RULES / "index.html", page)
    section_count = sum(1 for doc in docs if doc.get("recordType") == "rule-section")
    part_count = sum(1 for doc in docs if doc.get("recordType") == "rule-part")
    chapter_count = sum(1 for doc in docs if doc.get("recordType") == "rule-chapter")
    index = {
        "_comment": (
            "Inventory of administrative-rule pages. A rule id such as Elec 101.01 is "
            "https://granitestate.github.io/rules/elec/101.01. Fetch the identifier plus .jsonld. "
            "Humans open the .html file. An agency is the directory /rules/elec/. "
            "RSA authority that has no page in this build is listed in rules/UNRESOLVED_CITATIONS.md. "
            "Secretary of State rules are absent because sos.nh.gov returned HTTP 403."
        ),
        "addressScheme": (
            "Elec 101.01 is https://granitestate.github.io/rules/elec/101.01. "
            "The agency segment is the lowercased rule prefix. The number segment omits the prefix. "
            "RSA 659:21 linked from a rule is https://granitestate.github.io/rsa/659/659-21."
        ),
        "context": CONTEXT_URI,
        "scheme": SCHEME_ID,
        "generatedFrom": {
            "repo": SOURCE_REPO,
            "commit": pin["commit"],
            "commitDate": pin.get("commit_date"),
            "snapshot": pin.get("snapshot"),
            "path": "derived/",
            "note": "Pages link to this commit's files in adm-rules-data. Publisher URLs are text, not links.",
        },
        "counts": {
            "agencies": len(prefixes),
            "chapters": chapter_count,
            "parts": part_count,
            "sections": section_count,
            "rules": len(docs),
            "droppedHeadings": len(dropped),
        },
        "agencies": [
            {
                "code": prefix,
                "name": (agency_names.get(prefix) or {"name": prefix})["name"],
                "html": f"rules/{slug_of(prefix)}/index.html",
                "jsonld": f"rules/{slug_of(prefix)}/index.jsonld",
                "id": agency_uri(prefix),
                "sections": sum(1 for doc in by_prefix.get(prefix, []) if doc.get("recordType") == "rule-section"),
            }
            for prefix in prefixes
        ],
    }
    write_text(RULES / "index.json", dump_json(index))


def write_gaps(dropped, agencies, pin, docs) -> None:
    sample = ", ".join(rule["id"] for rule in dropped[:40])
    lines = [
        "# Gaps in the administrative-rule pages",
        "",
        f"Built from `{SOURCE_REPO}` commit `{pin['commit']}`, snapshot {pin.get('snapshot')}.",
        "The derived files do not invent text. These are the holes left visible.",
        "",
        "## Secretary of State",
        "",
        "sos.nh.gov returned HTTP 403 from Akamai. No Secretary of State compilation was stored.",
        "Election procedure that the Secretary publishes only on that site is not here.",
        "Elec on the General Court list is the Electricians' Board. Bal is the Ballot Law Commission, and those rules are in this build.",
        "",
        "## Agencies with no operative text",
        "",
        "Cul, the abolished Department of Cultural Resources, returned HTTP 404. Cul-H, Historical Resources, is stored.",
        "Rec and Rep are repealed tables of contents. No operative Rec or Rep sections were parsed.",
        "",
        "## Headings that are not rule numbers",
        "",
        f"{len(dropped)} headings had a prefix that is not an agency code (for example And, Cfr, Dssp, Part, Table).",
        "They collide with real rule numbers when the agency slug is reused, and they are not published as pages.",
        "The sentence stays in the previous heading's text.",
        "",
        f"Sample: {sample}.",
        "",
        "## Mec and Saf-Mec",
        "",
        "Mec and Saf-Mec number many of the same sections. They are separate page trees, /rules/mec/ and /rules/saf-mec/, because one path cannot hold both.",
        "The agency list describes Saf-Mec as the earlier numbering of the Mechanical Licensing Board.",
        "",
        "## Slice files",
        "",
        "he-p6000.html, stra1100.html, and plc1500.html are slices of He-P, Stra, and Plc.",
        "Their headings use the parent prefix, so the pages live under /rules/he-p/, /rules/stra/, and /rules/plc/.",
        "",
        "## RSA pages this site does not have",
        "",
        "Authority citations whose RSA section or chapter is not in the current RSA build stay plain text.",
        "They are listed in rules/UNRESOLVED_CITATIONS.md. The RSA build is election law plus sections cited from those pages, not the entire Revised Statutes.",
        "A citation that names a section is not linked to the chapter page.",
        "",
        "## What was not copied from the archive",
        "",
        "Filing-history pages, the Rulemaking Register, and the rules-search detail screens are not pages on this site.",
        "The compilation HTML is the rule text. Provenance links to that file in adm-rules-data at the pinned commit.",
        "Publisher URLs, including gc.nh.gov, are printed as text and are not hrefs.",
        "source_note rows are RSA citations inside a Source. annotation. They are not listed as authority.",
        "Inherited part and chapter authority is listed, and the via label says so.",
        "",
        f"Rule concepts on disk: {len(docs)}.",
        "",
    ]
    write_text(RULES / "KNOWN_GAPS.md", "\n".join(lines))


def write_unresolved(docs: list[dict], rsa_sections: dict, rsa_chapters: dict) -> None:
    counts: dict[str, int] = {}
    for doc in docs:
        for auth in doc.get("authority") or []:
            if auth.get("source"):
                continue
            citation = auth.get("citation")
            if not citation:
                continue
            counts[citation] = counts.get(citation, 0) + 1
    lines = [
        "# Unresolved RSA citations from administrative rules",
        "",
        "An implementing citation (the Authority list, role implements) matched an RSA id and this build has no page for it.",
        "A section citation is not linked to a chapter page. Chapter letters are uppercase and section letters are lowercase.",
        "Source-note citations inside a Source. line are not in this table.",
        "Headings whose prefix is not an agency code are not published and are not listed here.",
        "",
        f"Unresolved RSA ids: {len(counts)}. Citation rows: {sum(counts.values())}.",
        "",
        "| RSA | Rules | Reason |",
        "| --- | --- | --- |",
    ]
    for rsa_id in sorted(counts, key=rsa_sort_key):
        if ":" in rsa_id:
            reason = "section is not in this RSA build"
        else:
            reason = "chapter is not in this RSA build"
        lines.append(f"| {rsa_id} | {counts[rsa_id]} | {reason} |")
    if not counts:
        lines.append("|  |  |  |")
    lines.append("")
    write_text(RULES / "UNRESOLVED_CITATIONS.md", "\n".join(lines))
    index_path = RULES / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index.setdefault("counts", {})
        index["counts"]["unresolvedStatutes"] = len(counts)
        index["counts"]["unresolvedRows"] = sum(counts.values())
        write_text(index_path, dump_json(index))


def sync_rsa(docs: list[dict], rsa_sections: dict, rsa_chapters: dict) -> None:
    by_uri: dict[str, dict[str, dict]] = {}
    for doc in docs:
        for auth in doc.get("authority") or []:
            src = auth.get("source")
            if not src:
                continue
            bucket = by_uri.setdefault(src, {})
            item = bucket.setdefault(
                doc["@id"],
                {"label": doc.get("prefLabel") or doc.get("notation"), "paragraphs": [], "vias": [], "href": rule_href_from_uri(doc["@id"])},
            )
            for para in auth.get("paragraphs") or []:
                if para not in item["paragraphs"]:
                    item["paragraphs"].append(para)
            for via in str(auth.get("via") or "").split(","):
                if via and via not in item["vias"]:
                    item["vias"].append(via)
    targets = []
    for citation, item in rsa_sections.items():
        targets.append((item["id"], ROOT / item["html"], ROOT / item["jsonld"], citation))
    for notation, item in rsa_chapters.items():
        targets.append((item["id"], ROOT / item["html"], ROOT / item["jsonld"], notation))
    updated = 0
    for uri, html_path, jsonld_path, _citation in targets:
        rules = by_uri.get(uri) or {}
        is_section = html_path.name != "index.html"
        if not rules and not is_section:
            continue
        if html_path.is_file():
            text = html_path.read_text(encoding="utf-8")
            replacement = implementing_aside(rules)
            if RSA_ASIDE_RE.search(text):
                new = RSA_ASIDE_RE.sub(replacement, text, count=1)
            elif "  <footer>" in text:
                new = text.replace("  <footer>", "  " + replacement + "\n  <footer>", 1)
            else:
                new = text
            if new != text:
                html_path.write_text(new, encoding="utf-8")
                updated += 1
        if jsonld_path.is_file() and rules:
            doc = json.loads(jsonld_path.read_text(encoding="utf-8"))
            ordered = sorted(rules, key=lambda rule_uri_value: rule_sort_key(notation_from_uri(rule_uri_value)))
            if doc.get("implementedBy") != ordered:
                doc["implementedBy"] = ordered
                jsonld_path.write_text(dump_json(doc), encoding="utf-8")
        elif jsonld_path.is_file() and is_section and "implementedBy" in json.loads(jsonld_path.read_text(encoding="utf-8")):
            doc = json.loads(jsonld_path.read_text(encoding="utf-8"))
            doc.pop("implementedBy", None)
            jsonld_path.write_text(dump_json(doc), encoding="utf-8")
    print(f"updated RSA html blocks on {updated} pages", flush=True)


def rule_href_from_uri(uri: str) -> str:
    rel = uri[len(SITE) :] if uri.startswith(SITE) else uri
    return "/" + rel + ".html"


def notation_from_uri(uri: str) -> str:
    rel = uri.rstrip("/").rsplit("/", 2)
    # rules/elec/101.01 -> Elec is not in the URI. Use the path number and the slug's case later.
    # rule_sort_key needs "Elec 101.01". Recover prefix from the slug by reading is unnecessary
    # if we sort by slug then number. Build a synthetic id from the path.
    path = uri[len(SITE) :] if uri.startswith(SITE) else uri
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "rules":
        slug, number = parts[1], parts[2]
        return f"{slug} {number}"
    return path


def implementing_aside(rules: dict[str, dict]) -> str:
    if not rules:
        inner = ""
    else:
        rows = []
        for uri in sorted(rules, key=lambda value: rule_sort_key(notation_from_uri(value))):
            item = rules[uri]
            bits = []
            if item["paragraphs"]:
                bits.append("paragraphs " + ", ".join(item["paragraphs"]))
            if item["vias"]:
                bits.append("; ".join(VIA_LABEL.get(via, via) for via in item["vias"]))
            note = f' <span class="note">{html.escape("; ".join(bits))}</span>' if bits else ""
            rows.append(
                f'<li><a class="cite-implements" href="{html.escape(item["href"], quote=True)}">{html.escape(item["label"])}</a>{note}</li>'
            )
        inner = "\n      " + "\n      ".join(rows) + "\n    "
    return (
        "<aside>\n    <h2>Implementing rules</h2>\n"
        f"    <ul id=\"implementing-rules\">{inner}</ul>\n  </aside>"
    )


def self_test() -> None:
    html_self_test()
    configure_linker(["Elec", "Saf-Mec", "He-P"])
    sections = {
        "659:21": {"html": "rsa/659/659-21.html", "id": SITE + "rsa/659/659-21"},
        "541-A:16": {"html": "rsa/541-A/541-A-16.html", "id": SITE + "rsa/541-A/541-A-16"},
    }
    chapters = {"541-A": {"id": SITE + "rsa/541-A", "html": "rsa/541-A/index.html"}}
    rules_by_key = {("elec", "101.01"): "Elec 101.01", ("saf-mec", "201.01"): "Saf-Mec 201.01"}
    para_ids = {"Elec 101.01": {"b"}, "Saf-Mec 201.01": set()}
    line = render_line(
        "See Elec 101.01(b) and RSA 659:21 and RSA 999:1 and RSA chapter 541-A.",
        set(),
        rules_by_key,
        para_ids,
        sections,
        chapters,
    )
    assert 'href="/rules/elec/101.01.html#b"' in line, line
    assert 'href="/rsa/659/659-21.html"' in line, line
    assert "RSA 999:1" in line and "999" not in line.split("href")[-1]
    assert 'href="/rsa/541-A/"' in line, line
    assert "http://" not in line and "https://" not in line
    assert authority_label("319-C:6-a", ["II", "V"]) == "RSA 319-C:6-a, II, V"
    assert rule_html("He-P 6001.01") == "/rules/he-p/6001.01.html"
    assert rule_uri("Saf-Mec 201.01") == SITE + "rules/saf-mec/201.01"
    target = rsa_target("659:20-a", {"659:20-a": {"html": "rsa/659/659-20-a.html", "id": SITE + "rsa/659/659-20-a"}}, {})
    assert target is not None and target[0] == "/rsa/659/659-20-a.html"
    assert rsa_target("662-A:1", {}, {}) is None
    chapter_target = rsa_target("326-E", {}, {"326-E": {"id": SITE + "rsa/326-E", "html": "rsa/326-E/index.html"}})
    assert chapter_target is not None and chapter_target[0] == "/rsa/326-E/"
    marked = render_line("(b) Second.", {"b"}, rules_by_key, para_ids, sections, chapters)
    assert 'id="b"' in marked and "(b)" in marked
    print("build_rules self-test ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Checkout of GraniteState/adm-rules-data")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prefixes", help="Comma-separated prefixes to write. Other rule pages stay.")
    parser.add_argument("--skip-rsa", action="store_true", help="Do not rewrite RSA implementing-rule lists.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.source is None:
        raise SystemExit("pass --source or --self-test")
    only = None
    if args.prefixes:
        only = {part.strip() for part in args.prefixes.split(",") if part.strip()}
    build(args.source, only, args.skip_rsa)


if __name__ == "__main__":
    main()
