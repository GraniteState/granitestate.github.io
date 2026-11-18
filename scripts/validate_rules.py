#!/usr/bin/env python3
"""Validate administrative-rule pages and the RSA implementing-rule lists.

Standard library only. Does not need the adm-rules-data checkout.

  python3 scripts/validate_rules.py

Checks that every rule JSON-LD file uses the shared context, that authority
links and implementing-rule links resolve and agree, that pages do not link
off the GraniteState hosts, and that no generated file is 100 MiB or larger.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from kb_common import CONTEXT_URI, JSONLD_KEYWORDS, ROOT, SITE, as_ids, resolve_uri, walk_dicts

RULES = ROOT / "rules"
RSA = ROOT / "rsa"
MAX_ERRORS = 40
MAX_BYTES = 100 * 1024 * 1024
HREF_RE = re.compile(r'href="([^"]+)"')
ID_RE = re.compile(r'\sid="([^"]+)"')
AUTHORITY_RE = re.compile(r'<a class="cite-authority" href="([^"]+)"')
IMPLEMENTS_RE = re.compile(r'<a class="cite-implements" href="([^"]+)"')
COMMIT_RE = re.compile(r"https://github\.com/GraniteState/adm-rules-data/blob/([0-9a-f]{40})/")


def main() -> int:
    errors: list[str] = []
    index_path = RULES / "index.json"
    if not index_path.is_file():
        print("rules/index.json is missing")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    context = json.loads((ROOT / "kb/context.jsonld").read_text(encoding="utf-8"))
    allowed = set(context.get("@context") or {}) | JSONLD_KEYWORDS
    pin = json.loads((ROOT / "sources/provenance.json").read_text(encoding="utf-8")).get("rules") or {}
    commit = pin.get("commit") or ""

    documents = load_jsonld(RULES, errors)
    check_keys(documents, allowed, errors)
    check_graph(documents, errors)
    check_inventory(index, documents, errors)
    check_pairs(documents, errors)
    check_html(documents, commit, errors)
    check_unresolved(index, errors)
    check_sizes(errors)
    return finish(errors, index)


def load_jsonld(directory: Path, errors: list[str]) -> dict[Path, dict]:
    documents = {}
    for path in sorted(directory.rglob("*.jsonld")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)} does not parse: {exc}")
            continue
        if isinstance(doc, dict):
            documents[path] = doc
        else:
            errors.append(f"{rel(path)} is not an object")
    return documents


def check_keys(documents: dict[Path, dict], allowed: set[str], errors: list[str]) -> None:
    for path, doc in documents.items():
        if doc.get("@context") != CONTEXT_URI:
            errors.append(f"{rel(path)} does not use {CONTEXT_URI}")
        for node in walk_dicts(doc):
            unknown = sorted(set(node) - allowed)
            if unknown:
                errors.append(f"{rel(path)} has keys outside the context: {', '.join(unknown)}")
                return


def check_graph(documents: dict[Path, dict], errors: list[str]) -> None:
    concepts = {}
    for path, doc in documents.items():
        uri = doc.get("@id")
        if not isinstance(uri, str):
            errors.append(f"{rel(path)} has no @id")
            continue
        concepts[uri] = doc
        resolved = resolve_uri(uri)
        if not isinstance(resolved, Path) or resolved.resolve() != path.resolve():
            errors.append(f"{uri} resolves to {resolved}, file is {rel(path)}")
    for uri, doc in concepts.items():
        for key, inverse in (("broader", "narrower"), ("narrower", "broader")):
            for target in as_ids(doc.get(key)):
                other = concepts.get(target)
                if other is None:
                    errors.append(f"{uri} {key} {target} is not a rule concept")
                    continue
                if uri not in as_ids(other.get(inverse)):
                    errors.append(f"{uri} {key} {target} has no inverse {inverse}")
                    if len(errors) >= MAX_ERRORS:
                        return
        for target in as_ids(doc.get("topConceptOf")):
            scheme = concepts.get(target)
            if scheme is None or uri not in as_ids(scheme.get("hasTopConcept")):
                errors.append(f"{uri} topConceptOf {target} is not reciprocated")
        for target in as_ids(doc.get("hasTopConcept")):
            other = concepts.get(target)
            if other is None or uri not in as_ids(other.get("topConceptOf")):
                errors.append(f"{uri} hasTopConcept {target} is not reciprocated")
                if len(errors) >= MAX_ERRORS:
                    return


def check_inventory(index: dict, documents: dict[Path, dict], errors: list[str]) -> None:
    counts = index.get("counts") or {}
    rules = [
        doc
        for doc in documents.values()
        if str(doc.get("recordType") or "").startswith("rule-") and doc.get("recordType") != "rule-agency"
    ]
    agencies = [doc for doc in documents.values() if doc.get("recordType") == "rule-agency"]
    if counts.get("rules") != len(rules):
        errors.append(f"index counts.rules is {counts.get('rules')} and disk has {len(rules)}")
    if counts.get("agencies") != len(agencies):
        errors.append(f"index counts.agencies is {counts.get('agencies')} and disk has {len(agencies)}")
    levels = {"rule-section": "sections", "rule-part": "parts", "rule-chapter": "chapters"}
    for record_type, key in levels.items():
        found = sum(1 for doc in rules if doc.get("recordType") == record_type)
        if counts.get(key) != found:
            errors.append(f"index counts.{key} is {counts.get(key)} and disk has {found}")
    for agency in index.get("agencies") or []:
        for key in ("html", "jsonld"):
            path = ROOT / agency[key]
            if not path.is_file():
                errors.append(f"{agency.get('code')} is missing {agency[key]}")
    listed = {item.get("code") for item in index.get("agencies") or []}
    on_disk = {doc.get("agencyCode") for doc in agencies}
    if listed != on_disk:
        errors.append(f"agency index does not match disk: {sorted(listed ^ on_disk)[:8]}")


def check_pairs(documents: dict[Path, dict], errors: list[str]) -> None:
    rsa_docs = {}
    for path in RSA.rglob("*.jsonld"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)} does not parse: {exc}")
            continue
        if isinstance(doc, dict) and isinstance(doc.get("@id"), str):
            rsa_docs[doc["@id"]] = doc
    rule_docs = {
        doc["@id"]: doc
        for doc in documents.values()
        if str(doc.get("recordType") or "").startswith("rule-") and doc.get("recordType") != "rule-agency"
    }
    for uri, doc in rule_docs.items():
        for target in as_ids(doc.get("authorizedBy")):
            other = rsa_docs.get(target)
            if other is None:
                errors.append(f"{uri} authorizedBy {target} is not an RSA concept")
                continue
            if uri not in as_ids(other.get("implementedBy")):
                errors.append(f"{uri} authorizedBy {target} is not in implementedBy")
            if len(errors) >= MAX_ERRORS:
                return
        for auth in doc.get("authority") or []:
            if not isinstance(auth, dict):
                errors.append(f"{uri} authority entry is not an object")
                continue
            source = auth.get("source")
            if source and source not in as_ids(doc.get("authorizedBy")):
                errors.append(f"{uri} authority source {source} is missing from authorizedBy")
    for uri, doc in rsa_docs.items():
        for target in as_ids(doc.get("implementedBy")):
            other = rule_docs.get(target)
            if other is None:
                errors.append(f"{uri} implementedBy {target} is not a rule concept")
                continue
            if uri not in as_ids(other.get("authorizedBy")):
                errors.append(f"{uri} implementedBy {target} is not in authorizedBy")
            if len(errors) >= MAX_ERRORS:
                return


def check_html(documents: dict[Path, dict], commit: str, errors: list[str]) -> None:
    by_uri = {doc["@id"]: doc for doc in documents.values() if isinstance(doc.get("@id"), str)}
    for path in sorted(RULES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        ids = set(ID_RE.findall(text))
        if 'id="section"' not in text and path.name != "index.html":
            errors.append(f"{rel(path)} has no id=section")
        for href in HREF_RE.findall(text):
            check_href(path, href, ids, commit, errors)
            if len(errors) >= MAX_ERRORS:
                return
        if path.name == "index.html" and path.parent == RULES:
            if "Secretary of State" not in text or "sos.nh.gov" not in text or "Elec" not in text:
                errors.append("rules/index.html does not describe the Secretary of State gap")
            continue
        if path.name == "index.html":
            continue
        doc = json.loads(path.with_suffix(".jsonld").read_text(encoding="utf-8"))
        linked = {uri_from_site_href(href) for href in AUTHORITY_RE.findall(text)}
        linked.discard(None)
        expected = set(as_ids(doc.get("authorizedBy")))
        if linked != expected:
            errors.append(f"{rel(path)} authority links do not match authorizedBy")
        if "id=\"authority\"" not in text:
            errors.append(f"{rel(path)} has no authority list")
    # RSA section pages reserve the implementing-rules list. Chapter pages
    # carry it when a chapter-level citation has implementing rules.
    for path in sorted(RSA.glob("*/*.html")):
        if path.parent == RSA / "title":
            continue
        text = path.read_text(encoding="utf-8")
        is_section = path.name != "index.html"
        has_list = 'id="implementing-rules"' in text
        jsonld_path = path.with_suffix(".jsonld") if is_section else path.parent / "index.jsonld"
        doc = json.loads(jsonld_path.read_text(encoding="utf-8")) if jsonld_path.is_file() else {}
        implemented = as_ids(doc.get("implementedBy"))
        if is_section and not has_list:
            errors.append(f"{rel(path)} has no implementing-rules list")
        if implemented and not has_list:
            errors.append(f"{rel(path)} has implementedBy and no implementing-rules list")
        if not is_section and not implemented:
            continue
        linked = []
        for href in IMPLEMENTS_RE.findall(text):
            uri = uri_from_site_href(href)
            if uri:
                linked.append(uri)
        if set(linked) != set(implemented):
            errors.append(f"{rel(path)} implementing-rule links do not match implementedBy")
        if len(errors) >= MAX_ERRORS:
            return
        for href in HREF_RE.findall(text):
            if "cite-implements" in text:
                break
        _ = by_uri


def check_href(path: Path, href: str, ids: set[str], commit: str, errors: list[str]) -> None:
    if href.startswith("#"):
        if href[1:] not in ids:
            errors.append(f"{rel(path)} fragment {href} is not in the page")
        return
    document, _hash, fragment = href.partition("#")
    if document.startswith("http://") or document.startswith("https://"):
        if not allowed_host(document):
            errors.append(f"{rel(path)} links outside GraniteState: {href}")
            return
        if "github.com" in urlparse(document).netloc.lower():
            match = COMMIT_RE.search(document)
            if commit and (match is None or match.group(1) != commit):
                errors.append(f"{rel(path)} github link is not pinned to {commit[:12]}: {href}")
        if fragment:
            target = local_target(document)
            if target is None or fragment not in ID_RE.findall(target.read_text(encoding="utf-8")):
                errors.append(f"{rel(path)} fragment {href} does not resolve")
        return
    if document.startswith("/"):
        target = ROOT / document.lstrip("/")
    else:
        target = (path.parent / document).resolve()
    if str(document).endswith("/"):
        target = target / "index.html"
    if not target.is_file():
        errors.append(f"{rel(path)} link does not resolve: {href}")
        return
    if fragment and fragment not in ID_RE.findall(target.read_text(encoding="utf-8")):
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
    if parsed.netloc.lower() not in {"granitestate.github.io", "www.granitestate.github.io"}:
        return None
    path = ROOT / parsed.path.lstrip("/")
    if parsed.path.endswith("/"):
        path = path / "index.html"
    return path if path.is_file() else None


def uri_from_site_href(href: str) -> str | None:
    document = href.split("#", 1)[0]
    if not document.startswith("/"):
        return None
    rel = document[1:]
    if rel.endswith(".html"):
        rel = rel[:-5]
    if rel.endswith("/index"):
        rel = rel[:-6]
    elif rel.endswith("/"):
        rel = rel[:-1]
    return SITE + rel


def check_unresolved(index: dict, errors: list[str]) -> None:
    path = RULES / "UNRESOLVED_CITATIONS.md"
    if not path.is_file():
        errors.append("rules/UNRESOLVED_CITATIONS.md is missing")
        return
    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and not line.startswith("| RSA") and not line.startswith("| ---")
    ]
    expected = (index.get("counts") or {}).get("unresolvedStatutes")
    if expected != len(rows):
        errors.append(f"unresolved statutes {expected} and the table has {len(rows)} rows")
    if not (RULES / "KNOWN_GAPS.md").is_file():
        errors.append("rules/KNOWN_GAPS.md is missing")


def check_sizes(errors: list[str]) -> None:
    for path in RULES.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size >= MAX_BYTES:
            errors.append(f"{rel(path)} is {size} bytes")
        if path.suffix == ".json" and path.stat().st_size < 20:
            continue
        if path.suffix in {".json", ".jsonld", ".md", ".html"}:
            head = path.read_bytes()[:80]
            if head.startswith(b"version https://git-lfs.github.com/spec/"):
                errors.append(f"{rel(path)} is a Git LFS pointer")


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
    print("OK")
    print(
        f"agencies {counts.get('agencies')} rules {counts.get('rules')} "
        f"sections {counts.get('sections')} unresolved {counts.get('unresolvedStatutes')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
