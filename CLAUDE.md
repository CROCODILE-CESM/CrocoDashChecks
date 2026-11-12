# CLAUDE.md

CrocoDashChecks checks CrocoDash end to end, in two folders: `integration/` (the test matrix of
grids; the workflow on every grid, `test_workflow.py`, on Casper; and the CESM runs on the grids
marked for them, `run_mom_tests.py`, on Derecho) and `data_access/` (every data access method, on
Casper). All three run every Monday from `weekly.sh`, started by one crontab line. Shared job
scripts (`weekly.sh`, `crocodash_main.sh`, `push_results.sh`) are at the root. `site/` is a Sphinx
site on GitHub Pages; its Status and Performance pages are notebooks that read that JSON. How it all
runs: `site/how_it_works.md`.

## Where things live

| What | Where |
|---|---|
| Dev checkout (edit here, or in a worktree) | `dev/CrocoDashChecks/` in the CROC monorepo |
| Each weekly run (fresh clones of this repo and CESM, job logs; 4 weeks kept) | `/glade/derecho/scratch/$USER/crocodashchecks/<date>/` |
| Data the data-access check reads (not a clone; keep it) | `/glade/work/$USER/croc_ci/inputs/` |
| The CrocoDash tested | a fresh clone of `main` per job (`CROCODASH_BRANCH` overrides), deleted when the job ends |
| Crontab | `cron.hpc.ucar.edu`; read it with `ssh cron.hpc.ucar.edu crontab -l`; only the user edits it |
| Cron and job logs | `/glade/derecho/scratch/$USER/crocodashchecks/cron.log`, each run's `logs/` |
| Weekly CESM-run summary | `cesm_runs.json` on the `test-results` branch |
| Weekly workflow results | `integration/workflow.json` and `workflow.xml` on `main` |
| Published site | <https://crocodile-cesm.github.io/CrocoDashChecks/>, built by `.github/workflows/publish.yml` |

Every job records the CrocoDash branch and commit it tested (`crocodash` in `cesm_runs.json` and
`health.json`, properties in `workflow.xml`), and the Status page shows them.

## Rules

- **Everything runs in the `CrocoDash` conda env** (pytest-benchmark installed into it). Don't add
  other dependencies (the site's own build packages in `site/requirements.txt` are the exception:
  CI only).
- **Always test a fresh pull:** CrocoDash `main` via `source crocodash_main.sh` (every job does; do it
  before any hand run too), and CESM's `crocodash` branch tip with its pinned MOM_interface regional
  tag (the weekly CESM job clones it fresh).
- **The test matrix is `integration/matrix.yaml`, one row per grid** (read by `matrix.py`), and
  every case starts from `case.yaml`, a CrocoDash case config without its grid. A row gives its grid, any
  changes to `case.yaml`, the forcings to run (`crocodash process` flags) and `cesm_runs`. Add
  grids there, never inside a test; a new forcing needs a step in `test_workflow.py` and its flag
  in `matrix.FORCINGS`.
- **The workflow is one file, `integration/test_workflow.py`:** each grid is built once
  (`test_grid`, through `CrocoDash.recipe`'s builders), then each forcing runs through its
  CrocoDash configurator, without a CESM case. Sweeps that vary what isn't a grid stay in that
  file and run on named rows. Every step runs in a forked child; its timing goes to
  `workflow.json` and its pass/fail/skip, with the reason, to `workflow.xml` (pytest's junit),
  which is what lets the site show failures.
- **Keep it small.** One script per job; no packages, frameworks or config layers. MOM_interface's
  `testlist_mom.xml` decides which CESM tests run; don't add test lists here.
- **The site is Markdown and notebooks, never hand-written HTML, CSS or JS** (the owner can't read
  them). Charts are matplotlib cell outputs; Sphinx runs the notebooks on every build and shows
  only their outputs, not their code (`nb_remove_code_source`). Commit notebooks without outputs;
  edit them as notebooks (no generator scripts). Shared helpers go in `site/checks.py`, page logic stays in
  the page's notebook. `site/requirements.txt` is pinned; bump it on purpose.
- **Keep the Status page terse and glanceable:** the matrix shows marks only (✅ ❌ ⬜ ⚠️, shapes,
  never color alone) with a one-line legend; tables are compact (`checks.table`). Every number
  on the site comes from the JSON. A check older than `STALE_DAYS` in `site/checks.py` shows as
  stale, because a schedule that stops running fails silently otherwise.
- **Keep the anchors other pages link to:** `#cesm` and `#data-access` (README badges) and
  `#mom6-scaling` (the gallery's `ocean_only` notebook) on the Status page.
- **Nothing is kept between weekly runs:** the crontab line clones this repo fresh and runs
  `weekly.sh`, which copies the clone into that run's directory and submits every job from there,
  so whatever is on `main` on Monday runs. Keep the crontab line itself minimal (clone, then
  `weekly.sh`); everything else belongs in `weekly.sh`.
- Use black on Python and the notebooks (`black[jupyter]`) before committing. Build the site with
  `sphinx-build --fail-on-warning site site/_build/html`, as CI does.

## Gotchas

- **`data_access/check.py` runs each access method in its own process group** and kills it at
  `VALIDATE_TIMEOUT`. A thread pool can't do this: leaving it waits for the thread, so one
  whole-file download held up every run.
- **A failing method's `detail` is its last error line,** because `validate_method` catches its own
  exceptions and returns False.
- **The CESM runs push `cesm_runs.json` to `test-results`, not `main`;** `publish.yml` rebuilds on
  pushes to either branch, always from `main`, fetching `cesm_runs.json` from `test-results`.
- **The workflow needs ~80 GB at its peak** (runoff on `indo_pacific` at rmax 80 km; full GEBCO
  on `pacific_40deg` takes ~65 GB and 22 min; the whole run ~2 h): run it with `integration/workflow.pbs`, never on a login node.
- **A forcing on a grid that failed to build is skipped, not failed:** `equator_180e` fails at
  the grid step (mom6_forge #173, the GEBCO ±180° gap), so its open boundaries show as skipped.
- **The `CrocoDash` env imports its own installed CrocoDash** (the 2026 workshop checkout), not
  `main`, unless `crocodash_main.sh` was sourced first.
- **MOM6 truncates `INPUTDIR` at 128 characters,** so keep the CESM runs' test paths short.
