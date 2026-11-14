# AGENTS.md

How an agent should read the GraniteState knowledge base. The base is static JSON-LD using SKOS. Fetch files over HTTPS. Nothing in this repository is a live query API.

## Start here

1. Read [`kb/index.json`](kb/index.json) for the scheme URIs, file paths, and concept counts.
2. Read [`kb/context.jsonld`](kb/context.jsonld) for the short keys. Project terms use `https://granitestate.github.io/kb/vocab#`. The vocabulary file is [`kb/vocab.jsonld`](kb/vocab.jsonld).
3. Resolve a name, alias, GEOID, or GRANIT town id in [`kb/names.json`](kb/names.json).
4. Fetch the one concept file you need. Fetch a scheme file only when you want the whole graph.

Read [`kb/KNOWN_GAPS.md`](kb/KNOWN_GAPS.md) before treating a missing value as a fact. This version does not guess.

## Identifiers and files

Concept identifiers look like this:

| Concept | Identifier |
| --- | --- |
| State | `https://granitestate.github.io/kb/places/33` |
| County | `https://granitestate.github.io/kb/places/33001` (five-digit GEOID) |
| Municipality | `https://granitestate.github.io/kb/places/3300101060` (10-digit Census county-subdivision GEOID) |
| City ward | `https://granitestate.github.io/kb/places/3300140180/ward-1` |
| State House district | `https://granitestate.github.io/kb/districts/2022/nh-house/belknap-7` |
| State Senate district | `https://granitestate.github.io/kb/districts/2022/nh-senate/6` |
| Executive Council district | `https://granitestate.github.io/kb/districts/2022/executive-council/1` |
| U.S. House district | `https://granitestate.github.io/kb/districts/2022/us-house/1` |
| Plan | `https://granitestate.github.io/kb/districts/2022/plan/2022-nh_house-hb50` |

The identifier has no file suffix. The file is that path plus `.jsonld`. Alton is `kb/places/3300101060.jsonld`, fetched at `https://granitestate.github.io/kb/places/3300101060.jsonld`. GitHub Pages does not rewrite the bare identifier to that file.

A scheme URI returns one document whose `@graph` holds the scheme and every concept in it:

- `kb/schemes/places.jsonld`
- `kb/schemes/districts-2022.jsonld`

`dcterms:modified` on a scheme is the `generated` date of `sources/towns.json`. The legal effective date of a plan is `effectiveDate` on the plan and on each of its districts.

## Look up a town by name or alias

`kb/names.json` has three maps:

- `byFoldedLabel` — labels folded with `casefold`, Unicode apostrophes (`’ ‘ ʼ ′`) replaced by `'`, and whitespace collapsed. Abbreviations are left as written. `&` is not rewritten to `and`.
- `byGeoid` — `33`, the ten county prefixes, the 259 municipality GEOIDs, and Census VTD GEOIDs (wards, and municipalities that have one).
- `byGranitId` — the GRANIT town id on each municipality, as a decimal string with no added zeros (`85` for Alton). Wards, counties, and the state have no GRANIT town id.

Each folded label maps to a list of `{id, label, role}`. Roles are `prefLabel`, `altLabel`, `censusNamelsad`, `granitDistrict`, and `censusVtdName`. `prefLabel` is the `name` in `towns.json` (the 2026 ballot-type spelling, including typographic apostrophes). `altLabel` is the `aliases` array: GRANIT, Census, and SOS voting-districts spellings that differ from `name`.

Example: `hart's location` finds Hart’s Location, whose prefLabel uses `’` and whose GRANIT and Census aliases use `'`.

Some folded labels hit two concepts. Read `kind` on each hit before choosing:

- `carroll`, `grafton`, `hillsborough`, `merrimack`, `strafford`, and `sullivan` are both a county and a municipality.
- `beans` is the Census alias of both Bean’s Grant and Bean’s Purchase.
- `wentworth` is the town Wentworth and the Census alias of Wentworth’s Location.

