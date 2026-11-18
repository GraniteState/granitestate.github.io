# General Court augmentation

The published pages do not link to the General Court. A source note is plain text plus a link to the raw HTML in `GraniteState/nh-rsa-data` at the commit in `sources/provenance.json`. Session-law citations stay unlinked until chaptered-law text is snapshotted into `GraniteState/gc-data`.

The notes below are what this environment observed on 2026-11-14. They are not links from the statute pages.

## RSA section pages

`https://www.gencourt.state.nh.us/rsa/...` redirects to `https://gc.nh.gov/rsa/...`.

A section page is stable:

`https://gc.nh.gov/rsa/html/{TitleRoman}/{Chapter}/{Chapter}-{section}.htm`

Checked live, each returned the same HTML shape as the scrape:

| Citation | URL | Result |
| --- | --- | --- |
| RSA 659:21 | `/rsa/html/LXIII/659/659-21.htm` | 200 |
| RSA 659:20-a | `/rsa/html/LXIII/659/659-20-a.htm` | 200 |
| RSA 662:1 | `/rsa/html/LXIII/662/662-1.htm` | 200 |
| RSA 662-A:1 | `/rsa/html/LXIII/662-A/662-A-1.htm` | 200 |
| RSA 21-G:1 and 21-G:2 | `/rsa/html/I/21-G/21-G-1.htm` and `21-G-2.htm` | 200 |
| RSA 260:21 and 260:21-a | `/rsa/html/XXI/260/260-21.htm` and `260-21-a.htm` | 200 |
| RSA 664:1 | `/rsa/html/LXIII/664/664-1.htm` | 200 |

Chapter letters are uppercase in the path. Section letters are lowercase. There is no chapter 21-A in the table of contents (the series goes 21, 21-B, 21-C, …). `.../I/21-A/21-A-1.htm` is 404.

Title IV (Elections, chapters 54–70) is repealed. `NHTOC/NHTOC-IV.htm` is 200 and says the title was repealed. `.../IV/60/60-1.htm` is 404. Out-of-scope citations in that range link to the repeal notice, not to a section path.

A chapter table of contents is `https://gc.nh.gov/rsa/html/NHTOC/NHTOC-{Title}-{Chapter}.htm` (for example `NHTOC-LXIII-659.htm` and `NHTOC-I-21-G.htm`).

Citations outside this build use that pattern. They are not fetched at build time.

## Session laws and bill status

A source note such as `1979, 436:1, eff. July 1, 1979` is Laws 1979, chapter 436, section 1. That is not an RSA section. The pages do not link it.

What gc.nh.gov actually serves:

- `https://gc.nh.gov/bill_status/` is 403 from IIS (directory listing denied), not an Akamai block. Named pages under it return 200.
- `https://gc.nh.gov/bill_status/misc/chaptered_final_version.aspx` is 200 and, on this date, is titled "2026 Chaptered Final Version". The year is not a query parameter that changes the list (`?year=2024` still returns the 2026 page). The form is an ASP.NET postback.
- Each chapter number on that page is a link like `billinfo.aspx?id=533`. The id is an opaque bill id. Chapter 4 of the 2026 list was HB0266, not a URL derived from the year and chapter.
- `billinfo.aspx?id=533` is 200. Bill text and the chaptered final version are opened with `__doPostBack`, not a stable GET. Amendment PDFs use `pdf.aspx?q=amendment&id=2025-2998H`, which is an amendment id, not a session-law chapter.
- These guesses were 404: `/legislation/2024/0004.html`, `/laws/2024/4.html`, `/laws/2024/chapter-4.html`, `/bill_status/chapter.aspx?year=2024&chapter=4`, `/bill_status/ChapteredLaw.aspx?year=2024&chap=4`, and `gencourt.state.nh.us/legislation/2024/HB0154.html`.
- `results.aspx` with `txtsessionyear` or `txtchapternumber` returned the search shell, not a chapter.

There is no verified URL that is a function of year + chapter + section. Linking `1979, 436:1` to a guessed path would be wrong, and the 1979 laws are not on the current chaptered-final list.

