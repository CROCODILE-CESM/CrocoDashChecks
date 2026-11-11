#!/bin/bash
# Weekly entry point, run from crontab on cron.hpc.ucar.edu (see README.md).
# The cron host only has 1 GB and no software (not even git), so this only
# submits run_mom_tests.pbs, which updates this repo and CESM, and clones
# CrocoDash main, itself.
#
# CI_ROOT : holds the CESM clone and the job logs (default: /glade/work/$USER/croc_ci)
# MAILTO  : where PBS mails when the job ends (default: $USER@ucar.edu)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CI_ROOT=${CI_ROOT:-/glade/work/$USER/croc_ci}

cd "$HERE"
# Job logs go next to the clones, not into this repo.
mkdir -p "$CI_ROOT/logs"
/opt/pbs/bin/qsub -q main@desched1 -m ae -M "${MAILTO:-$USER@ucar.edu}" -o "$CI_ROOT/logs/" \
  -v UPDATE=1,PUBLISH=1,CESMROOT=$CI_ROOT/CESM \
  run_mom_tests.pbs
