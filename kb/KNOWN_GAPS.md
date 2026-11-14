# Known gaps

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

- At & Gil Academy Grant (unincorporated place, `3300702420`)
- Bean’s Grant (unincorporated place, `3300704100`)
- Bean’s Purchase (unincorporated place, `3300704260`)
- Berlin (city, `3300705140`)
- Cambridge (unincorporated place, `3300708420`)
- Chandler’s Purchase (unincorporated place, `3300711220`)
- Crawford’s Purchase (unincorporated place, `3300716100`)
- Cutt’s Grant (unincorporated place, `3300716660`)
- Derry (town, `3301517940`)
- Dixville (unincorporated place, `3300718420`)
- Dix’s Grant (unincorporated place, `3300718340`)
- Dummer (town, `3300719300`)
- Erving’s Location (unincorporated place, `3300725180`)
- Green’s Grant (unincorporated place, `3300731780`)
- Hadley’s Purchase (unincorporated place, `3300732420`)
- Hale’s Location (unincorporated place, `3300332500`)
- Kilkenny (unincorporated place, `3300739940`)
- Livermore (unincorporated place, `3300942820`)
- Low & Burbank’s Grant (unincorporated place, `3300743620`)
- Martin’s Location (unincorporated place, `3300746020`)
- Millsfield (unincorporated place, `3300748260`)
- Odell (unincorporated place, `3300757860`)
- Pinkham’s Grant (unincorporated place, `3300761620`)
- Sargent’s Purchase (unincorporated place, `3300767860`)
- Second College Grant (unincorporated place, `3300768500`)
- Success (unincorporated place, `3300774500`)
- Thompson & Meserve’s Purchase (unincorporated place, `3300776580`)
- Wentworth’s Location (unincorporated place, `3300780740`)

### Unincorporated places with no vote_in host

`vote_in` is present only when the 2026 ballot-type lists name a host municipality. These unincorporated places have no `vote_in` and no `vote_in_id`. Nothing was filled in.

- Dixville (`3300718420`)
- Millsfield (`3300748260`)

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

- **Coos 2.** Printed: Atk. & Gilm. Academy Gt; Cambridge; Clarksville; Dix's Grant; Dixville; Dummer; Errol; Milan; Millsfield; Odell; Pittsburg; Second College Grant; Stark; Wentworth's Location. Linked prefLabels: At & Gil Academy Grant; Cambridge; Clarksville; Dix’s Grant; Dixville; Dummer; Errol; Milan; Millsfield; Odell; Pittsburg; Second College Grant; Stark; Wentworth’s Location.
- **Coos 6.** Printed: Bean's Grant; Bean's Purchase; Chandler's Purchase; Crawford's Purchase; Cutt's Grant; Gorham; Green's Grant; Hadley's Purchase; Low & Burbank's Gt.; Martin's Location; Pinkham's Grant; Randolph; Sargent's Purchase; Shelburne; Success; Thompson & Mes's Pur.. Linked prefLabels: Bean’s Grant; Bean’s Purchase; Chandler’s Purchase; Crawford’s Purchase; Cutt’s Grant; Gorham; Green’s Grant; Hadley’s Purchase; Low & Burbank’s Grant; Martin’s Location; Pinkham’s Grant; Randolph; Sargent’s Purchase; Shelburne; Success; Thompson & Meserve’s Purchase.

### Folded labels that match more than one concept

- `beans`: Beans (altLabel, `https://granitestate.github.io/kb/places/3300704100`), Beans (altLabel, `https://granitestate.github.io/kb/places/3300704260`)
- `carroll`: Carroll (prefLabel, `https://granitestate.github.io/kb/places/3300710100`), Carroll (prefLabel, `https://granitestate.github.io/kb/places/33003`)
- `grafton`: Grafton (prefLabel, `https://granitestate.github.io/kb/places/3300930820`), Grafton (prefLabel, `https://granitestate.github.io/kb/places/33009`)
- `hillsborough`: Hillsborough (prefLabel, `https://granitestate.github.io/kb/places/3301136180`), Hillsborough (prefLabel, `https://granitestate.github.io/kb/places/33011`)
- `merrimack`: Merrimack (prefLabel, `https://granitestate.github.io/kb/places/3301147540`), Merrimack (prefLabel, `https://granitestate.github.io/kb/places/33013`)
- `strafford`: Strafford (prefLabel, `https://granitestate.github.io/kb/places/3301773860`), Strafford (prefLabel, `https://granitestate.github.io/kb/places/33017`)
- `sullivan`: Sullivan (prefLabel, `https://granitestate.github.io/kb/places/3300574900`), Sullivan (prefLabel, `https://granitestate.github.io/kb/places/33019`)
- `wentworth`: Wentworth (altLabel, `https://granitestate.github.io/kb/places/3300780740`), Wentworth (prefLabel, `https://granitestate.github.io/kb/places/3300980500`)

### Eleven abbreviated SOS names

`name_mismatches.csv` leaves eleven Coos unincorporated places unmatched. `towns.json` already stores the SOS spelling as an alias and the GRANIT id and Census GEOID from that file's one-for-one leftovers. The generator checks that each `no_name_match` name is one of those aliases and that the crosswalk's district numbers match `towns.json`. It does not choose a new match.

### Ballot types and poll books

`towns.json` carries `ballot_type` and `electronic_poll_book` for 2026. They are not properties of these concepts. See AGENTS.md.

### Fetching an identifier

Concept URIs have no `.jsonld` suffix. GitHub Pages serves the file at the same path plus `.jsonld` and does not rewrite the bare identifier to that file.
