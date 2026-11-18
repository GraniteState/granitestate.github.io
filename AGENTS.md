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

## Look up an RSA section

Election law is Title LXIII, chapters 652 through 671, including chapter 664 (political expenditures and contributions). Title IV is also named Elections and was repealed; it has a title page and no sections. Other titles are not in this build.

1. Read [`rsa/index.json`](rsa/index.json) for the address scheme, the titles, and every section.
2. A citation `RSA 659:21` is `https://granitestate.github.io/rsa/659/659-21`. Chapter letters stay uppercase (`662-A`). Section letters stay lowercase (`659:20-a` is `rsa/659/659-20-a`). The colon becomes a hyphen. The section heading on the HTML page has `id="section"`, so a rule page can link to `https://granitestate.github.io/rsa/659/659-21.html#section`. Paragraphs keep `id="p-I"` and the rest. Rules that implement the section are listed at `id="implementing-rules"` on that page.
3. Fetch the identifier plus `.jsonld`. The human page is the same path plus `.html`. GitHub Pages does not rewrite the bare identifier to either file. A chapter is the directory `rsa/659/` (`index.jsonld`). A title is `rsa/title/LXIII/`.
4. `statuteText` is the section body. `historyNote` is the source note. `sessionLaw` parses that note into year, chapter, section, and effective date when the note prints them. A time of day stays in `effectiveText`. A clause that does not match is kept as `citation` and not filled in. `1979, 436:1` is a session law, not an RSA section, and is not a link.
5. A link with class `cite-internal` points at a section or chapter in this build. The site does not link to the General Court. A citation whose target is not a page here stays plain text and is listed in [`rsa/UNRESOLVED_CITATIONS.md`](rsa/UNRESOLVED_CITATIONS.md). Each page names the snapshot (`NH General Court RSA HTML`, the retrieval date, and `nh-rsa-data@` the pinned commit) and links to that commit's raw HTML on `github.com/GraniteState/nh-rsa-data`.
6. `paragraph I` is linked only when that paragraph label is in the section the sentence is in, or when the sentence names the section (`paragraph I of RSA 659:13`). The anchor is `#p-I`.
7. `related` points at a knowledge-base concept only for the rows applied in [`rsa/KB_LINKS.md`](rsa/KB_LINKS.md). Those KB files do not point back. RSA 662:1 is the U.S. House section; the plan record says the boundaries in force come from the 2022 court order.

[`rsa/GC_AUGMENTATION.md`](rsa/GC_AUGMENTATION.md) records what gc.nh.gov serves for chaptered laws. Administrative rules are a separate build, below.

## Look up an administrative rule

The Office of Legislative Services compilation is snapshotted in `GraniteState/adm-rules-data`. Elec is the Electricians' Board. Election rules of the Ballot Law Commission are Bal. Secretary of State rules are not in the snapshot: sos.nh.gov returned HTTP 403. That gap is stated on the rules index.

1. Read [`rules/index.json`](rules/index.json) for the agency list and the address scheme. Gaps are in [`rules/KNOWN_GAPS.md`](rules/KNOWN_GAPS.md).
2. A rule id `Elec 101.01` is `https://granitestate.github.io/rules/elec/101.01`. The agency segment is the lowercased prefix (`saf-mec`, `he-p`, `env-wq`). The number segment drops the prefix. Chapter `Elec 100` is `rules/elec/100`. Part `Elec 101` is `rules/elec/101`. A paragraph such as Elec 404.05(b) is the section page plus `#b`.
3. Fetch the identifier plus `.jsonld`. The human page is the same path plus `.html`. GitHub Pages does not rewrite a bare path to either file. An agency is the directory `rules/elec/` (`index.jsonld`).
4. `ruleText` is the heading through its Source. note. `authorizedBy` lists RSA concepts the rule implements. `authority` keeps the paragraph markers and whether the citation came from an appendix, a statutory-authority line, or a parent part or chapter. An RSA id with no page in this build is plain text on the rule and a row in [`rules/UNRESOLVED_CITATIONS.md`](rules/UNRESOLVED_CITATIONS.md).
5. An RSA section's `implementedBy` list is the inverse, and only for the implements role. A citation inside a Source. note is not authority. The HTML list is `ul#implementing-rules`.
6. Pages link to granitestate.github.io and to `github.com/GraniteState/adm-rules-data` at the commit in [`sources/provenance.json`](sources/provenance.json). Publisher URLs are text, not links. The online compilation is not the official version under RSA 541-A.

## Rebuild

```sh
python3 scripts/build_kb.py
python3 scripts/validate_kb.py
python3 scripts/build_rsa.py --self-test
python3 scripts/validate_rsa.py
python3 scripts/build_rules.py --self-test
python3 scripts/validate_rules.py
```

Administrative rules also need a checkout of `GraniteState/adm-rules-data` at the commit in `sources/provenance.json`:

```sh
python3 scripts/build_rules.py --source /path/to/adm-rules-data
```

Run it after `build_rsa.py`. It fills `#implementing-rules` on the RSA section pages. `--prefixes Elec,Bal` writes those prefixes and leaves other rule pages in place.

RSA pages also need a checkout of `GraniteState/nh-rsa-data`:

```sh
python3 scripts/build_rsa.py --source /path/to/nh-rsa-data/rsa_html
```

`--all` builds every title. `--titles LXIII` builds one title. The default is the titles whose table-of-contents name contains "election", plus any other section files sitting in the checkout (used to close citations).

## Refresh the RSA snapshot

The pages are a snapshot. Refresh them each January, when the General Court reconvenes:

1. Re-scrape the RSA HTML into `GraniteState/nh-rsa-data` and commit that scrape.
2. Bump `rsa.commit` and `rsa.commit_date` in [`sources/provenance.json`](sources/provenance.json) to that commit. The builder reads the pin from there.
3. Rebuild and validate:

```sh
python3 scripts/build_rsa.py --source /path/to/nh-rsa-data/rsa_html
python3 scripts/validate_rsa.py
```

History notes stay unlinked until chaptered-law text is snapshotted into `GraniteState/gc-data`. The validator rejects any href whose host is not `granitestate.github.io` or `github.com/GraniteState/`.

`scripts/build_kb.py --check` exits non-zero if `kb/` differs from a fresh rebuild. Inputs are the files under `sources/`. The script checks each file’s Git blob SHA-1 against `sources/provenance.json` and stops if a copy has changed.
