"""Shared paths and JSON-LD helpers for the knowledge-base scripts.

build_kb.py and validate_kb.py both import this module. The label fold
below is part of the lookup contract documented in AGENTS.md; keep the
two scripts on this one implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "kb"

SITE = "https://granitestate.github.io/"
CONTEXT_URI = SITE + "kb/context.jsonld"
PLACES_SCHEME = SITE + "kb/schemes/places"
DISTRICTS_SCHEME = SITE + "kb/schemes/districts-2022"

JSONLD_KEYWORDS = {"@context", "@id", "@type", "@value", "@graph", "@language"}

# Typographic apostrophes that appear in the SOS and Census spellings.
_APOSTROPHES = {
    "\u2019": "'",  # ’
    "\u2018": "'",  # ‘
    "\u02bc": "'",  # ʼ
    "\u2032": "'",  # ′
}


def fold_label(value: str) -> str:
    """Casefold a label and normalize apostrophes.

    Abbreviations are not expanded, and "&" is not rewritten to "and".
    Those variant spellings are already stored as aliases when the
    driver recorded them.
    """
    for src, dst in _APOSTROPHES.items():
        value = value.replace(src, dst)
    return " ".join(value.casefold().split())


def dump_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def as_ids(value: object) -> list[str]:
    """Normalize a JSON-LD id reference to a list of URI strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict) and isinstance(value.get("@id"), str):
        return [value["@id"]]
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            ids.extend(as_ids(item))
        return ids
    raise TypeError(f"not an id reference: {value!r}")


def resolve_uri(uri: str, root: Path = ROOT) -> Path | None | str:
    """Map a site URI to a file.

    Returns "external" for other hosts, a Path when the URI is this
    site's identifier for a file, or None when it should have been a
    file and was not. Identifiers have no suffix; the file is the same
    path plus .jsonld. A URI that already ends in a real file
    (context.jsonld, for example) resolves to that file.
    """
    if not uri.startswith(SITE):
        return "external"
    document, _hash, _fragment = uri.partition("#")
    rel = document[len(SITE) :]
    if not rel or rel.startswith("/") or any(part == ".." for part in rel.split("/")):
        return None
    if rel.endswith("/"):
        for name in ("index.jsonld", "index.json", "index.html"):
            candidate = root / rel / name
            if candidate.is_file():
                return candidate
        return None
    exact = root / rel
    if exact.is_file():
        return exact
    suffixed = root / (rel + ".jsonld")
    if suffixed.is_file():
        return suffixed
    return None


def walk_strings(node: object):
    if isinstance(node, dict):
        for value in node.values():
            yield from walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_strings(value)
    elif isinstance(node, str):
        yield node


def walk_dicts(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_dicts(value)
