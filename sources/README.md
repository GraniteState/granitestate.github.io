# Sources

These are byte-for-byte copies of the driver files the knowledge base is built from. `provenance.json` records the origin repository, path, commit, and Git blob SHA-1. `scripts/build_kb.py` refuses to write `kb/` if a file's blob hash does not match.

Nothing in this directory was retyped. The eleven Coos name matches described in `sos-voting-districts/README.md` were already applied in `towns.json`; this copy does not join them again.

## nh-elections

Private repository `GraniteState/nh-elections`.

| Local file | Origin path | Commit | Generated |
| --- | --- | --- | --- |
| `towns.json` | `towns.json` | [`f00f5fbf`](https://github.com/GraniteState/nh-elections/commit/f00f5fbf5d52da23eb4199a08591c29c3ff6df29) (2026-11-11) | 2026-11-11 |
| `redistricting.json` | `redistricting.json` | [`9ca443d4`](https://github.com/GraniteState/nh-elections/commit/9ca443d4497691b9407a41629f004362edb4bf25) (2026-11-10) | 2026-11-10 |

`redistricting.json` is unchanged in the later `towns.json` commit `f00f5fbf`. The `_comment` key in each file is the field guide. Read it before the records.

`towns.json` is the municipality roster: 259 Census county-subdivision GEOIDs, with names, aliases, kind, county, wards, GRANIT ids, and 2022-plan district assignments. For the 12 cities that have wards, district assignments are on the wards.

`redistricting.json` is the plan history from 1982 through 2022. This knowledge base uses the 2022 event's current plans (and the 2023 Strafford county-commissioner plan) for effective dates and first elections. Earlier plans, including 2012, stay in this file and are not built into `kb/`.

## nh-elections-data

Private repository `GraniteState/nh-elections-data`, commit [`5900f24d`](https://github.com/GraniteState/nh-elections-data/commit/5900f24db08576d3570934573df1e5a0e07c8633) (2026-11-11).

| Local file | Origin path |
| --- | --- |
| `sos-voting-districts/README.md` | `raw/sos-voting-districts/README.md` |
| `sos-voting-districts/house_districts.csv` | `raw/sos-voting-districts/derived/house_districts.csv` |
| `sos-voting-districts/town_ward_district_crosswalk.csv` | `raw/sos-voting-districts/derived/town_ward_district_crosswalk.csv` |
| `sos-voting-districts/town_ward_units.csv` | `raw/sos-voting-districts/derived/town_ward_units.csv` |
| `sos-voting-districts/name_mismatches.csv` | `raw/sos-voting-districts/derived/name_mismatches.csv` |

The README in that directory is the upstream note for the Secretary of State 2022–2032 voting-district extract. The generator uses `house_districts.csv` for seat counts, the floterial flag, and the printed member list, and checks the crosswalk against `towns.json`. Membership links follow `towns.json`.

Official pages cited by those files have no open-data licence stated on them. Cite the New Hampshire Secretary of State, GRANIT, and the U.S. Census Bureau as the upstream README and `towns.json` `sources` list do.

## nh-rsa-data

Repository `GraniteState/nh-rsa-data`, commit [`96bd0a24`](https://github.com/GraniteState/nh-rsa-data/commit/96bd0a247d4463e2ae692310c0fdd17ec563a46c) (2026-11-12). The HTML under `rsa_html/` is a scrape of the New Hampshire General Court RSA pages. It is not copied into this repository. `scripts/build_rsa.py` reads a local checkout and writes `rsa/`. The `rsa` object in `provenance.json` is the pin: to refresh, commit a new scrape, bump `commit` and `commit_date` there, and rebuild. The `files` array is only the driver copies `build_kb.py` hashes.
