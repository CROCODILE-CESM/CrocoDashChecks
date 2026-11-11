# How it works

CrocoDashChecks runs three checks on NCAR's systems and publishes their results here.

| Check | What it does | Where | When | Results |
|---|---|---|---|---|
| [Weekly CESM runs](cesm_runs.md) | Builds each regional SMS test in MOM_interface's `testlist_mom.xml` with CrocoDash on a small test domain, then runs it in CESM | One Derecho node | Mondays 02:00 MT | `cesm_runs.json` on the `test-results` branch |
| Data access | Calls every way CrocoDash fetches data (every product's access methods), for real | Casper | Daily 05:00 MT | `data_access/health.json` on `main` |
| [Performance](performance.ipynb) | Times CrocoDash's expensive steps and records their peak memory | A compute node | By hand | `performance/*.json` on `main` |

## Which CrocoDash gets tested

Every check tests the tip of CrocoDash `main`, and the weekly runs use the tip of CESM's
`crocodash` branch, with the MOM_interface regional tag it pins. `crocodash_main.sh` clones
CrocoDash fresh, with its submodules, puts that clone first on `PYTHONPATH`, and deletes it
when the job (or your shell) exits. Both scheduled jobs source it, and you should too before
running anything by hand. Each job records the branch and commit it tested, and the
[Status page](index.ipynb) shows them. The `CrocoDash` conda env supplies only the
dependencies.

To test another branch, submit the job yourself with `CROCODASH_BRANCH` set, e.g.
`qsub -v CESMROOT=...,CROCODASH_BRANCH=my-branch cesm_runs/run_mom_tests.pbs`.

## How a scheduled run starts

1. **The crontab on `cron.hpc.ucar.edu`** runs a `cron_submit.sh` script. The cron host has
   no software (not even git), so that script only runs `qsub`:

   ```
   0 2 * * 1 /glade/work/$USER/croc_ci/CrocoDashChecks/cesm_runs/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   0 5 * * * /glade/work/$USER/croc_ci/CrocoDashChecks/data_access/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   ```

   Edit it with `ssh cron.hpc.ucar.edu` and then `crontab -e`.
2. **The job** (`cesm_runs/run_mom_tests.pbs` or `data_access/check.pbs`) first resets its
   clone of this repo to `main`. The weekly job also resets the CESM clone and runs
   `git-fleximod update`. Then it clones CrocoDash and runs the check.
3. **It publishes its results** with `cesm_runs/push_results.sh`, using the token from your
   `gh` login. The weekly runs push `cesm_runs.json` to the `test-results` branch. The daily
   check pushes `data_access/health.json` to `main`, and that push rebuilds this site.

:::{important}
PBS copies a job script when the job is submitted, before the job updates its clone. So a
change to a `.pbs` file only takes effect once the CI clone has it: after merging, run
`git -C /glade/work/$USER/croc_ci/CrocoDashChecks pull`.
:::

## Where things are

| What | Where |
|---|---|
| CI clones the jobs run from (reset every run, so don't edit them) | `/glade/work/$USER/croc_ci/`: this repo and CESM's `crocodash` branch |
| Cron output | `/glade/work/$USER/croc_ci/cron.log` |
| Job logs | `/glade/work/$USER/croc_ci/logs/` |
| Weekly test directories | `/glade/derecho/scratch/$USER/croc_tests/` |
| Credentials the data-access check uses | your own: `~/.cdsapirc`, `~/.copernicusmarine` |

## How this site is built

`.github/workflows/publish.yml` rebuilds the site on every push to `main`:

1. it fetches `cesm_runs.json` from the `test-results` branch;
2. `sphinx-build` runs the page notebooks ([Status](index.ipynb) and
   [Performance](performance.ipynb)), which read the results JSON and draw the tables and
   charts;
3. `site/write_badges.py` writes the README's two badges from the same counts.

To build it yourself:

```bash
pip install -r site/requirements.txt
sphinx-build site site/_build/html
python site/write_badges.py
# open site/_build/html/index.html
```

To change a page, open its notebook (`site/index.ipynb` or `site/performance.ipynb`) in
Jupyter, run it, and edit it like any notebook. Clear its outputs before committing: the
build reruns it anyway. Code that both pages need is in `site/checks.py`.

## Running a check by hand

Everything here runs in the `CrocoDash` conda env (which has pytest-benchmark installed for the
performance tests). Start every hand run with a fresh clone of CrocoDash `main`:

```bash
conda activate CrocoDash
source crocodash_main.sh
```

**Data access**, on GLADE:

```bash
python data_access/check.py                     # writes data_access/health.json
qsub -q casper@casper-pbs data_access/check.pbs  # or as a Casper job, with a fresh clone of main
```

**Weekly CESM runs**: see [Weekly CESM runs](cesm_runs.md).

**Performance**, on a compute node. Each case is timed once, with its peak memory:

```bash
pytest performance/test_obc.py --benchmark-json=performance/obc.json                  # ~1 h, ~80 GB
pytest performance/test_topo.py --benchmark-json=performance/topo.json                # ~60 GB
pytest performance/test_mapping.py --benchmark-json=performance/runoff_mapping.json   # 100 GB+
```


`performance/mom6_scaling.json` holds a hand-run NTASKS_OCN sweep; its scripts are in the CROC
monorepo's `dev/scaling_test/`.
