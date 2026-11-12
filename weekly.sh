#!/bin/bash
# The weekly run of every check, from a fresh clone of this repo:
#
#   bash weekly.sh <CESMROOT>
#
# CESMROOT is a checkout of CROCODILE-CESM/CESM branch crocodash that the run
# keeps at that branch's tip (it must have no local changes). The one crontab
# line on cron.hpc.ucar.edu (site/how_it_works.md) starts a small Casper job
# that clones this repo into a temporary directory and runs this script from
# it; the cron host itself has no git. Each run gets its own directory, and runs
# older than four weeks are deleted:
#
#   /glade/derecho/scratch/$USER/crocodashchecks/<date>/
#     CrocoDashChecks/   this repo as of this run, which the jobs run from
#     logs/              the jobs' logs
#
# It submits the workflow (every grid's case, its forcings and the CESM runs) to
# Derecho and the data-access check to Casper. Each job clones CrocoDash main
# itself and publishes its own results.
#
# MAILTO : where PBS mails when a job ends (default: $USER@ucar.edu)
# QSUB   : the qsub to use (default: /opt/pbs/bin/qsub); QSUB=echo only prints the submissions
set -euo pipefail

CESMROOT=${1:?usage: weekly.sh <CESMROOT>}
ROOT=/glade/derecho/scratch/$USER/crocodashchecks
RUN=$ROOT/$(date +%F_%H%M)
QSUB=${QSUB:-/opt/pbs/bin/qsub}
OPTS=(-m ae -M "${MAILTO:-$USER@ucar.edu}" -o "$RUN/logs/")

mkdir -p "$RUN/logs"
cp -r "$(cd "$(dirname "$0")" && pwd)" "$RUN/CrocoDashChecks"
cd "$RUN/CrocoDashChecks"

$QSUB -q main@desched1 "${OPTS[@]}" -v "PUBLISH=1,CESMROOT=$CESMROOT" integration/workflow.pbs
$QSUB -q casper@casper-pbs "${OPTS[@]}" -v PUBLISH=1 data_access/check.pbs

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +27 -exec rm -rf {} +