A ward’s prefLabel is its GRANIT district name (`Laconia Ward 1`). The Census VTD name (`LACONIA WARD 1`) is an altLabel and folds to the same key.

## Walk the place hierarchy

`broader` points at the larger place. `narrower` is the inverse. The validator checks that every pair agrees.

| Concept | `kind` | `broader` |
| --- | --- | --- |
| New Hampshire | `state` | none; `topConceptOf` the places scheme |
| County | `county` | the state |
| Town, city, or unincorporated place | `town`, `city`, or `unincorporated place` | its county |
| City ward | `ward` | its city |

The county prefLabel is the `county` string from the driver (`Belknap`), with no suffix added. The county GEOID is the five-digit prefix shared by that county’s municipality GEOIDs. The state GEOID is the two-digit prefix `33`.

`notation` holds the Census GEOID as a typed literal (`Geoid`) and, on a municipality, the GRANIT town id (`GranitId`). A ward’s notation is its Census VTD GEOID (`CensusVtdGeoid`). The same values are repeated in `geoid` and `granitId` so a consumer can read them without unpacking the typed literal. There is no `exactMatch` Census URI; that gap is recorded in `kb/KNOWN_GAPS.md`.

## Walk from a precinct to its districts

A precinct is the concept that carries `precinct: true` and `inDistrict`. That is every town, every unincorporated place, every ward, and Berlin (a city the SOS lists without wards). The other 12 cities are municipalities only. Their wards are the precincts, which is where `towns.json` stores the 2022 assignment.

`inDistrict` on a precinct is the list of district identifiers for the 2022–2032 plans:

- one base State House district (`office` `nh_house`, `floterial` false)
- one floterial State House district when the precinct has one (`floterial` true)
- one State Senate district
- one Executive Council district
- one U.S. House district

The district points back with `memberPlace`. Those two properties are inverses.

Alton (`kb/places/3300101060.jsonld`) is in Belknap 7, State Senate 6, Executive Council 1, and U.S. House 1. Laconia Ward 1 is in Belknap 5 and the other three offices. Fetch any of those district files for `seats` (State House), `effectiveDate`, `firstElection`, and `plan`.

`firstElection` dates are copied from `redistricting.json` together with that plan’s `unconfirmed` list. When `unconfirmed` contains `first_election`, keep the date and treat it as unconfirmed.

A floterial district lists `baseDistrict`. In this plan the floterial’s members are exactly the members of those base districts. The base district lists the floterial under `floterialDistrict`. Both links are derived from shared membership; the derivation is in `kb/KNOWN_GAPS.md`.

Plan records live at `kb/districts/2022/plan/<plan id>.jsonld`. Office records live at `kb/districts/2022/office/<office>.jsonld` and list their plans in `hasPlan` and their districts in `narrower`.

## Unincorporated places and vote_in

An unincorporated place whose driver record has `vote_in` and `vote_in_id` links to that host municipality with `voteIn`. Hale’s Location votes in Bartlett. Dixville and Millsfield have no host in the driver; the link is absent on purpose.

## Out of scope

These are in the source copies and are not concepts in `kb/` yet:

- The 2012 plan, and every earlier plan in `sources/redistricting.json` (1982, 1992, 2002, and the 2004 replacement of the court plans). Use the driver file for plan history. Do not infer 2012 membership from the 2022 districts.
- Election results.
- `ballot_type` and `electronic_poll_book` on each municipality in `sources/towns.json`.
- Ward lines, maps, and any geography that would split a precinct. The 2022 driver assigns each precinct to one congressional district.
- County commissioner membership. The 2022 and 2023 commissioner plans are plan concepts only. See `kb/KNOWN_GAPS.md`.
- Vetoed and failed bills in the redistricting file.

## Rebuild

```sh
python3 scripts/build_kb.py
python3 scripts/validate_kb.py
```

`scripts/build_kb.py --check` exits non-zero if `kb/` differs from a fresh rebuild. Inputs are the files under `sources/`. The script checks each file’s Git blob SHA-1 against `sources/provenance.json` and stops if a copy has changed.
