# raw/sos-voting-districts

Official New Hampshire Secretary of State voting-district documents for the **2022 redistricting**, published as 2022–2032 plans, plus a derived town/ward crosswalk joined to the geographic identifiers already in this repo.

Source page: [https://www.sos.nh.gov/elections/voting-districts](https://www.sos.nh.gov/elections/voting-districts).

Live `sos.nh.gov` requests from the project box returned an Akamai 403, so every file was taken from the Internet Archive Wayback Machine (`id_` raw captures). The manifest records both `original_url` and `archived_url`. Nothing here was invented; typographic repairs are noted in `parse_notes`.

## Vintage

These are the maps and town lists for the 2022 plans (event `nh-redistricting-2022`, 2020 Census), labeled 2022–2032:

| Office | Plan id |
| --- | --- |
| State House | `2022-nh_house-hb50` |
| State Senate | `2022-nh_senate-sb240` |
| Executive Council | `2022-executive_council-sb241` |
| U.S. House | `2022-us_house-norelli` |
| County commissioners | `2022-county_commissioner-hb54` and Strafford `2023-county_commissioner-hb75-strafford` |

The towns-and-wards PDF was created 2023-04-26. The House, Senate, Council, and congressional list PDFs were re-exported 2025-05-06. The county commissioner list PDF was dated 2026-06-02. Scanned maps date from July 2022.

## Layout

```
raw/sos-voting-districts/
  manifest.json
  README.md
  source/             official files, stored as retrieved
  derived/            parsed tables (rebuild with the script below)
```

### Official files

Linked from the 2026-10-06 capture of the SOS page:

| File | Role |
| --- | --- |
| `source/voting-districts.html` | Index page (Wayback 2026-10-06; decompressed from a gzip-stored capture) |
| `source/2022-2032-congressional-districts.pdf` | U.S. House town list |
| `source/2022-congressional-district-map.pdf` | U.S. House map |
| `source/2022-2032-executive-council-districts.pdf` | Executive Council town list |
| `source/2022-executive-council-district-map.pdf` | Executive Council map |
| `source/2022-2032-state-senate-districts.pdf` | State Senate town list |
| `source/2022-senatorial-district-map.pdf` | State Senate map |
| `source/2022-2032-state-representative-and-delegate-districts.pdf` | State House (and Republican delegate) districts, with seat counts and `FL` floterial flags |
| `source/towns-and-wards-as-districted-for-election-purposes-2022-remediated.pdf` | Town/ward crosswalk to all four state offices |
| `source/2024-how-county-officers-are-elected.pdf` | Explanatory |
| `source/2022-2032-county-commissioners-by-district_1.pdf` | County commissioner districts |

**Not captured:** the current index links to `how-county-commissioners-are-elected.pdf`, which has no Wayback snapshot (CDX empty; a 2026-10-06 `id_` fetch returned 404). A same-titled earlier file, `2024-how-county-commissioners-are-elected.pdf` (created 2023-08-21), is stored for reference and is not treated as the current document.

### Derived tables

Rebuild them from the PDFs and the existing geography files:

```
python3 scripts/parse_sos_voting_districts.py
```

The script uses `pdftohtml` (poppler) for layout-aware extraction. Standard library otherwise.

| File | What it is |
| --- | --- |
| `derived/town_ward_district_crosswalk.csv` | Tidy crosswalk: one row per municipality (or ward) and House district |
| `derived/town_ward_units.csv` | One row per SOS town or ward, before a base-plus-floterial pair is expanded |
| `derived/house_districts.csv` | One row per House district, with seats, floterial flag, and printed members |
| `derived/name_mismatches.csv` | Names that were not joined, and leftover GRANIT / Census names |

The crosswalk keeps SOS House names (`Belknap 1`, `Hillsborough 44`, …). `is_floterial` and `house_seats` come from the House list PDF. `is_unincorporated` is true only for places listed under the SOS heading “Unincorporated Places” (other grants and townships that appear in the alphabetical town list are left false).

## Counts (2022–2032)

From the official lists, as parsed:

- 320 town/ward units (247 whole municipalities or unincorporated places, plus 73 wards in 12 cities). Berlin and Derry are listed as whole municipalities, not by ward.
- 494 crosswalk rows, because 174 of those units also sit in a floterial House district. Every unit has exactly one base district; none has only a floterial or more than one of each.
- 203 House districts: **164 base and 39 floterial**. Seat counts sum to **400**.
- 24 Senate districts, 5 Executive Council districts, 2 congressional districts.

That House tally matches GRANIT’s 2022 layers (164 base polygons and 39 named floterial polygons, plus one empty “no floterial” filler that is not a district).

Two typographic glitches in the towns-and-wards PDF house column are recorded in `parse_notes` and were read as the values the House list PDF confirms:

- Concord Ward 2 is printed `16. 28` and is Merrimack 16 (base) and Merrimack 28 (floterial).
- East Kingston is printed `14 34` and is Rockingham 14 (base) and Rockingham 34 (floterial).

The House list PDF itself spells two headings `Distsrict No. 12` and `Disrict No. 30`; those were parsed as districts 12 and 30.

## Geographic ID join

Columns added from existing repo geography:

- `granit_town_id` (`FID_towns_` in `NHPolitDists2022`), `granit_fips`, `granit_name`, `granit_district`
- `census_cousub_geoid`, `census_countyfp`, `census_cousubfp`, `census_name`, `census_namelsad` (2020 Census county subdivisions in `raw/census/rd2022_c2020/geography/NAMES_ST33_NH.zip`)
- `census_vtd_code`, `census_vtd_geoid`, `census_vtd_name` when the unit is a named ward, or a municipality that has exactly one 2020 VTD

**GRANIT’s `FIPS` field is not the Census COUSUB code.** It is GRANIT’s own town code (for example Laconia is GRANIT `1035` and Census cousub `40180`, GEOID `3300140180`). Both are stored.

Names were matched only after a typographic fold (Unicode apostrophes, `&` / `and`, punctuation, case, and a trailing “town” / “city” / “location” / “grant” / “purchase”). Abbreviations were **not** expanded.

### Match rate

- **309 of 320 units matched** both GRANIT and Census (96.6%). 0 partial matches.
- All 73 wards matched, including a Census VTD code.
- **11 units unmatched.** All are unincorporated places in Coos County whose SOS names are abbreviated. IDs were left blank. The same 11 places appear as leftovers in GRANIT and in the Census MCD file:

| SOS name (unmatched) | GRANIT name (leftover) | Census NAMELSAD (leftover) | Census GEOID |
| --- | --- | --- | --- |
| Atk. & Gil. Academy Gt | Atkinson & Gilmanton | Atkinson and Gilmanton Academy grant | 3300702420 |
| Chandler’s Pur. | Chandler's Purchase | Chandlers purchase | 3300711220 |
| Crawford’s Pur. | Crawford's Purchase | Crawfords purchase | 3300716100 |
| Erving’s Loc. | Erving's Location | Ervings location | 3300725180 |
| Hadley’s Pur. | Hadley's Purchase | Hadleys purchase | 3300732420 |
| Martin’s Loc. | Martin's Location | Martins location | 3300746020 |
| Pinkham’s Gt | Pinkham's Grant | Pinkhams grant | 3300761620 |
| Sargent’s Pur. | Sargent's Purchase | Sargents purchase | 3300767860 |
| Second College Gt | Second College Grant | Second College grant | 3300768500 |
| Thompson & Mes’s Pur. | Thompson & Meserve | Thompson and Meserves purchase | 3300776580 |
| Wentworth’s Loc. | Wentworth's Location | Wentworth location | 3300780740 |

Those 11 leftovers are the only GRANIT municipalities and the only real Census MCDs that did not match a SOS name. Census also has a placeholder county subdivision, `County subdivisions not defined` (`3301500000`), which was ignored.

Places that *did* match after the typographic fold include Hale’s Location, Bean’s Grant, Bean’s Purchase, Cutt’s Grant, Dix’s Grant, Green’s Grant, and Low & Burbank’s Grant.

## Licence

No open-data licence is stated on the SOS page or in the PDFs. These are official New Hampshire Secretary of State publications. Cite the New Hampshire Secretary of State.
