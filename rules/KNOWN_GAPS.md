# Gaps in the administrative-rule pages

Built from `GraniteState/adm-rules-data` commit `1c92d82e0f03a582ca5b7a578588edf38de2318e`, snapshot 2026-11-15.
The derived files do not invent text. These are the holes left visible.

## Secretary of State

sos.nh.gov returned HTTP 403 from Akamai. No Secretary of State compilation was stored.
Election procedure that the Secretary publishes only on that site is not here.
Elec on the General Court list is the Electricians' Board. Bal is the Ballot Law Commission, and those rules are in this build.

## Agencies with no operative text

Cul, the abolished Department of Cultural Resources, returned HTTP 404. Cul-H, Historical Resources, is stored.
Rec and Rep are repealed tables of contents. No operative Rec or Rep sections were parsed.

## Headings that are not rule numbers

105 headings had a prefix that is not an agency code (for example And, Cfr, Dssp, Part, Table).
They collide with real rule numbers when the agency slug is reused, and they are not published as pages.
The sentence stays in the previous heading's text.

Sample: Age 1203, And 102, And 103.06, And 104.02, And 202, And 203.02, And 205.03, And 209.02, And 212.05, And 213.05, And 214.03, And 302.02, And 304.03, And 402.03, And 402.04, And 402.07, And 404.02, And 415.02, And 426.17, And 426.18, And 426.19, And 426.20, And 426.21, And 426.22, And 426.23, And 426.24, And 909, And 1001.02, And 1001.04, And 1405.03, And 4047, And 5011.02, C 7508.07, Cfr 29.7, Cfr 29.8, Cfr 29.9, Cfr 29.10, Cfr 29.11, Cfr 29.12, Dssp 372.

## Mec and Saf-Mec

Mec and Saf-Mec number many of the same sections. They are separate page trees, /rules/mec/ and /rules/saf-mec/, because one path cannot hold both.
The agency list describes Saf-Mec as the earlier numbering of the Mechanical Licensing Board.

## Slice files

he-p6000.html, stra1100.html, and plc1500.html are slices of He-P, Stra, and Plc.
Their headings use the parent prefix, so the pages live under /rules/he-p/, /rules/stra/, and /rules/plc/.

## RSA pages this site does not have

Authority citations whose RSA section or chapter is not in the current RSA build stay plain text.
They are listed in rules/UNRESOLVED_CITATIONS.md. The RSA build is election law plus sections cited from those pages, not the entire Revised Statutes.
A citation that names a section is not linked to the chapter page.

## What was not copied from the archive

Filing-history pages, the Rulemaking Register, and the rules-search detail screens are not pages on this site.
The compilation HTML is the rule text. Provenance links to that file in adm-rules-data at the pinned commit.
Publisher URLs, including gc.nh.gov, are printed as text and are not hrefs.
source_note rows are RSA citations inside a Source. annotation. They are not listed as authority.
Inherited part and chapter authority is listed, and the via label says so.

Rule concepts on disk: 30765.
