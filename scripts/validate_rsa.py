#!/usr/bin/env python3
"""Validate the generated RSA pages.

Standard library only. Does not need the private HTML scrape.

  python3 scripts/validate_rsa.py

Checks that every JSON-LD file parses, that its keys are in the shared
context, that every section listed in rsa/index.json was emitted, that
every internal link resolves, and that citation counts match the pages.
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from kb_common import CONTEXT_URI, JSONLD_KEYWORDS, ROOT, SITE, as_ids, resolve_uri, walk_dicts

RSA = ROOT / "rsa"
MAX_ERRORS = 40


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("href"):
            self.hrefs.append(values["href"])
        if values.get("id"):
            self.ids.add(values["id"])


def main() -> int:
    errors: list[str] = []
    index_path = RSA / "index.json"
    if not index_path.is_file():
        print("rsa/index.json is missing")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    context = json.loads((ROOT / "kb/context.jsonld").read_text(encoding="utf-8"))
    terms = set(context.get("@context") or {})
    allowed = terms | JSONLD_KEYWORDS

    documents = load_jsonld(errors)
    for path, doc in documents.items():
        if not isinstance(doc, dict):
            errors.append(f"{rel(path)} is not an object")
            continue
        if doc.get("@context") != CONTEXT_URI:
            errors.append(f"{rel(path)} does not use {CONTEXT_URI}")
        for node in walk_dicts(doc):
            unknown = sorted(set(node) - allowed)
            if unknown:
                errors.append(f"{rel(path)} has keys outside the context: {', '.join(unknown)}")

    check_inventory(index, errors)
    check_graph(documents, errors)
    check_html(index, errors)
    check_counts(index, errors)
    return finish(errors, index)


def load_jsonld(errors: list[str]) -> dict[Path, object]:
    documents = {}
    for path in sorted(RSA.rglob("*.jsonld")):
        try:
            documents[path] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)} does not parse: {exc}")
    return documents


def check_inventory(index: dict, errors: list[str]) -> None:
    sections = index.get("sections") or []
    citations = []
    for item in sections:
        citation = item.get("citation")
        citations.append(citation)
        for key in ("html", "jsonld"):
            path = ROOT / item[key]
            if not path.is_file():
                errors.append(f"{citation} is missing {item[key]}")
        jsonld = ROOT / item["jsonld"]
        if jsonld.is_file():
            doc = json.loads(jsonld.read_text(encoding="utf-8"))
            if doc.get("@id") != item.get("id"):
                errors.append(f"{citation} @id is {doc.get('@id')}")
            if doc.get("notation") != citation:
                errors.append(f"{citation} notation is {doc.get('notation')}")
    toc = index.get("tocCitations") or []
    missing = [cite for cite in toc if cite not in set(citations)]
    if missing:
        errors.append(f"TOC sections not emitted: {missing[:12]}")
    emitted = {item["html"] for item in sections}
    for path in RSA.glob("*/*.html"):
        if path.name == "index.html":
            continue
        rel_path = path.relative_to(ROOT).as_posix()
        if rel_path not in emitted:
            errors.append(f"extra section page {rel_path}")
    counts = index.get("counts") or {}
    if counts.get("sections") != len(sections):
        errors.append(f"index counts.sections is {counts.get('sections')} and lists {len(sections)}")


def check_graph(documents: dict[Path, object], errors: list[str]) -> None:
    concepts = {}
    for path, doc in documents.items():
        if not isinstance(doc, dict) or not isinstance(doc.get("@id"), str):
            continue
        concepts[doc["@id"]] = doc
        resolved = resolve_uri(doc["@id"])
        if resolved != path and not (isinstance(resolved, Path) and resolved.resolve() == path.resolve()):
            # Chapter and title identifiers resolve to index.jsonld.
            if not isinstance(resolved, Path) or resolved.resolve() != path.resolve():
                errors.append(f"{doc['@id']} resolves to {resolved}, file is {rel(path)}")
    for uri, doc in concepts.items():
        for key, inverse in (("broader", "narrower"), ("narrower", "broader")):
            for target in as_ids(doc.get(key)):
                if not target.startswith(SITE):
                    continue
                other = concepts.get(target)
                if other is None:
                    errors.append(f"{uri} {key} {target} is not an RSA concept")
                    continue
                if uri not in as_ids(other.get(inverse)):
                    errors.append(f"{uri} {key} {target} has no inverse {inverse}")
        for target in as_ids(doc.get("related")):
            if resolve_uri(target) is None:
                errors.append(f"{uri} related {target} does not resolve")
        for target in as_ids(doc.get("topConceptOf")):
            scheme = concepts.get(target)
            if scheme is None or uri not in as_ids(scheme.get("hasTopConcept")):
                errors.append(f"{uri} topConceptOf {target} is not reciprocated")
        for target in as_ids(doc.get("hasTopConcept")):
            other = concepts.get(target)
            if other is None or target not in concepts or uri not in as_ids(other.get("topConceptOf")):
                errors.append(f"{uri} hasTopConcept {target} is not reciprocated")


def check_html(index: dict, errors: list[str]) -> None:
    internal = 0
    external = 0
    for path in sorted(ROOT.rglob("*.html")):
        parser = LinkParser()
        text = path.read_text(encoding="utf-8")
        parser.feed(text)
        internal += text.count('class="cite-internal"')
        external += text.count('class="cite-external"')
        for href in parser.hrefs:
            check_href(path, href, parser.ids, errors)
            if len(errors) >= MAX_ERRORS:
                return
    if external:
        errors.append(f"found {external} cite-external links; external hosts are not allowed")
    citations = index.get("citations") or {}
    if citations.get("external") not in (0, None):
        errors.append(f"index citations.external is {citations.get('external')}")
    if citations.get("internal") != internal:
        errors.append(f"citation counts internal {citations.get('internal')} but pages have {internal}")


def check_href(path: Path, href: str, ids: set[str], errors: list[str]) -> None:
    if href.startswith("#"):
        if href[1:] not in ids:
            errors.append(f"{rel(path)} fragment {href} is not in the page")
        return
    document, _hash, fragment = href.partition("#")
    if document.startswith("http://") or document.startswith("https://"):
        if not allowed_host(document):
            errors.append(f"{rel(path)} links outside GraniteState: {href}")
            return
        host = urlparse(document).netloc.lower()
        if fragment and host.endswith("granitestate.github.io"):
            target = local_target(document)
            if target is None or not fragment_exists(target, fragment):
                errors.append(f"{rel(path)} fragment {href} does not resolve")
        return
    if document.startswith("/"):
        target = ROOT / document.lstrip("/")
    else:
        target = (path.parent / document).resolve()
    if document.endswith("/"):
        target = target / "index.html"
    if not target.is_file():
        errors.append(f"{rel(path)} link does not resolve: {href}")
        return
    if fragment and not fragment_exists(target, fragment):
        errors.append(f"{rel(path)} fragment {href} is not in {rel(target)}")


def allowed_host(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in {"granitestate.github.io", "www.granitestate.github.io"}:
        return True
    if host == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        return bool(parts) and parts[0].lower() == "granitestate"
    return False


def local_target(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "granitestate.github.io":
        return None
    path = ROOT / parsed.path.lstrip("/")
    if parsed.path.endswith("/"):
        path = path / "index.html"
    return path if path.is_file() else None


def fragment_exists(path: Path, fragment: str) -> bool:
    parser = LinkParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return fragment in parser.ids


def check_counts(index: dict, errors: list[str]) -> None:
    path = RSA / "UNRESOLVED_CITATIONS.md"
    if not path.is_file():
        errors.append("rsa/UNRESOLVED_CITATIONS.md is missing")
        return
    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and not line.startswith("| In section") and not line.startswith("| ---")
    ]
    expected = (index.get("citations") or {}).get("unresolved")
    if expected != len(rows):
        errors.append(f"unresolved count is {expected} and the table has {len(rows)} rows")
    if not (RSA / "KB_LINKS.md").is_file():
        errors.append("rsa/KB_LINKS.md is missing")
    if not (RSA / "GC_AUGMENTATION.md").is_file():
        errors.append("rsa/GC_AUGMENTATION.md is missing")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def finish(errors: list[str], index: dict) -> int:
    if errors:
        print("\n".join(errors[:MAX_ERRORS]))
        if len(errors) > MAX_ERRORS:
            print(f"... {len(errors) - MAX_ERRORS} more")
        print(f"FAILED {len(errors)} error(s)")
        return 1
    counts = index.get("counts") or {}
    citations = index.get("citations") or {}
    print("OK")
    print(
        f"sections {counts.get('sections')} chapters {counts.get('chapters')} titles {counts.get('titles')}"
    )
    print(
        f"citations internal {citations.get('internal')} external {citations.get('external')} "
        f"unresolved {citations.get('unresolved')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
