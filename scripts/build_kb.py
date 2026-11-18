#!/usr/bin/env python3
"""Rebuild kb/ from sources/.

Standard library only. Reads the copies described in sources/provenance.json,
checks their Git blob hashes, and writes the JSON-LD concept schemes, one
file per concept, the indexes, and kb/KNOWN_GAPS.md.

  python3 scripts/build_kb.py
  python3 scripts/build_kb.py --check
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

from kb_common import (
    CONTEXT_URI,
    DISTRICTS_SCHEME,
    PLACES_SCHEME,
    ROOT,
    SITE,
    dump_json,
    fold_label,
    load_json,
)

PLAN_VINTAGE = "2022-2032"
EVENT_ID = "nh-redistricting-2022"

# Office labels are the phrases in sources/sos-voting-districts/README.md.
OFFICE_LABEL = {
    "nh_house": "State House",
    "nh_senate": "State Senate",
    "executive_council": "Executive Council",
    "us_house": "U.S. House",
    "county_commissioner": "County commissioners",
}
OFFICE_SLUG = {
    "nh_house": "nh-house",
    "nh_senate": "nh-senate",
    "executive_council": "executive-council",
    "us_house": "us-house",
    "county_commissioner": "county-commissioner",
}
# Plans whose district membership is in towns.json, keyed by office code.
DISTRICT_PLAN = {
    "nh_house": "2022-nh_house-hb50",
    "nh_senate": "2022-nh_senate-sb240",
    "executive_council": "2022-executive_council-sb241",
    "us_house": "2022-us_house-norelli",
}
# Plan concepts to emit. Commissioner plans have metadata and no members.
PLAN_ORDER = [
    "2022-nh_house-hb50",
    "2022-nh_senate-sb240",
    "2022-executive_council-sb241",
    "2022-us_house-norelli",
    "2022-county_commissioner-hb54",
    "2023-county_commissioner-hb75-strafford",
]
OFFICE_ORDER = [
    "nh_house",
    "nh_senate",
    "executive_council",
    "us_house",
    "county_commissioner",
]

MUNICIPAL_KINDS = ("town", "city", "unincorporated place")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the rebuild with kb/ and do not write",
    )
    args = parser.parse_args()
    files = build(ROOT)
    if args.check:
        return check(files)
    write(files)
    print(f"wrote {len(files)} files under kb/")
    return 0


def build(root: Path) -> dict[str, str]:
    verify_provenance(root)
    towns_doc = load_json(root / "sources/towns.json")
    redistricting = load_json(root / "sources/redistricting.json")
    house_rows = read_csv(root / "sources/sos-voting-districts/house_districts.csv")
    crosswalk = read_csv(root / "sources/sos-voting-districts/town_ward_district_crosswalk.csv")
    mismatches = read_csv(root / "sources/sos-voting-districts/name_mismatches.csv")

    towns: dict = towns_doc["towns"]
    if len(towns) != 259:
        fail(f"towns.json has {len(towns)} municipalities, expected 259")
    plans = load_plans(redistricting)
    check_crosswalk(towns, crosswalk, mismatches, house_rows)

    state_id, counties = place_skeleton(towns)
    concepts: dict[str, dict] = {}
    concepts[state_id] = {
        "@id": state_id,
        "@type": "Concept",
        "recordType": "place",
        "kind": "state",
        "prefLabel": "New Hampshire",
        "notation": [{"@type": "Geoid", "@value": "33"}],
        "geoid": "33",
        "inScheme": PLACES_SCHEME,
        "topConceptOf": PLACES_SCHEME,
        "narrower": sorted(counties.values()),
    }

    districts: dict[str, dict] = {}
    assignments: list[tuple[str, dict]] = []
    no_vtd: list[tuple[str, str, str]] = []
    no_vote_in: list[tuple[str, str]] = []

    for geoid in sorted(towns):
        town = towns[geoid]
        county_id = counties[town["county"]]
        muni_id = SITE + "kb/places/" + geoid
        ward_ids = []
        wards = town.get("wards") or []
        if wards:
            seen_numbers = set()
            for ward in wards:
                number = ward["ward"]
                if number in seen_numbers:
                    fail(f"duplicate ward {number} in {town['name']}")
                seen_numbers.add(number)
                ward_id = f"{muni_id}/ward-{number}"
                ward_ids.append(ward_id)
                concepts[ward_id] = ward_concept(town, ward, muni_id, ward_id)
                assignments.append((ward_id, ward["districts"]["2022"]))
        concepts[muni_id] = municipality_concept(towns, town, muni_id, county_id, ward_ids)
        if not town.get("census_vtd_geoid") and not wards:
            no_vtd.append((town["name"], town["kind"], geoid))
        if town["kind"] == "unincorporated place" and not town.get("vote_in_id"):
            no_vote_in.append((town["name"], geoid))
        if not wards:
            assignments.append((muni_id, town["districts"]["2022"]))

    for county_name, county_id in sorted(counties.items(), key=lambda item: item[1]):
        members = [
            concept_id
            for concept_id, concept in concepts.items()
            if concept.get("kind") in MUNICIPAL_KINDS and concept.get("broader") == county_id
        ]
        concepts[county_id] = {
            "@id": county_id,
            "@type": "Concept",
            "recordType": "place",
            "kind": "county",
            "prefLabel": county_name,
            "notation": [{"@type": "Geoid", "@value": county_id.rsplit("/", 1)[-1]}],
            "geoid": county_id.rsplit("/", 1)[-1],
            "inScheme": PLACES_SCHEME,
            "broader": state_id,
            "narrower": sorted(members),
            "note": "County name as published in the county field of towns.json. GEOID is the five-digit prefix shared by that county's municipality GEOIDs.",
        }

    house_by_name = {row["house_district"]: row for row in house_rows}
    member_lists: dict[str, list[str]] = defaultdict(list)
    precinct_house: dict[str, tuple[str, str | None]] = {}

    for precinct_id, assignment in assignments:
        if assignment.get("plan_vintage") != PLAN_VINTAGE:
            fail(f"{precinct_id} plan_vintage is {assignment.get('plan_vintage')!r}")
        house = assignment["house"]
        bases = [item for item in house if not item["is_floterial"]]
        floterials = [item for item in house if item["is_floterial"]]
        if len(bases) != 1 or len(floterials) > 1:
            fail(f"{precinct_id} has house assignments {house}")
        base_id = house_district_id(bases[0]["district"])
        flo_id = house_district_id(floterials[0]["district"]) if floterials else None
        ensure_house(districts, bases[0], house_by_name, plans)
        member_lists[base_id].append(precinct_id)
        if flo_id:
            ensure_house(districts, floterials[0], house_by_name, plans)
            member_lists[flo_id].append(precinct_id)
        precinct_house[precinct_id] = (base_id, flo_id)

        senate_id = numbered_district_id("nh_senate", assignment["senate"])
        council_id = numbered_district_id("executive_council", assignment["executive_council"])
        congress_id = numbered_district_id("us_house", assignment["congressional"])
        ensure_numbered(districts, "nh_senate", assignment["senate"], plans)
        ensure_numbered(districts, "executive_council", assignment["executive_council"], plans)
        ensure_numbered(districts, "us_house", assignment["congressional"], plans)
        member_lists[senate_id].append(precinct_id)
        member_lists[council_id].append(precinct_id)
        member_lists[congress_id].append(precinct_id)
        concepts[precinct_id]["precinct"] = True
        concepts[precinct_id]["inDistrict"] = sorted(
            [base_id, senate_id, council_id, congress_id] + ([flo_id] if flo_id else [])
        )

    for district_id, members in member_lists.items():
        unique = sorted(set(members))
        if len(unique) != len(members):
            fail(f"{district_id} lists a member more than once")
        districts[district_id]["memberPlace"] = unique
        if districts[district_id]["office"] == "nh_house":
            member_counties = {concepts[member]["countyName"] for member in unique}
            if member_counties != {districts[district_id]["countyName"]}:
                fail(
                    f"{districts[district_id]['prefLabel']} members are in {sorted(member_counties)}"
                )

    flo_to_bases: dict[str, set[str]] = defaultdict(set)
    for base_id, flo_id in precinct_house.values():
        if flo_id:
            flo_to_bases[flo_id].add(base_id)
    for flo_id, base_ids in flo_to_bases.items():
        districts[flo_id]["baseDistrict"] = sorted(base_ids)
        for base_id in base_ids:
            districts[base_id].setdefault("floterialDistrict", []).append(flo_id)
    for district in districts.values():
        if "floterialDistrict" in district:
            district["floterialDistrict"] = sorted(set(district["floterialDistrict"]))

    for district_id, district in districts.items():
        if district["office"] != "nh_house" or not district["floterial"]:
            continue
        union: set[str] = set()
        for base_id in district["baseDistrict"]:
            union.update(districts[base_id]["memberPlace"])
        if union != set(district["memberPlace"]):
            fail(f"{district['prefLabel']} is not the union of its base districts")

    if set(house_by_name) != {d["prefLabel"] for d in districts.values() if d["office"] == "nh_house"}:
        fail("house district names in towns.json and house_districts.csv differ")
    seat_total = sum(d["seats"] for d in districts.values() if d["office"] == "nh_house")
    if seat_total != 400:
        fail(f"house seats sum to {seat_total}, expected 400")

    member_diffs = printed_member_diffs(districts, concepts, house_by_name)
    offices = office_concepts(districts, plans)
    plan_concepts = {plan_id: plan_concept(plans[plan_id]) for plan_id in PLAN_ORDER}

    place_nodes = list(concepts.values())
    district_nodes = list(offices.values()) + list(plan_concepts.values()) + list(districts.values())
    collisions = label_collisions(place_nodes + district_nodes)

    files: dict[str, str] = {}
    files["kb/context.jsonld"] = dump_json(context_document())
    files["kb/vocab.jsonld"] = dump_json(vocab_document())
    place_scheme = scheme_node(
        PLACES_SCHEME,
        "New Hampshire places",
        towns_doc["generated"],
        [state_id],
        place_sources(towns_doc),
        "Places in New Hampshire: the state, the 10 counties, 259 municipalities, and city wards. "
        "skos:broader points at the larger place. Built from nh-elections towns.json. "
        "dcterms:modified is that file's generated date, not a legal effective date. "
        "Census GEOIDs are in notation and geoid. This build does not emit skos:exactMatch.",
    )
    files["kb/schemes/places.jsonld"] = graph_document([place_scheme, *place_nodes])
    district_scheme = scheme_node(
        DISTRICTS_SCHEME,
        "New Hampshire districts (2022-2032)",
        towns_doc["generated"],
        [offices[code]["@id"] for code in OFFICE_ORDER],
        district_sources(towns_doc, plans),
        "Districts for the 2022-2032 plans: State House (base and floterial), State Senate, "
        "Executive Council, and U.S. House, plus plan records for county commissioners. "
        "Membership is copied from the 2022 assignment on each precinct in towns.json. "
        "effectiveDate and firstElection are copied from redistricting.json. "
        "dcterms:modified is the towns.json generated date. "
        "A district links to precincts with memberPlace; a floterial links to its base districts with baseDistrict.",
    )
    files["kb/schemes/districts-2022.jsonld"] = graph_document(
        [district_scheme, *district_nodes]
    )

    for concept in place_nodes + district_nodes:
        files[concept_path(concept["@id"])] = dump_json({"@context": CONTEXT_URI, **concept})

    place_counts = {
        "state": 1,
        "county": sum(1 for c in place_nodes if c["kind"] == "county"),
        "municipality": sum(1 for c in place_nodes if c["kind"] in MUNICIPAL_KINDS),
        "town": sum(1 for c in place_nodes if c["kind"] == "town"),
        "city": sum(1 for c in place_nodes if c["kind"] == "city"),
        "unincorporated place": sum(1 for c in place_nodes if c["kind"] == "unincorporated place"),
        "ward": sum(1 for c in place_nodes if c["kind"] == "ward"),
        "precinct": sum(1 for c in place_nodes if c.get("precinct")),
    }
    house = [d for d in districts.values() if d["office"] == "nh_house"]
    district_counts = {
        "office": len(offices),
        "plan": len(plan_concepts),
        "district": len(districts),
        "nh_house": len(house),
        "nh_house_base": sum(1 for d in house if not d["floterial"]),
        "nh_house_floterial": sum(1 for d in house if d["floterial"]),
        "nh_senate": sum(1 for d in districts.values() if d["office"] == "nh_senate"),
        "executive_council": sum(1 for d in districts.values() if d["office"] == "executive_council"),
        "us_house": sum(1 for d in districts.values() if d["office"] == "us_house"),
        "county_commissioner_district": 0,
        "house_seats": seat_total,
    }
    files["kb/index.json"] = dump_json(index_document(place_nodes, place_counts, district_nodes, district_counts))
    files["kb/names.json"] = dump_json(names_document(place_nodes + district_nodes))
    files["kb/KNOWN_GAPS.md"] = known_gaps(no_vtd, no_vote_in, collisions, member_diffs)
    return files


def verify_provenance(root: Path) -> None:
    provenance = load_json(root / "sources/provenance.json")
    for item in provenance["files"]:
        path = root / item["local_path"]
        if not path.is_file():
            fail(f"missing source {item['local_path']}")
        digest = git_blob_sha1(path.read_bytes())
        if digest != item["blob_sha1"]:
            fail(
                f"{item['local_path']} blob {digest} does not match "
                f"provenance {item['blob_sha1']}"
            )


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_plans(redistricting: dict) -> dict[str, dict]:
    event = next(item for item in redistricting["events"] if item["id"] == EVENT_ID)
    found = {plan["id"]: plan for plan in event["plans"]}
    missing = [plan_id for plan_id in PLAN_ORDER if plan_id not in found]
    if missing:
        fail(f"redistricting event is missing {missing}")
    return found


def check_crosswalk(towns, crosswalk, mismatches, house_rows) -> None:
    sos_alias = {}
    for geoid, town in towns.items():
        for alias in town.get("aliases") or []:
            if alias["source"] == "sos_voting_districts":
                if alias["name"] in sos_alias:
                    fail(f"duplicate SOS alias {alias['name']}")
                sos_alias[alias["name"]] = geoid
    unmatched = [row["municipality"] for row in mismatches if row["reason"] == "no_name_match"]
    if sorted(unmatched) != sorted(sos_alias):
        fail("SOS aliases in towns.json do not match name_mismatches.csv no_name_match rows")

    def unit_key(row: dict[str, str]) -> tuple[str, str]:
        geoid = row["census_cousub_geoid"]
        if not geoid:
            geoid = sos_alias.get(row["municipality"], "")
            if not geoid:
                fail(f"crosswalk row {row['municipality']!r} has no GEOID and no SOS alias")
        return geoid, row["ward"]

    by_unit: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in crosswalk:
        by_unit[unit_key(row)].append(row)

    expected = {}
    for geoid, town in towns.items():
        if town.get("wards"):
            for ward in town["wards"]:
                expected[(geoid, str(ward["ward"]))] = ward["districts"]["2022"]
        else:
            expected[(geoid, "")] = town["districts"]["2022"]
    if set(expected) != set(by_unit):
        fail("towns.json precincts and the SOS crosswalk units differ")

    for key, assignment in expected.items():
        rows = by_unit[key]
        senate = {row["senate_district"] for row in rows}
        council = {row["council_district"] for row in rows}
        congress = {row["congressional_district"] for row in rows}
        if len(senate) != 1 or len(council) != 1 or len(congress) != 1:
            fail(f"crosswalk unit {key} disagrees with itself")
        if (
            str(assignment["senate"]) != senate.pop()
            or str(assignment["executive_council"]) != council.pop()
            or str(assignment["congressional"]) != congress.pop()
        ):
            fail(f"crosswalk unit {key} disagrees with towns.json on senate, council, or congress")
        from_towns = {(item["district"], bool(item["is_floterial"]), int(item["seats"])) for item in assignment["house"]}
        from_csv = {
            (row["house_district"], row["is_floterial"] == "true", int(row["house_seats"]))
            for row in rows
        }
        if from_towns != from_csv:
            fail(f"crosswalk unit {key} disagrees with towns.json on house districts")

    from_towns_names = set()
    flags = {}
    for assignment in expected.values():
        for item in assignment["house"]:
            from_towns_names.add(item["district"])
            flags[item["district"]] = (bool(item["is_floterial"]), int(item["seats"]))
    if from_towns_names != {row["house_district"] for row in house_rows}:
        fail("house_districts.csv names differ from towns.json")
    for row in house_rows:
        floterial, seats = flags[row["house_district"]]
        if floterial != (row["is_floterial"] == "true") or seats != int(row["house_seats"]):
            fail(f"{row['house_district']} seats or floterial flag disagree")


def place_skeleton(towns: dict) -> tuple[str, dict[str, str]]:
    prefixes: dict[str, set[str]] = defaultdict(set)
    for geoid, town in towns.items():
        if len(geoid) != 10 or not geoid.isdigit() or not geoid.startswith("33"):
            fail(f"unexpected GEOID {geoid}")
        prefixes[town["county"]].add(geoid[:5])
    if len(prefixes) != 10:
        fail(f"expected 10 counties, found {sorted(prefixes)}")
    counties = {}
    for name, geos in prefixes.items():
        if len(geos) != 1:
            fail(f"county {name} has GEOID prefixes {sorted(geos)}")
        counties[name] = SITE + "kb/places/" + next(iter(geos))
    return SITE + "kb/places/33", counties


def municipality_concept(towns: dict, town: dict, muni_id: str, county_id: str, ward_ids: list[str]) -> dict:
    aliases = town.get("aliases") or []
    alt: list[str] = []
    for alias in aliases:
        if alias["name"] != town["name"] and alias["name"] not in alt:
            alt.append(alias["name"])
    notation = [
        {"@type": "Geoid", "@value": town["census_cousub_geoid"]},
        {"@type": "GranitId", "@value": str(town["granit_town_id"])},
    ]
    concept = {
        "@id": muni_id,
        "@type": "Concept",
        "recordType": "place",
        "kind": town["kind"],
        "prefLabel": town["name"],
        "notation": notation,
        "geoid": town["census_cousub_geoid"],
        "granitId": str(town["granit_town_id"]),
        "countyName": town["county"],
        "censusNamelsad": town["census_namelsad"],
        "inScheme": PLACES_SCHEME,
        "broader": county_id,
    }
    if alt:
        concept["altLabel"] = alt
    if town.get("granit_district"):
        concept["granitDistrict"] = town["granit_district"]
    if town.get("census_vtd_geoid"):
        notation.append({"@type": "CensusVtdGeoid", "@value": town["census_vtd_geoid"]})
        concept["censusVtdGeoid"] = town["census_vtd_geoid"]
        concept["censusVtdCode"] = town["census_vtd_code"]
        concept["censusVtdName"] = town["census_vtd_name"]
    if ward_ids:
        concept["narrower"] = sorted(ward_ids, key=ward_sort_key)
    if town.get("vote_in_id") or town.get("vote_in"):
        host = towns.get(town.get("vote_in_id"))
        if host is None or host["name"] != town.get("vote_in"):
            fail(f"{town['name']} vote_in {town.get('vote_in')!r} does not match {town.get('vote_in_id')}")
        concept["voteIn"] = SITE + "kb/places/" + town["vote_in_id"]
    note = concept_note(town)
    if note:
        concept["note"] = note
    return concept


def ward_concept(town: dict, ward: dict, muni_id: str, ward_id: str) -> dict:
    if "granit_district" not in ward or "census_vtd_geoid" not in ward:
        fail(f"{town['name']} ward {ward.get('ward')} is missing GRANIT or VTD ids")
    concept = {
        "@id": ward_id,
        "@type": "Concept",
        "recordType": "place",
        "kind": "ward",
        "prefLabel": ward["granit_district"],
        "notation": [{"@type": "CensusVtdGeoid", "@value": ward["census_vtd_geoid"]}],
        "geoid": ward["census_vtd_geoid"],
        "municipalityGeoid": town["census_cousub_geoid"],
        "wardNumber": ward["ward"],
        "countyName": town["county"],
        "granitDistrict": ward["granit_district"],
        "censusVtdGeoid": ward["census_vtd_geoid"],
        "censusVtdCode": ward["census_vtd_code"],
        "censusVtdName": ward["census_vtd_name"],
        "inScheme": PLACES_SCHEME,
        "broader": muni_id,
    }
    if ward["census_vtd_name"] != ward["granit_district"]:
        concept["altLabel"] = [ward["census_vtd_name"]]
    return concept


def concept_note(town: dict) -> str | None:
    parts = []
    if town.get("_comment"):
        parts.append(town["_comment"].strip())
    aliases = town.get("aliases") or []
    if aliases:
        rendered = "; ".join(f"{alias['name']} ({alias['source']})" for alias in aliases)
        parts.append(f"Aliases: {rendered}.")
    if town.get("vote_in_id"):
        parts.append(f"Votes in {town['vote_in']} ({town['vote_in_id']}).")
    return "\n\n".join(parts) or None


def house_district_id(name: str) -> str:
    county, number = name.rsplit(" ", 1)
    if not county.isalpha() or not number.isdigit():
        fail(f"unexpected house district name {name!r}")
    slug = f"{county.casefold()}-{int(number)}"
    return SITE + "kb/districts/2022/nh-house/" + slug


def numbered_district_id(office: str, number: int) -> str:
    return SITE + f"kb/districts/2022/{OFFICE_SLUG[office]}/{int(number)}"


def plan_uri(plan_id: str) -> str:
    return SITE + "kb/districts/2022/plan/" + plan_id


def office_uri(office: str) -> str:
    return SITE + "kb/districts/2022/office/" + OFFICE_SLUG[office]


def district_dates(plan: dict) -> dict:
    extra = {
        "plan": plan_uri(plan["id"]),
        "effectiveDate": plan["dates"]["effective"],
        "firstElection": {
            "primary": plan["first_election"]["primary"],
            "general": plan["first_election"]["general"],
        },
        "planVintage": PLAN_VINTAGE,
    }
    if plan.get("unconfirmed"):
        extra["unconfirmed"] = list(plan["unconfirmed"])
    return extra


def ensure_house(districts: dict, item: dict, house_by_name: dict, plans: dict) -> None:
    name = item["district"]
    district_id = house_district_id(name)
    if district_id in districts:
        return
    row = house_by_name[name]
    plan = plans[DISTRICT_PLAN["nh_house"]]
    districts[district_id] = {
        "@id": district_id,
        "@type": "Concept",
        "recordType": "district",
        "prefLabel": name,
        "notation": name,
        "inScheme": DISTRICTS_SCHEME,
        "broader": office_uri("nh_house"),
        "office": "nh_house",
        "countyName": row["county"],
        "floterial": bool(item["is_floterial"]),
        "seats": int(item["seats"]),
        "printedMembers": row["members"],
        **district_dates(plan),
    }


def ensure_numbered(districts: dict, office: str, number: int, plans: dict) -> None:
    district_id = numbered_district_id(office, number)
    if district_id in districts:
        return
    plan = plans[DISTRICT_PLAN[office]]
    label = f"{OFFICE_LABEL[office]} {int(number)}"
    districts[district_id] = {
        "@id": district_id,
        "@type": "Concept",
        "recordType": "district",
        "prefLabel": label,
        "notation": str(int(number)),
        "inScheme": DISTRICTS_SCHEME,
        "broader": office_uri(office),
        "office": office,
        **district_dates(plan),
    }


def office_concepts(districts: dict, plans: dict) -> dict[str, dict]:
    by_office: dict[str, list[str]] = defaultdict(list)
    for district in districts.values():
        by_office[district["office"]].append(district["@id"])
    concepts = {}
    for office in OFFICE_ORDER:
        concept = {
            "@id": office_uri(office),
            "@type": "Concept",
            "recordType": "office",
            "prefLabel": OFFICE_LABEL[office],
            "notation": office,
            "inScheme": DISTRICTS_SCHEME,
            "topConceptOf": DISTRICTS_SCHEME,
            "hasPlan": [plan_uri(plan["id"]) for plan in plans_for_office(plans, office)],
        }
        narrower = sorted(by_office.get(office, []))
        if narrower:
            concept["narrower"] = narrower
        if office == "county_commissioner":
            concept["note"] = (
                "Office code county_commissioner from redistricting.json. "
                "The inputs record the plans and not the member towns, so this build emits no district concepts."
            )
        elif office == "nh_house":
            concept["note"] = (
                "Office code nh_house. District names, seats, and the floterial flag come from the 2022 house assignment. "
                "A floterial district overlaps two or more base districts."
            )
        else:
            concept["note"] = f"Office code {office}. District numbers come from the 2022 assignment on each precinct."
        concepts[office] = concept
    return concepts


def plans_for_office(plans: dict, office: str) -> list[dict]:
    selected = [plans[plan_id] for plan_id in PLAN_ORDER if plans[plan_id]["office"] == office]
    return selected


def plan_concept(plan: dict) -> dict:
    concept = {
        "@id": plan_uri(plan["id"]),
        "@type": "Concept",
        "recordType": "plan",
        "prefLabel": plan["id"],
        "notation": plan["id"],
        "planId": plan["id"],
        "inScheme": DISTRICTS_SCHEME,
        "office": plan["office"],
        "authorityType": plan["authority_type"],
        "citation": plan["citation"],
        "status": plan["status"],
        "usedInElection": plan["used_in_election"],
        "districtsEmitted": plan["office"] in DISTRICT_PLAN and plan["id"] == DISTRICT_PLAN[plan["office"]],
        "source": list(plan["source_urls"]),
    }
    if plan["dates"]["effective"]:
        concept["effectiveDate"] = plan["dates"]["effective"]
    primary = plan["first_election"]["primary"]
    general = plan["first_election"]["general"]
    if primary or general:
        election = {}
        if primary:
            election["primary"] = primary
        if general:
            election["general"] = general
        concept["firstElection"] = election
    if plan.get("unconfirmed"):
        concept["unconfirmed"] = list(plan["unconfirmed"])
    if plan.get("bill"):
        concept["bill"] = plan["bill"]
    if plan.get("superseded_by"):
        target = plan["superseded_by"]
        if not isinstance(target, str) or target not in PLAN_ORDER:
            fail(f"plan {plan['id']} superseded_by {target!r} is not a single emitted plan")
        concept["supersededBy"] = plan_uri(target)
    if plan.get("_comment"):
        concept["note"] = plan["_comment"].strip()
    if not concept["districtsEmitted"]:
        concept["definition"] = (
            "Plan record only. Member towns are not in the inputs, so this build emits no district concepts."
        )
    return concept


def printed_member_diffs(districts, concepts, house_by_name) -> list[dict]:
    diffs = []
    for district in sorted(districts.values(), key=lambda item: item["prefLabel"]):
        if district["office"] != "nh_house":
            continue
        printed = [part.strip() for part in house_by_name[district["prefLabel"]]["members"].split(";") if part.strip()]
        canonical = [concepts[member]["prefLabel"] for member in district["memberPlace"]]
        if len(printed) != len(canonical):
            fail(
                f"{district['prefLabel']} printed member count {len(printed)} "
                f"!= linked places {len(canonical)}"
            )
        if {fold_label(part) for part in printed} == {fold_label(part) for part in canonical}:
            continue
        diffs.append(
            {
                "district": district["prefLabel"],
                "printed": printed,
                "linked": canonical,
            }
        )
    return diffs


def label_collisions(nodes: list[dict]) -> list[tuple[str, list[dict]]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for concept in nodes:
        seen = set()
        for label, role in iter_labels(concept):
            key = (fold_label(label), concept["@id"], role)
            if key in seen:
                continue
            seen.add(key)
            buckets[fold_label(label)].append(
                {"id": concept["@id"], "label": label, "role": role}
            )
    collisions = []
    for folded, entries in buckets.items():
        ids = {entry["id"] for entry in entries}
        if len(ids) > 1:
            collisions.append((folded, entries))
    collisions.sort(key=lambda item: item[0])
    return collisions


def iter_labels(concept: dict):
    yield concept["prefLabel"], "prefLabel"
    for label in concept.get("altLabel") or []:
        yield label, "altLabel"
    for key in ("censusNamelsad", "granitDistrict", "censusVtdName"):
        if concept.get(key):
            yield concept[key], key


def scheme_node(scheme_id, label, modified, top, sources, note) -> dict:
    return {
        "@id": scheme_id,
        "@type": "ConceptScheme",
        "prefLabel": label,
        "modified": modified,
        "hasTopConcept": top if len(top) > 1 else top[0],
        "source": sources,
        "note": note,
    }


def place_sources(towns_doc: dict) -> list[str]:
    return [item["url"] for item in towns_doc["sources"]]


def district_sources(towns_doc: dict, plans: dict) -> list[str]:
    urls = []
    for item in towns_doc["sources"]:
        if item["url"] not in urls:
            urls.append(item["url"])
    for plan_id in PLAN_ORDER:
        for url in plans[plan_id]["source_urls"]:
            if url not in urls:
                urls.append(url)
    return urls


def graph_document(nodes: list[dict]) -> str:
    body = {
        "@context": CONTEXT_URI,
        "@graph": sorted(nodes, key=lambda node: node["@id"]),
    }
    return dump_json(body)


def concept_path(uri: str) -> str:
    if not uri.startswith(SITE):
        fail(f"concept URI is not on this site: {uri}")
    return uri[len(SITE) :] + ".jsonld"


def ward_sort_key(uri: str):
    parent, _, number = uri.rpartition("/ward-")
    return parent, int(number)


def index_document(place_nodes, place_counts, district_nodes, district_counts) -> dict:
    return {
        "_comment": (
            "Entry point for the GraniteState knowledge base. "
            "A concept URI has no file suffix. Fetch the same path with .jsonld appended. "
            "Example: https://granitestate.github.io/kb/places/3300101060 "
            "is the file kb/places/3300101060.jsonld. "
            "A scheme URI returns a @graph of the scheme and every concept in it. "
            "names.json folds labels for lookup. Read AGENTS.md before querying."
        ),
        "base": SITE + "kb/",
        "context": CONTEXT_URI,
        "vocab": SITE + "kb/vocab",
        "names": SITE + "kb/names.json",
        "gaps": SITE + "kb/KNOWN_GAPS.md",
        "schemes": [
            {
                "id": PLACES_SCHEME,
                "file": "kb/schemes/places.jsonld",
                "prefLabel": "New Hampshire places",
                "concepts": len(place_nodes),
                "counts": place_counts,
            },
            {
                "id": DISTRICTS_SCHEME,
                "file": "kb/schemes/districts-2022.jsonld",
                "prefLabel": "New Hampshire districts (2022-2032)",
                "concepts": len(district_nodes),
                "counts": district_counts,
            },
        ],
    }


def names_document(nodes: list[dict]) -> dict:
    by_label: dict[str, list[dict]] = defaultdict(list)
    by_geoid: dict[str, str] = {}
    by_granit: dict[str, str] = {}
    for concept in nodes:
        seen = set()
        for label, role in iter_labels(concept):
            marker = (label, role)
            if marker in seen:
                continue
            seen.add(marker)
            entry = {"id": concept["@id"], "label": label, "role": role}
            bucket = by_label[fold_label(label)]
            if entry not in bucket:
                bucket.append(entry)
        if concept.get("recordType") == "place" and concept.get("geoid"):
            geoid = concept["geoid"]
            if geoid in by_geoid and by_geoid[geoid] != concept["@id"]:
                fail(f"GEOID {geoid} is used by two concepts")
            by_geoid[geoid] = concept["@id"]
            if concept.get("censusVtdGeoid") and concept["censusVtdGeoid"] != geoid:
                vtd = concept["censusVtdGeoid"]
                if vtd in by_geoid and by_geoid[vtd] != concept["@id"]:
                    fail(f"VTD GEOID {vtd} is used by two concepts")
                by_geoid[vtd] = concept["@id"]
        if concept.get("granitId"):
            granit_id = concept["granitId"]
            if granit_id in by_granit and by_granit[granit_id] != concept["@id"]:
                fail(f"GRANIT id {granit_id} is used by two concepts")
            by_granit[granit_id] = concept["@id"]
    for bucket in by_label.values():
        bucket.sort(key=lambda entry: (entry["id"], entry["role"], entry["label"]))
    return {
        "_comment": (
            "Lookup for place and district concepts. byFoldedLabel keys are "
            "fold_label(label): casefold, Unicode apostrophes to ASCII apostrophe, "
            "collapsed whitespace. Abbreviations are not expanded and '&' is not "
            "changed to 'and'. A key can point at more than one concept; "
            "the Census alias 'Beans' is both Bean's Grant and Bean's Purchase. "
            "Roles are prefLabel, altLabel, censusNamelsad, granitDistrict, and censusVtdName. "
            "byGeoid covers the state prefix 33, the five-digit county GEOIDs, "
            "the 10-digit county-subdivision GEOIDs, and Census VTD GEOIDs. "
            "byGranitId covers municipal GRANIT town ids. Wards do not have a separate GRANIT town id."
        ),
        "fold": "casefold; apostrophes U+2019 U+2018 U+02BC U+2032 to ASCII apostrophe; collapse whitespace",
        "byFoldedLabel": dict(by_label),
        "byGeoid": by_geoid,
        "byGranitId": by_granit,
    }


def known_gaps(no_vtd, no_vote_in, collisions, member_diffs) -> str:
    no_vtd_lines = "\n".join(
        f"- {name} ({kind}, `{geoid}`)" for name, kind, geoid in sorted(no_vtd)
    )
    no_vote_lines = "\n".join(f"- {name} (`{geoid}`)" for name, geoid in sorted(no_vote_in))
    if collisions:
        collision_lines = []
        for folded, entries in collisions:
            rendered = ", ".join(
                f"{entry['label']} ({entry['role']}, `{entry['id']}`)" for entry in entries
            )
            collision_lines.append(f"- `{folded}`: {rendered}")
        collision_block = "\n".join(collision_lines)
    else:
        collision_block = "- None."
    if member_diffs:
        diff_blocks = []
        for diff in member_diffs:
            printed = "; ".join(diff["printed"])
            linked = "; ".join(diff["linked"])
            diff_blocks.append(
                f"- **{diff['district']}.** Printed: {printed}. Linked prefLabels: {linked}."
            )
        diff_block = "\n".join(diff_blocks)
    else:
        diff_block = "- None."
    return f"""# Known gaps

