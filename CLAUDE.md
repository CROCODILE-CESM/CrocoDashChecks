# CLAUDE.md

CrocoDashChecks checks CrocoDash end to end: weekly CESM runs (`cesm_runs/`), a daily
data-access check (`data_access/`), and performance snapshots (`performance/`). `site/` is a Sphinx
site on GitHub Pages; its Status and Performance pages are notebooks that read that JSON. How it all
runs: `site/how_it_works.md`.

## Where things live

| What | Where |
|---|---|
| Dev checkout (edit here, or in a worktree) | `dev/CrocoDashChecks/` in the CROC monorepo |
| CI clones the scheduled jobs run from | `/glade/work/$USER/croc_ci/` (this repo, CESM `crocodash`); hard-reset every run, never edit |
| The CrocoDash tested | a fresh clone of `main` per job (`CROCODASH_BRANCH` overrides), deleted when the job ends |
| Crontab | `cron.hpc.ucar.edu`; read it with `ssh cron.hpc.ucar.edu crontab -l`; only the user edits it |
| Cron and job logs | `/glade/work/$USER/croc_ci/cron.log`, `/glade/work/$USER/croc_ci/logs/` |
| Weekly CESM-run summary | `cesm_runs.json` on the `test-results` branch |
| Published site | <https://crocodile-cesm.github.io/CrocoDashChecks/>, built by `.github/workflows/publish.yml` |

Both jobs record the CrocoDash branch and commit they tested (`crocodash` in `cesm_runs.json` and
`health.json`), and the Status page shows them.

## Rules

- **Everything runs in the `CrocoDash` conda env** (pytest-benchmark installed into it). Don't add
  other dependencies (the site's own build packages in `site/requirements.txt` are the exception:
  CI only).
- **Always test a fresh pull:** CrocoDash `main` via `source crocodash_main.sh` (both jobs do; do it
  before any hand run too), and CESM's `crocodash` branch tip with its pinned MOM_interface regional
  tag (the weekly job's `UPDATE=1`).
- **Keep it small.** One script per job; no packages, frameworks or config layers. MOM_interface's
  `testlist_mom.xml` decides which CESM tests run; don't add test lists here.
- **The site is Markdown and notebooks, never hand-written HTML, CSS or JS** (the owner can't read
  them). Charts are matplotlib cell outputs; Sphinx runs the notebooks on every build and hides their
  code. Commit notebooks without outputs. Shared helpers go in `site/checks.py`, page logic stays in
  the page's notebook. `site/requirements.txt` is pinned; bump it on purpose.
- **Status marks are an icon beside a word** (✅ Pass, ❌ Failed: …), never color alone. Every number
  on the site comes from the JSON. A check older than `STALE_DAYS` in `site/checks.py` shows as
  stale, because a schedule that stops running fails silently otherwise.
- **Keep the anchors other pages link to:** `#cesm` and `#data-access` (README badges) and
  `#mom6-scaling` (the gallery's `ocean_only` notebook) on the Status page.
- **The jobs run from the CI clones in `/glade/work/$USER/croc_ci`** and reset them to their branch
  tips (`UPDATE=1`). PBS copies a job script when it's submitted, so a change to a `.pbs` file takes
  effect only once the clone has it: pull there after merging.
- **Keep `cron_submit.sh` scripts executable in git (100755):** the reset restores git's mode.
- Use black on Python and the notebooks (`black[jupyter]`) before committing. Build the site with
  `sphinx-build --fail-on-warning site site/_build/html`, as CI does.

## Gotchas

- **`data_access/check.py` runs each access method in its own process group** and kills it at
  `VALIDATE_TIMEOUT`. A thread pool can't do this: leaving it waits for the thread, so one
  whole-file download held up every run.
- **A failing method's `detail` is its last error line,** because `validate_method` catches its own
  exceptions and returns False.
- **The weekly job pushes `cesm_runs.json` to `test-results`, not `main`,** so the site only picks it
  up on its next rebuild, at the latest after the next daily data-access push.
- **`performance/test_mapping.py` skips unless mom6_forge has the fast mapping write path**
  (mom6_forge #125/#137); CrocoDash's nested mom6_forge has it. Keep its boxes clear of the 0/360
  seam. Its rmax sweep peaks at ~85 GB (Indo-Pacific at rmax 80), so run it in a PBS job with 100 GB
  or more.
- **The `CrocoDash` env imports its own installed CrocoDash** (the 2026 workshop checkout), not
  `main`, unless `crocodash_main.sh` was sourced first.
- **MOM6 truncates `INPUTDIR` at 128 characters,** so keep `cesm_runs/` test paths short.
