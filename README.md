# CrocoDashChecks

[![weekly CESM runs](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/cesm_runs.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#cesm) [![data access](https://img.shields.io/endpoint?url=https://crocodile-cesm.github.io/CrocoDashChecks/badges/data_access.json)](https://crocodile-cesm.github.io/CrocoDashChecks/#data-access)

Checks that CrocoDash works end to end on NCAR's systems. Results: <https://crocodile-cesm.github.io/CrocoDashChecks/>

| Folder | What it checks | When |
|---|---|---|
| [`cesm_runs/`](cesm_runs/README.md) | MOM_interface's regional SMS tests, each built with CrocoDash and run in CESM on Derecho | Mondays 02:00 MT |
| [`data_access/`](data_access/) | Every way CrocoDash fetches data (`ProductRegistry.validate_function`), called for real on Casper | Daily 05:00 MT |
| [`performance/`](performance/) | How long the expensive steps take (open boundaries, GEBCO bathymetry, GLOFAS runoff mapping) and MOM6's speed vs. tasks | By hand |
| [`site/`](site/build_site.py) | Builds the results page from the three folders' JSON | On every push to `main` |

## How it runs

The crontab on `cron.hpc.ucar.edu` submits both scheduled checks; the cron host has no software, so each script only runs `qsub`:

```
0 2 * * 1 /glade/work/$USER/croc_ci/CrocoDashChecks/cesm_runs/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
0 5 * * * /glade/work/$USER/croc_ci/CrocoDashChecks/data_access/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
```

- **Clones:** both jobs run from the CI clones in `/glade/work/$USER/croc_ci` (this repo, CESM `crocodash`, CrocoDash). Each resets its clones to their branch tips first, so test another CrocoDash branch by checking it out there.
- **Logs:** job logs go to `/glade/work/$USER/croc_ci/logs/`.
- **Credentials:** the data-access job uses your own (`~/.cdsapirc`, `~/.copernicusmarine`).
- **Publishing:** both jobs push their results with `cesm_runs/push_results.sh`, using the token from your `gh` login:
  - the weekly runs push `cesm_runs.json` to the `test-results` branch;
  - the daily check pushes `data_access/health.json` to `main`, which rebuilds the site.

## By hand

```bash
python data_access/check.py                       # in the CrocoDash env, on GLADE
python site/build_site.py                          # -> site/_build/index.html
```

The performance tests use [pytest-benchmark](https://pytest-benchmark.readthedocs.io/) (`pip install pytest-benchmark`); each case is timed once, with its peak memory, and the page reads the JSON they write. Run them on a compute node:

```bash
pytest performance/test_obc.py --benchmark-json=performance/obc.json                  # CrocoDash env, ~1 h, ~80 GB
pytest performance/test_topo.py --benchmark-json=performance/topo.json                # CrocoDash env, ~60 GB
pytest performance/test_mapping.py --benchmark-json=performance/runoff_mapping.json   # mom6_forge env
```

`performance/mom6_scaling.json` holds a hand-run NTASKS_OCN sweep (the scripts are in the CROC monorepo's `dev/scaling_test/`).
