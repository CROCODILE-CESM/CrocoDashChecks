# Integration

| File | What it is |
|---|---|
| `matrix.yaml` | The test matrix: one row per grid, with its forcings and `cesm_runs` |
| `case.yaml` | The CrocoDash case config every row starts from; a row can change it |
| `matrix.py` | Reads both |
| `test_workflow.py`, `workflow.pbs` | The workflow: every grid built once, its forcings run, every step timed (Casper) |
| `run_mom_tests.py`, `run_mom_tests.pbs` | The CESM runs (Derecho) |
| `mom6_scaling.json` | A hand-run sweep of MOM6's speed against its task count |

Schedule, and running by hand: [How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html).

## The CESM runs

- **What runs:** every regional (`USER_RES`) `SMS` test in MOM_interface's `testlist_mom.xml`,
  keeping only its compset and options (`_D`, `_Ld2`, `_P<n>`). To cover a new compset, add a
  test there.
- **Where:** on every `matrix.yaml` row with `cesm_runs: true`, built by CrocoDash from
  `case.yaml` instead of the test's Panama testmods.
- **Forcing:** each test gets only the `case.yaml` forcing blocks its compset uses: synthetic
  ocean, ice and waves; real GLOFAS runoff, river nutrients and MARBL IC from GLADE.
- **Skipped:** restart and other multi-run tests (ERS etc.); CESM's own `create_test` covers them.
- **List the tests:** `python run_mom_tests.py --cesmroot <CESM> --test-root /tmp/x --dry-run`.

| Phase | What it covers |
|---|---|
| `CREATE_NEWCASE` | `crocodash create`, including configuring and processing forcings |
| `XML` | the test options, plus 4 tasks per component and 56 for DATM, DROF and the mediator |
| `SETUP` | `case.setup --reset` |
| `SHAREDLIB_BUILD` / `MODEL_BUILD` | `case.build` |
| `SUBMIT` / `RUN` | `case.submit --no-batch`; RUN passes only if `CaseStatus` records `case.run success` |

A test's files, in `/glade/derecho/scratch/$USER/croc_tests/`:

- `SMS_…crocodash-<grid>.<testid>/`: `TestStatus`, `croc_test.log` (every command's output),
  `crocodash_config.yaml`, and the case itself.
- `inputdir/<compset>.<grid>.<testid>/`: the case's forcing (kept short: MOM6 truncates
  `INPUTDIR` at 128 characters).
- `cs.status.<testid>`: CIME's summary of every test in that run.