Unresolved values are listed here instead of being guessed. Judgment calls say how a link was derived when the inputs did not contain that link as its own field.

## Unresolved

### No Census URI for skos:exactMatch

Municipality identifiers in `towns.json` are 10-digit Census county-subdivision GEOIDs. Wards and some municipalities also have `census_vtd_geoid`. The state concept uses `33` and each county concept uses the five-digit prefix shared by its municipalities. None of the inputs contain an HTTP URI for those GEOIDs, so this build does not emit `exactMatch` or `closeMatch`. The GEOID is in `notation` (typed `Geoid` or `CensusVtdGeoid`) and in `geoid`.

### County commissioner districts

`redistricting.json` includes two used plans:

- `2022-county_commissioner-hb54`, effective 2022-02-24, first election primary 2022-09-13 and general 2022-11-08. `superseded_by` is `2023-county_commissioner-hb75-strafford`. The plan comment says Strafford stayed at large under this act and the other counties are still current.
- `2023-county_commissioner-hb75-strafford`, effective 2023-10-03, first election primary 2024-09-10 and general 2024-11-05. The plan comment says this created three Strafford County commissioner districts. `unconfirmed` lists `first_election.primary`.

`towns.json` district assignments have house, senate, executive council, and congressional values only. The SOS derived CSVs have those same offices and no commissioner column. This build emits the two plan concepts and a county-commissioner office concept. It emits no commissioner district concepts and no `memberPlace` links for them.

