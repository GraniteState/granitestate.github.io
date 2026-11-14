#!/usr/bin/env python3
"""Validate the static JSON-LD knowledge base.

Standard library only. Checks that every JSON-LD file parses, that every
concept URI on this site resolves to a file, that skos:broader and
skos:narrower are symmetric, that the place scheme has 259 municipalities
and 10 counties, and that every State House district has at least one member.

  python3 scripts/validate_kb.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from kb_common import (
    CONTEXT_URI,
    DISTRICTS_SCHEME,
    JSONLD_KEYWORDS,
    KB,
    PLACES_SCHEME,
    ROOT,
    SITE,
    as_ids,
    fold_label,
    resolve_uri,
    walk_dicts,
    walk_strings,
)

REQUIRED_CONTEXT_TERMS = [
    "prefLabel",
    "altLabel",
    "broader",
    "narrower",
    "inScheme",
    "topConceptOf",
    "exactMatch",
    "closeMatch",
    "notation",
    "definition",
    "note",
    "source",
    "created",
    "modified",
    "kind",
    "geoid",
    "granitId",
    "floterial",
    "effectiveDate",
    "firstElection",
    "plan",
    "memberPlace",
]
MUNICIPAL_KINDS = {"town", "city", "unincorporated place"}
MAX_ERRORS = 40


def main() -> int:
    errors: list[str] = []
    documents = load_documents(errors)
    if len(errors) >= MAX_ERRORS:
        return finish(errors)

    context = documents.get(KB / "context.jsonld")
    terms = context_terms(context, errors)
    allowed = terms | JSONLD_KEYWORDS
    for path, doc in documents.items():
        if path.name == "context.jsonld":
            continue
        if path.suffix != ".jsonld":
            continue
        for node in walk_dicts(doc):
            unknown = sorted(set(node) - allowed)
            if unknown:
                errors.append(f"{rel(path)} has keys outside the context: {', '.join(unknown)}")

    check_uris(documents, errors)
    concepts, schemes = collect_concepts(documents, errors)
    check_symmetry(concepts, "broader", "narrower", errors)
    check_symmetry(concepts, "memberPlace", "inDistrict", errors)
    check_symmetry(concepts, "baseDistrict", "floterialDistrict", errors)
    check_top_concepts(concepts, schemes, errors)
    check_places(concepts, errors)
    check_districts(concepts, errors)
    check_index(concepts, errors)
    check_names(concepts, errors)
    return finish(errors, concepts)


def load_documents(errors: list[str]) -> dict[Path, object]:
    documents = {}
    if not KB.is_dir():
        errors.append("kb/ is missing")
        return documents
    paths = sorted(KB.rglob("*"))
    for path in paths:
        if not path.is_file() or path.suffix not in {".json", ".jsonld"}:
            continue
        try:
            documents[path] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)} does not parse: {exc}")
    if KB / "context.jsonld" not in documents:
        errors.append("kb/context.jsonld is missing")
    return documents


def context_terms(context: object, errors: list[str]) -> set[str]:
    if not isinstance(context, dict) or not isinstance(context.get("@context"), dict):
        errors.append("kb/context.jsonld has no @context object")
        return set()
    terms = set(context["@context"])
    missing = [term for term in REQUIRED_CONTEXT_TERMS if term not in terms]
    if missing:
        errors.append("context is missing " + ", ".join(missing))
    return terms


def check_uris(documents: dict[Path, object], errors: list[str]) -> None:
    seen: set[str] = set()
    for path, doc in documents.items():
        for value in walk_strings(doc):
            if not value.startswith(SITE) or value in seen:
                continue
            seen.add(value)
            if resolve_uri(value) is None:
                errors.append(f"{rel(path)} URI does not resolve to a file: {value}")
                if len(errors) >= MAX_ERRORS:
                    return


def collect_concepts(documents: dict[Path, object], errors: list[str]):
    """Return concept bodies and scheme bodies, checking file copies match."""
    copies: dict[str, list[tuple[str, Path, dict]]] = defaultdict(list)
    for path, doc in documents.items():
        if path.suffix != ".jsonld" or not isinstance(doc, dict):
            continue
        if "@graph" in doc:
            if not isinstance(doc["@graph"], list):
                errors.append(f"{rel(path)} @graph is not a list")
                continue
            for node in doc["@graph"]:
                remember(copies, node, "graph", path, errors)
        elif "@id" in doc:
            remember(copies, doc, "file", path, errors)

    concepts = {}
    schemes = {}
    for uri, items in copies.items():
        bodies = [body for _, _, body in items]
        if any(body != bodies[0] for body in bodies[1:]):
            errors.append(f"{uri} has different JSON-LD bodies in {[rel(path) for _, path, _ in items]}")
            continue
        body = bodies[0]
        resolved = resolve_uri(uri)
        kind = body.get("@type")
        if kind == "Concept":
            file_paths = [path for slot, path, _ in items if slot == "file"]
            graph_paths = [path for slot, path, _ in items if slot == "graph"]
            if file_paths != [resolved]:
                errors.append(f"{uri} concept file is { [rel(path) for path in file_paths] }, resolved {resolved}")
            if len(graph_paths) != 1:
                errors.append(f"{uri} is in {len(graph_paths)} scheme graphs")
            concepts[uri] = body
        elif kind == "ConceptScheme":
            if not isinstance(resolved, Path):
                errors.append(f"{uri} scheme does not resolve to a file")
            elif not any(slot == "graph" and path == resolved for slot, path, _ in items):
                errors.append(f"{uri} is not the @graph document at {resolved}")
            schemes[uri] = body
        else:
            errors.append(f"{uri} has @type {kind!r}")
    return concepts, schemes


def remember(copies, node, slot, path, errors) -> None:
    if not isinstance(node, dict) or not isinstance(node.get("@id"), str):
        errors.append(f"{rel(path)} has a node without @id")
        return
    body = {key: value for key, value in node.items() if key != "@context"}
    copies[node["@id"]].append((slot, path, body))


def check_symmetry(concepts: dict, forward: str, inverse: str, errors: list[str]) -> None:
    for uri, concept in concepts.items():
        for target in as_ids(concept.get(forward)):
            if target not in concepts:
                errors.append(f"{uri} {forward} {target} is not a concept")
                continue
            if uri not in as_ids(concepts[target].get(inverse)):
                errors.append(f"{uri} {forward} {target} has no inverse {inverse}")
        for target in as_ids(concept.get(inverse)):
            if target not in concepts:
                errors.append(f"{uri} {inverse} {target} is not a concept")
                continue
            if uri not in as_ids(concepts[target].get(forward)):
                errors.append(f"{uri} {inverse} {target} has no inverse {forward}")


def check_top_concepts(concepts, schemes, errors) -> None:
    for scheme_id, scheme in schemes.items():
        tops = as_ids(scheme.get("hasTopConcept"))
        if not tops:
            errors.append(f"{scheme_id} has no hasTopConcept")
        for top in tops:
            if top not in concepts:
                errors.append(f"{scheme_id} top concept {top} is missing")
                continue
            if scheme_id not in as_ids(concepts[top].get("topConceptOf")):
                errors.append(f"{top} is a top concept without topConceptOf {scheme_id}")
    for uri, concept in concepts.items():
        for scheme_id in as_ids(concept.get("topConceptOf")):
            if scheme_id not in schemes:
                errors.append(f"{uri} topConceptOf {scheme_id} is not a scheme")
                continue
            if uri not in as_ids(schemes[scheme_id].get("hasTopConcept")):
                errors.append(f"{uri} claims topConceptOf {scheme_id} but the scheme does not list it")


def check_places(concepts: dict, errors: list[str]) -> None:
    places = [c for c in concepts.values() if c.get("recordType") == "place"]
    municipalities = [c for c in places if c.get("kind") in MUNICIPAL_KINDS]
    counties = [c for c in places if c.get("kind") == "county"]
    if len(municipalities) != 259:
        errors.append(f"found {len(municipalities)} municipalities, expected 259")
    if len(counties) != 10:
        errors.append(f"found {len(counties)} counties, expected 10")
    states = [c for c in places if c.get("kind") == "state"]
    if len(states) != 1:
        errors.append(f"found {len(states)} state concepts, expected 1")
    for concept in places:
        kind = concept.get("kind")
        wards = [uri for uri in as_ids(concept.get("narrower")) if "/ward-" in uri]
        in_district = as_ids(concept.get("inDistrict"))
        if kind == "ward" or (kind in MUNICIPAL_KINDS and not wards):
            if not concept.get("precinct") or not in_district:
                errors.append(f"{concept['@id']} should be a precinct with inDistrict")
        elif kind == "city" and wards:
            if concept.get("precinct") or in_district:
                errors.append(f"{concept['@id']} is a city with wards and also a precinct")
        elif kind in {"state", "county"} and (concept.get("precinct") or in_district):
            errors.append(f"{concept['@id']} is a {kind} with district membership")
        for host in as_ids(concept.get("voteIn")):
            target = concepts.get(host)
            if target is None or target.get("kind") not in MUNICIPAL_KINDS:
                errors.append(f"{concept['@id']} voteIn {host} is not a municipality")
        if concept.get("inScheme") != PLACES_SCHEME:
            errors.append(f"{concept['@id']} is not in the places scheme")


def check_districts(concepts: dict, errors: list[str]) -> None:
    districts = [c for c in concepts.values() if c.get("recordType") == "district"]
    house = [c for c in districts if c.get("office") == "nh_house"]
    if not house:
        errors.append("no State House districts")
    for concept in house:
        if "floterial" not in concept:
            errors.append(f"{concept['@id']} has no floterial flag")
        if len(as_ids(concept.get("memberPlace"))) < 1:
            errors.append(f"{concept['prefLabel']} has no members")
        if concept.get("floterial"):
            bases = as_ids(concept.get("baseDistrict"))
            if not bases:
                errors.append(f"{concept['prefLabel']} is floterial without baseDistrict")
                continue
            union = set()
            for base in bases:
                target = concepts.get(base)
                if target is None:
                    continue
                union.update(as_ids(target.get("memberPlace")))
            if union != set(as_ids(concept.get("memberPlace"))):
                errors.append(f"{concept['prefLabel']} is not the union of its base districts")
        elif concept.get("baseDistrict"):
            errors.append(f"{concept['prefLabel']} is a base district with baseDistrict")
    for concept in districts:
        if len(as_ids(concept.get("memberPlace"))) < 1:
            errors.append(f"{concept.get('prefLabel')} has no members")
        if concept.get("inScheme") != DISTRICTS_SCHEME:
            errors.append(f"{concept['@id']} is not in the 2022 district scheme")
        for member in as_ids(concept.get("memberPlace")):
            target = concepts.get(member)
            if target is None or not target.get("precinct"):
                errors.append(f"{concept.get('prefLabel')} member {member} is not a precinct")


def check_index(concepts: dict, errors: list[str]) -> None:
    path = KB / "index.json"
    if not path.is_file():
        errors.append("kb/index.json is missing")
        return
    index = json.loads(path.read_text(encoding="utf-8"))
    schemes = {item["id"]: item for item in index.get("schemes", [])}
    place = schemes.get(PLACES_SCHEME)
    district = schemes.get(DISTRICTS_SCHEME)
    if place is None or district is None:
        errors.append("index.json is missing a scheme entry")
        return
    places = [c for c in concepts.values() if c.get("recordType") == "place"]
    expected_place = {
        "state": sum(c.get("kind") == "state" for c in places),
        "county": sum(c.get("kind") == "county" for c in places),
        "municipality": sum(c.get("kind") in MUNICIPAL_KINDS for c in places),
        "town": sum(c.get("kind") == "town" for c in places),
        "city": sum(c.get("kind") == "city" for c in places),
        "unincorporated place": sum(c.get("kind") == "unincorporated place" for c in places),
        "ward": sum(c.get("kind") == "ward" for c in places),
        "precinct": sum(bool(c.get("precinct")) for c in places),
    }
    districts = [c for c in concepts.values() if c.get("recordType") == "district"]
    house = [c for c in districts if c.get("office") == "nh_house"]
    expected_district = {
        "office": sum(c.get("recordType") == "office" for c in concepts.values()),
        "plan": sum(c.get("recordType") == "plan" for c in concepts.values()),
        "district": len(districts),
        "nh_house": len(house),
        "nh_house_base": sum(not c.get("floterial") for c in house),
        "nh_house_floterial": sum(bool(c.get("floterial")) for c in house),
        "nh_senate": sum(c.get("office") == "nh_senate" for c in districts),
        "executive_council": sum(c.get("office") == "executive_council" for c in districts),
        "us_house": sum(c.get("office") == "us_house" for c in districts),
        "county_commissioner_district": sum(c.get("office") == "county_commissioner" for c in districts),
        "house_seats": sum(c.get("seats") or 0 for c in house),
    }
    if place.get("concepts") != len(places) or place.get("counts") != expected_place:
        errors.append(f"index places counts {place.get('counts')} != {expected_place}")
    district_concepts = [
        c for c in concepts.values() if c.get("inScheme") == DISTRICTS_SCHEME and c.get("@type") == "Concept"
    ]
    if district.get("concepts") != len(district_concepts) or district.get("counts") != expected_district:
        errors.append(
            f"index district counts {district.get('counts')} concepts {district.get('concepts')} "
            f"!= {expected_district} ({len(district_concepts)} concepts)"
        )


def check_names(concepts: dict, errors: list[str]) -> None:
    path = KB / "names.json"
    if not path.is_file():
        errors.append("kb/names.json is missing")
        return
    names = json.loads(path.read_text(encoding="utf-8"))
    folded = names.get("byFoldedLabel")
    if not isinstance(folded, dict):
        errors.append("names.json has no byFoldedLabel object")
        return
    present = defaultdict(set)
    for key, entries in folded.items():
        if not isinstance(entries, list):
            errors.append(f"names.json key {key!r} is not a list")
            continue
        for entry in entries:
            uri = entry.get("id")
            label = entry.get("label")
            concept = concepts.get(uri)
            if concept is None:
                errors.append(f"names.json {key!r} points at missing {uri}")
                continue
            if not isinstance(label, str) or fold_label(label) != key:
                errors.append(f"names.json {key!r} does not fold from {label!r}")
                continue
            present[uri].add((label, entry.get("role")))
    for uri, concept in concepts.items():
        expected = set(labels_of(concept))
        if not expected:
            continue
        if uri not in present:
            errors.append(f"{concept.get('prefLabel')} is missing from names.json")
            continue
        missing = expected - present[uri]
        if missing:
            errors.append(f"{concept.get('prefLabel')} labels missing from names.json: {sorted(missing)[:4]}")
    by_geoid = names.get("byGeoid") or {}
    for concept in concepts.values():
        if concept.get("recordType") != "place":
            continue
        for geoid in filter(None, [concept.get("geoid"), concept.get("censusVtdGeoid")]):
            if by_geoid.get(geoid) != concept["@id"]:
                errors.append(f"GEOID {geoid} does not index {concept['@id']}")


def labels_of(concept: dict) -> list[tuple[str, str]]:
    found = [(concept["prefLabel"], "prefLabel")] if concept.get("prefLabel") else []
    for label in concept.get("altLabel") or []:
        found.append((label, "altLabel"))
    for key in ("censusNamelsad", "granitDistrict", "censusVtdName"):
        if concept.get(key):
            found.append((concept[key], key))
    return found


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def finish(errors: list[str], concepts: dict | None = None) -> int:
    if errors:
        print("\n".join(errors[:MAX_ERRORS]))
        if len(errors) > MAX_ERRORS:
            print(f"... {len(errors) - MAX_ERRORS} more")
        print(f"FAILED {len(errors)} error(s)")
        return 1
    places = [c for c in concepts.values() if c.get("recordType") == "place"]
    districts = [c for c in concepts.values() if c.get("recordType") == "district"]
    house = [c for c in districts if c.get("office") == "nh_house"]
    print("OK")
    print(
        f"places: {len(places)} concepts "
        f"({sum(c.get('kind') in MUNICIPAL_KINDS for c in places)} municipalities, "
        f"{sum(c.get('kind') == 'county' for c in places)} counties, "
        f"{sum(c.get('kind') == 'ward' for c in places)} wards, "
        f"{sum(c.get('kind') == 'state' for c in places)} state)"
    )
    print(
        f"districts-2022: {len(districts)} districts "
        f"({len(house)} house, {sum(bool(c.get('floterial')) for c in house)} floterial, "
        f"{sum(c.get('office') == 'nh_senate' for c in districts)} senate, "
        f"{sum(c.get('office') == 'executive_council' for c in districts)} executive council, "
        f"{sum(c.get('office') == 'us_house' for c in districts)} US house)"
    )
    print(f"broader/narrower, memberPlace/inDistrict, and baseDistrict/floterialDistrict are symmetric")
    return 0


if __name__ == "__main__":
    sys.exit(main())
