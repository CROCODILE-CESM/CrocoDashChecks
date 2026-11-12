#!/bin/bash
# The weekly run of every check, from a fresh clone of this repo. The one crontab
# line on cron.hpc.ucar.edu (site/how_it_works.md) starts a small Casper job that
# clones this repo into a temporary directory and runs this script from it; the
# cron host itself has no git. Nothing is kept between runs except each run's
# directory, and runs older than four weeks are deleted:
#
#   /glade/derecho/scratch/$USER/crocodashchecks/<date>/
#     CrocoDashChecks/   this repo as of this run, which the jobs run from
#     CESM/              CESM's crocodash branch, cloned fresh by the CESM runs
#     logs/              the jobs' logs
#
# It submits the workflow and the data-access check to Casper and the CESM runs
# to Derecho. Each job clones CrocoDash main itself and publishes its own results.
#
# MAILTO : where PBS mails when a job ends (default: $USER@ucar.edu)
# QSUB   : the qsub to use (default: /opt/pbs/bin/qsub); QSUB=echo only prints the submissions
set -euo pipefail

ROOT=/glade/derecho/scratch/$USER/crocodashchecks
RUN=$ROOT/$(date +%F_%H%M)
QSUB=${QSUB:-/opt/pbs/bin/qsub}
OPTS=(-m ae -M "${MAILTO:-$USER@ucar.edu}" -o "$RUN/logs/")

mkdir -p "$RUN/logs"
cp -r "$(cd "$(dirname "$0")" && pwd)" "$RUN/CrocoDashChecks"
cd "$RUN/CrocoDashChecks"

$QSUB -q casper@casper-pbs "${OPTS[@]}" -v PUBLISH=1 integration/workflow.pbs
$QSUB -q casper@casper-pbs "${OPTS[@]}" -v PUBLISH=1 data_access/check.pbs
# run_mom_tests.pbs finds its scripts from where it was submitted.
(cd integration && $QSUB -q main@desched1 "${OPTS[@]}" -v "PUBLISH=1,CESMROOT=$RUN/CESM" run_mom_tests.pbs)

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +27 -exec rm -rf {} +