### No Census voting district in the driver

These municipalities have no `census_vtd_geoid` in `towns.json`. The value was left empty. Berlin and Derry are whole municipalities in the SOS list. Every unincorporated place in the roster is in this list.

{no_vtd_lines}

### Unincorporated places with no vote_in host

`vote_in` is present only when the 2026 ballot-type lists name a host municipality. These unincorporated places have no `vote_in` and no `vote_in_id`. Nothing was filled in.

{no_vote_lines}

### No GRANIT id for the state or the counties

`granit_town_id` is present on all 259 municipalities. Wards have `granit_district` and a Census VTD id, not a separate GRANIT town id. The state and county concepts have no GRANIT id in the inputs.

### first_election dates marked unconfirmed

Each 2022 plan used here lists `first_election` in `unconfirmed`, except `2023-county_commissioner-hb75-strafford`, which lists `first_election.primary`. The dates are copied onto the plan concept and onto each district of that plan, together with the same `unconfirmed` list. `effectiveDate` is `dates.effective`, which those plans do not list as unconfirmed.

## Judgment calls

### memberPlace, not skos:related

A district links to its member precincts with `memberPlace`. The precinct links back with `inDistrict`. The validator checks that the two are inverses. `skos:related` is symmetric and would not record which concept is the district.

Precincts are towns, unincorporated places, wards, and a city that the SOS lists without wards (Berlin). The 12 cities that have wards are not precincts; their wards are. That follows the towns.json comment: for those cities, district assignments are on each ward.

