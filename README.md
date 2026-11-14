# GraniteState

GitHub Pages site for the [GraniteState](https://github.com/GraniteState) project, served at <https://granitestate.github.io/>.

This repository publishes a static knowledge base of New Hampshire places and the 2022–2032 districts. The files are JSON-LD concept schemes in SKOS. An agent can fetch one concept at a time. There is no server and no database.

- Landing page: [`index.html`](index.html)
- Agent guide: [`AGENTS.md`](AGENTS.md)
- Entry point: [`kb/index.json`](kb/index.json)
- Gaps and judgment calls: [`kb/KNOWN_GAPS.md`](kb/KNOWN_GAPS.md)

The driver files are copies of `towns.json` and `redistricting.json` from the private `nh-elections` repository, plus the Secretary of State voting-district tables from the private `nh-elections-data` repository. Origins and commit ids are in [`sources/README.md`](sources/README.md).

Rebuild the knowledge base, then check it:

```sh
python3 scripts/build_kb.py
python3 scripts/validate_kb.py
```

Both scripts use the Python standard library only. Pull requests run the validator and a rebuild check.

Election-law RSA sections are generated from the private `nh-rsa-data` scrape. The HTML is not stored in this repository. Origins are in [`sources/provenance.json`](sources/provenance.json) and [`rsa/GC_AUGMENTATION.md`](rsa/GC_AUGMENTATION.md).

```sh
python3 scripts/build_rsa.py --source /path/to/nh-rsa-data/rsa_html
python3 scripts/build_rsa.py --self-test
python3 scripts/validate_rsa.py
```