Proposed later step, not done here:

1. Save the chaptered-final index for each session year that the site still publishes. That requires finding a year selector that works; the public page observed here does not have one.
2. Record `year, chapter -> bill id` from that index.
3. Link a source-note citation to `https://gc.nh.gov/bill_status/billinfo.aspx?id={id}` only when the map has that chapter. Say so in the link text, because the bill page is not the session-law section.
4. Leave older years (the 1979 acts that open most election sections) unresolved until a scanned session-law source is identified.

## sos.nh.gov

`https://sos.nh.gov/` and `https://www.sos.nh.gov/` return 403. The body is an Akamai "Access Denied" page (`errors.edgesuite.net`, reference number in the body). The RSA HTML on gc.nh.gov did not do that.

## Administrative rules

The rule pages are built. `scripts/build_rules.py` reads `GraniteState/adm-rules-data` at the commit in `sources/provenance.json` and writes `/rules/`. Each RSA section page lists implementing rules at `#implementing-rules`. The notes below are what this environment observed on 2026-11-14, before that snapshot. They are not links from the rule pages.

The Office of Legislative Services, Administrative Rules, is at `https://gc.nh.gov/rules/`. It says there is no official publisher of the complete New Hampshire Code of Administrative Rules. OLS does not publish the rules. Each agency publishes its own. `https://gc.nh.gov/rules/about_rules/official_version.aspx` says that for rules filed after August 25, 1998 the as-filed copy is the official version, and the online text is an edited camera-ready copy the agency certifies. `https://gc.nh.gov/rules/about_rules/checkrule.aspx` says an online rule can lag an amendment or an expiration until the agency certifies the update.

What the site does publish, and the URL shapes that responded:

| Page | What it is |
| --- | --- |
| `https://gc.nh.gov/rules/about_rules/listagencies.aspx` | Index of rule-number prefixes (`Agr`, `Ed`, `He-P`, …) to the agency name. Many rows also name the agency's own website. |
| `https://gc.nh.gov/rules/state_agencies/{prefix}.html` | That prefix's table of contents. `agr.html` is 200 and links to chapter files. |
| `https://gc.nh.gov/rules/state_agencies/{prefix}{chapter}.html` | Chapter text. `agr100.html` is 200 (the old `gencourt.state.nh.us` host redirects here). It states `Statutory Authority: RSA 541-A:16, I(a)` on the chapter and a source note `Source. #2298, eff 2-17-83`. The ids in the file are Word style names, not section anchors, so `Agr 101.01` is not a fragment URL. |
| `https://gc.nh.gov/rules/filing_history/default.aspx` | Links to `filing_history/source{prefix}.html`, a chronological filing history with document numbers. |
| `https://gc.nh.gov/rules/adoptions/default.aspx` | Newest adopted rules awaiting certification. A row has a document number, a notice number (`NN 2026-119`), rule numbers (`Pol 300-Pol 600`), and an effective date. The href is a PDF whose filename repeats that whole label, with spaces, under `adoptions/Effective Adopted Rules as Filed - Awaiting Certification/`. |
| `https://gc.nh.gov/rules/register/default.aspx` | The Rulemaking Register: a weekly PDF, plus notice PDFs such as `/rules/register/2026/1112/2026-241 IP Rule Opt 400.pdf`. |
| `https://gc.nh.gov/nholsrulesdbsearch/` | Search by agency, year, effective date, expiration date, and notice number. The form is an ASP.NET postback. A rule number is not a stable GET URL. |
| `https://gc.nh.gov/rules/about_rules/effective_expire.aspx` | When regular, interim, and emergency rules take effect and expire, citing RSA 541-A. |

A later build can index prefixes and chapter files from `listagencies.aspx` and the `state_agencies` HTML, and can store statutory authority and the source-note document number and effective date from those chapter pages. It should not treat the online HTML as the official rule text. Most of the code lives on the agency sites named in the index, and the official version is the copy filed with OLS.