### voteIn, not skos:related

An unincorporated place with `vote_in` and `vote_in_id` links to that host municipality with `voteIn`. The host's name matches `vote_in`. The link is directional, so it is not `skos:related`.

### baseDistrict

`baseDistrict` on a floterial is the set of base State House districts that share at least one member precinct. In this plan that set's members are exactly the floterial's members: every floterial is the union of its base districts. `floterialDistrict` on a base district is the inverse. Neither property is a column in the inputs. The validator checks the inverse and the union.

### State and county identifiers

The state GEOID `33` is the two-digit prefix of every municipality GEOID. A county GEOID is the five-digit prefix shared by the municipalities whose `county` field is that name. The county `prefLabel` is that field with no " County" suffix added. The state `prefLabel` is "New Hampshire", the name used in the redistricting.json comments.

### Numbered district labels

State House `prefLabel` values are the source strings, such as `Belknap 1`. Senate, Executive Council, and U.S. House labels are composed as the office phrase from the SOS voting-districts README table plus the district number on the precinct (`State Senate 6`, `Executive Council 1`, `U.S. House 1`). The number alone is `notation`.

### Ward labels

A ward's `prefLabel` is its `granit_district` (`Laconia Ward 1`). `census_vtd_name` is an `altLabel` when it differs. The URI is `https://granitestate.github.io/kb/places/<municipality geoid>/ward-<n>` using the ward number from towns.json.

