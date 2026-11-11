# CrocoDashChecks

[![weekly CESM runs](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/cesm_runs.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#cesm) [![data access](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/data_access.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#data-access)

Checks that CrocoDash works end to end on NCAR's systems, and publishes the results at
**<https://crocodile-cesm.github.io/CrocoDashChecks/>**. Both scheduled checks test a fresh
clone of CrocoDash `main`.

| Folder | What it checks | When |
|---|---|---|
| [`cesm_runs/`](cesm_runs/README.md) | MOM_interface's regional SMS tests, each built with CrocoDash and run in CESM on Derecho | Mondays 02:00 MT |
| [`data_access/`](data_access/) | Every way CrocoDash fetches data, called for real on Casper | Daily 05:00 MT |
| [`performance/`](performance/) | The workflow: builds every grid in the matrix and runs its forcings, timing each step; and MOM6's speed vs. tasks | By hand |
| [`site/`](site/) | The website: Sphinx pages, two of them notebooks that read the folders' JSON and draw the tables and charts | On every push to `main` |

[`matrix.yaml`](matrix.yaml) is the test matrix: one row per grid (across the prime meridian
and the antimeridian, over both poles, a ladder of sizes and resolutions), each listing the
forcings to run on it and whether the CESM runs use it. Every case starts from the CrocoDash case
config in [`case.yaml`](case.yaml).

How it all runs, how to run a check yourself, and how to build the site:
[How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html)
(source: [`site/how_it_works.md`](site/how_it_works.md)).
