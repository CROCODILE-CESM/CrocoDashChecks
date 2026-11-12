# CrocoDashChecks

[![weekly CESM runs](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/cesm_runs.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#cesm) [![data access](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/data_access.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#data-access)

Checks CrocoDash `main` end to end on NCAR's systems every Monday:
**<https://crocodile-cesm.github.io/CrocoDashChecks/>**

| Folder | What's in it |
|---|---|
| [`integration/`](integration/README.md) | The test matrix, the workflow on every grid (Casper), and the CESM runs (Derecho) |
| [`data_access/`](data_access/) | Every way CrocoDash fetches data, called for real (Casper) |
| [`site/`](site/) | The website: Markdown pages and notebooks that read the results |

How it runs, and how to run a check by hand:
[How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html).