### Printed House member lists

`printedMembers` is the `members` string from `house_districts.csv`. Links use the towns.json GEOID. The printed list and the linked `prefLabel`s differ, after the name fold, for:

{diff_block}

### Folded labels that match more than one concept

{collision_block}

### Eleven abbreviated SOS names

`name_mismatches.csv` leaves eleven Coos unincorporated places unmatched. `towns.json` already stores the SOS spelling as an alias and the GRANIT id and Census GEOID from that file's one-for-one leftovers. The generator checks that each `no_name_match` name is one of those aliases and that the crosswalk's district numbers match `towns.json`. It does not choose a new match.

### Ballot types and poll books

`towns.json` carries `ballot_type` and `electronic_poll_book` for 2026. They are not properties of these concepts. See AGENTS.md.

### Fetching an identifier

Concept URIs have no `.jsonld` suffix. GitHub Pages serves the file at the same path plus `.jsonld` and does not rewrite the bare identifier to that file.
"""


def vocab_document() -> dict:
    return {
        "@context": CONTEXT_URI,
        "prefLabel": "GraniteState vocabulary",
        "definition": (
            "Project terms for this knowledge base. "
            "A term identifier is https://granitestate.github.io/kb/vocab# plus the local name, "
            "for example https://granitestate.github.io/kb/vocab#geoid. "
            "The JSON-LD context that maps short keys to these terms is kb/context.jsonld. "
            "RSA statute terms are listed in note."
        ),
        "note": [
            "catchline: the section heading, including the RSA number and without the trailing dash.",
            "statuteText: the section body. Line breaks follow the source br tags and table rows. HTML whitespace inside a line is collapsed.",
            "historyNote: the source note, verbatim aside from collapsed HTML whitespace.",
            "sessionLaw: one object per session-law citation parsed from the source note or a repeal catchline.",
            "sessionYear: the year of a session law.",
            "sessionChapter: the session-law chapter number, as printed.",
            "sessionSection: the session-law section numbers, as printed.",
            "sessionRemainder: words in the session-law citation that were not a section number or an effective date.",
            "effectiveText: the effective-date phrase as printed, including a time of day when the note gives one.",
            "partHeading: the bold part heading inside a chapter, such as Voting Procedure.",
            "repealed: true when the catchline says the section is repealed.",
            "officialHtml: the raw HTML file in GraniteState/nh-rsa-data at the pinned commit.",
            "combinedWith: another section identifier that shares this source heading.",
            "rsaTitle: the title's Roman numeral, such as LXIII.",
            "agencyCode: the administrative-rule prefix, such as Elec or Saf-Mec.",
            "ruleText: the heading's operative text, from that heading through the Source. note and before the next heading.",
            "authorizedBy: RSA concept the rule implements. source_note citations are not included.",
            "implementedBy: administrative-rule concept that implements this RSA section or chapter.",
            "authority: one object per implementing RSA citation, with citation, via, paragraphs, and source when the RSA page exists.",
            "via: how the implementing citation was found: appendix, statutory_authority, inherited_part, or inherited_chapter.",
            "paragraphs: paragraph markers named in an implementing citation, such as II or I(a). They are not part of the URL.",
            "expirationDate: the expiration date parsed from the Source. note, when that date is still in force.",
            "priorExpiration: an earlier EXPIRES or EXPIRED date that a later adoption in the same Source. note superseded.",
        ],
    }


def context_document() -> dict:
    term = "https://granitestate.github.io/kb/vocab#"
    return {
        "@context": {
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "dcterms": "http://purl.org/dc/terms/",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "gs": term,
            "Concept": "skos:Concept",
            "ConceptScheme": "skos:ConceptScheme",
            "prefLabel": "skos:prefLabel",
            "altLabel": "skos:altLabel",
            "broader": {"@id": "skos:broader", "@type": "@id"},
            "narrower": {"@id": "skos:narrower", "@type": "@id"},
            "related": {"@id": "skos:related", "@type": "@id"},
            "inScheme": {"@id": "skos:inScheme", "@type": "@id"},
            "topConceptOf": {"@id": "skos:topConceptOf", "@type": "@id"},
            "hasTopConcept": {"@id": "skos:hasTopConcept", "@type": "@id"},
            "exactMatch": {"@id": "skos:exactMatch", "@type": "@id"},
            "closeMatch": {"@id": "skos:closeMatch", "@type": "@id"},
            "notation": "skos:notation",
            "definition": "skos:definition",
            "note": "skos:note",
            "source": {"@id": "dcterms:source", "@type": "@id"},
            "created": {"@id": "dcterms:created", "@type": "xsd:date"},
            "modified": {"@id": "dcterms:modified", "@type": "xsd:date"},
            "Geoid": "gs:Geoid",
            "GranitId": "gs:GranitId",
            "CensusVtdGeoid": "gs:CensusVtdGeoid",
            "kind": "gs:kind",
            "geoid": "gs:geoid",
            "granitId": "gs:granitId",
            "floterial": "gs:floterial",
            "effectiveDate": {"@id": "gs:effectiveDate", "@type": "xsd:date"},
            "firstElection": "gs:firstElection",
            "primary": {"@id": "gs:primary", "@type": "xsd:date"},
            "general": {"@id": "gs:general", "@type": "xsd:date"},
            "plan": {"@id": "gs:plan", "@type": "@id"},
            "hasPlan": {"@id": "gs:hasPlan", "@type": "@id"},
            "memberPlace": {"@id": "gs:memberPlace", "@type": "@id"},
            "inDistrict": {"@id": "gs:inDistrict", "@type": "@id"},
            "baseDistrict": {"@id": "gs:baseDistrict", "@type": "@id"},
            "floterialDistrict": {"@id": "gs:floterialDistrict", "@type": "@id"},
            "voteIn": {"@id": "gs:voteIn", "@type": "@id"},
            "supersededBy": {"@id": "gs:supersededBy", "@type": "@id"},
            "recordType": "gs:recordType",
            "office": "gs:office",
            "seats": "gs:seats",
            "planId": "gs:planId",
            "planVintage": "gs:planVintage",
            "citation": "gs:citation",
            "bill": "gs:bill",
            "status": "gs:status",
            "authorityType": "gs:authorityType",
            "unconfirmed": "gs:unconfirmed",
            "usedInElection": "gs:usedInElection",
            "districtsEmitted": "gs:districtsEmitted",
            "precinct": "gs:precinct",
            "censusNamelsad": "gs:censusNamelsad",
            "granitDistrict": "gs:granitDistrict",
            "censusVtdGeoid": "gs:censusVtdGeoid",
            "censusVtdCode": "gs:censusVtdCode",
            "censusVtdName": "gs:censusVtdName",
            "municipalityGeoid": "gs:municipalityGeoid",
            "countyName": "gs:countyName",
            "wardNumber": "gs:wardNumber",
            "printedMembers": "gs:printedMembers",
            "catchline": "gs:catchline",
            "statuteText": "gs:statuteText",
            "historyNote": "gs:historyNote",
            "sessionLaw": "gs:sessionLaw",
            "sessionYear": "gs:sessionYear",
            "sessionChapter": "gs:sessionChapter",
            "sessionSection": "gs:sessionSection",
            "sessionRemainder": "gs:sessionRemainder",
            "effectiveText": "gs:effectiveText",
            "partHeading": "gs:partHeading",
            "repealed": "gs:repealed",
            "officialHtml": {"@id": "gs:officialHtml", "@type": "@id"},
            "combinedWith": {"@id": "gs:combinedWith", "@type": "@id"},
            "rsaTitle": "gs:rsaTitle",
            "agencyCode": "gs:agencyCode",
            "ruleText": "gs:ruleText",
            "authorizedBy": {"@id": "gs:authorizedBy", "@type": "@id"},
            "implementedBy": {"@id": "gs:implementedBy", "@type": "@id"},
            "authority": "gs:authority",
            "via": "gs:via",
            "paragraphs": "gs:paragraphs",
            "expirationDate": {"@id": "gs:expirationDate", "@type": "xsd:date"},
            "priorExpiration": {"@id": "gs:priorExpiration", "@type": "xsd:date"},
        }
    }


def check(files: dict[str, str]) -> int:
    problems = []
    for rel, text in sorted(files.items()):
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"missing {rel}")
            continue
        current = path.read_text(encoding="utf-8")
        if current != text:
            problems.append(f"differs {rel}")
    kb = ROOT / "kb"
    if kb.exists():
        for path in sorted(kb.rglob("*")):
            if path.is_file():
                rel = path.relative_to(ROOT).as_posix()
                if rel not in files:
                    problems.append(f"extra {rel}")
    if problems:
        print("\n".join(problems))
        return 1
    print(f"kb/ matches the rebuild ({len(files)} files)")
    return 0


def write(files: dict[str, str]) -> None:
    kb = ROOT / "kb"
    if kb.exists():
        for path in kb.rglob("*"):
            if path.is_file():
                rel = path.relative_to(ROOT).as_posix()
                if rel not in files:
                    path.unlink()
    for rel, text in files.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if kb.exists():
        for path in sorted(kb.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()


def fail(message: str) -> None:
    raise SystemExit(message)


if __name__ == "__main__":
    sys.exit(main())
