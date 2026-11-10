#!/usr/bin/env bash
#PBS -N checks_bench
#PBS -l select=1:ncpus=8:mem=128GB
#PBS -l walltime=08:00:00
#PBS -q casper
#PBS -A NCGD0011
#PBS -j oe
#PBS -o /glade/u/home/manishrv/documents/croc/dev/SeaSloth/pbs_bench.log
#
# pbs_submit.sh — PBS job for the full perf-benchmark suite on Casper.
# Runs everything, including suites that require GEBCO or GLORYS data.
# Submit with: qsub scripts/pbs_submit.sh

set -euo pipefail
module load conda
conda activate CrocoDash

REPO_ROOT="${PBS_O_WORKDIR:-/glade/u/home/manishrv/documents/croc/dev/SeaSloth}"
cd "$REPO_ROOT"

echo "=== CrocoDashChecks HPC benchmarks: $(date) ==="
echo "Node: $(hostname)"

bash scripts/run_benchmarks.sh

echo ""
echo "=== Done: $(date) ==="
echo "Commit results and rebuild the report page from the login node:"
echo "  git add results/latest.json && git commit -m 'bench: <description>' && git push"
echo "  python scripts/generate_report.py"
