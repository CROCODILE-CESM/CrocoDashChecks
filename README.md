# CrocoDashChecks

[![weekly CESM runs](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/cesm_runs.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#cesm) [![data access](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/data_access.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#data-access)

Checks that CrocoDash works end to end on NCAR's systems, and publishes the results at
**<https://crocodile-cesm.github.io/CrocoDashChecks/>**. Both scheduled checks test a fresh
clone of CrocoDash `main`.

| Folder | What it checks | When |
|---|---|---|
| [`integration/`](integration/README.md) | CrocoDash on every grid of the test matrix: the workflow builds each grid and runs the forcings turned on for it, timing each step (by hand, on Casper); the CESM runs build MOM_interface's regional tests with CrocoDash on the grids marked for them and run them in CESM (Mondays 02:00 MT, on Derecho) | By hand; weekly |
| [`data_access/`](data_access/) | Every way CrocoDash fetches data, called for real on Casper | Daily 05:00 MT |
| [`site/`](site/) | The website: Sphinx pages, two of them notebooks that read the folders' JSON and draw the tables and charts | On every push to `main` |

[`integration/matrix.yaml`](integration/matrix.yaml) is the test matrix: one row per grid (across the prime meridian
and the antimeridian, over both poles, a ladder of sizes and resolutions), each listing the
forcings to run on it and whether the CESM runs use it. Every case starts from the CrocoDash case
config in [`integration/case.yaml`](integration/case.yaml).

How it all runs, how to run a check yourself, and how to build the site:
[How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html)
(source: [`site/how_it_works.md`](site/how_it_works.md)).
