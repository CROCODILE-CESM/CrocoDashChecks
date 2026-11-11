# Source this before any check, so it tests the latest CrocoDash. It clones
# CrocoDash main fresh, with its submodules, puts the clone first on
# PYTHONPATH (ahead of the CrocoDash the conda env has installed), and deletes
# the clone when the job or shell exits.
#
#   conda activate CrocoDash
#   source crocodash_main.sh
#   pytest integration/test_workflow.py ...
#
# Both scheduled jobs (integration/run_mom_tests.pbs, data_access/check.pbs)
# source it too.
#
# CROCODASH_BRANCH : branch to clone instead of main
# CLONE_ROOT       : where the clone goes (default: /glade/derecho/scratch/$USER)
#
# Sets CROCODASH_SRC to the clone; the checks record its branch and commit.

CROCODASH_SRC=$(mktemp -d "${CLONE_ROOT:-/glade/derecho/scratch/$USER}/crocodash_clone.XXXXXX") || return 1
export CROCODASH_SRC
trap 'rm -rf "$CROCODASH_SRC"' EXIT
git clone -q --recurse-submodules -b "${CROCODASH_BRANCH:-main}" \
  https://github.com/CROCODILE-CESM/CrocoDash "$CROCODASH_SRC" || return 1

# CrocoDash and the packages it embeds as submodules.
_cd=$CROCODASH_SRC/CrocoDash
export PYTHONPATH=$CROCODASH_SRC:$_cd/rm6:$_cd/visualCaseGen:$_cd/visualCaseGen/ProConPy:$_cd/visualCaseGen/external/mom6_forge:$_cd/visualCaseGen/external/ipyfilechooser:$CROCODASH_SRC/gallery${PYTHONPATH:+:$PYTHONPATH}
unset _cd

echo "Testing CrocoDash $(git -C "$CROCODASH_SRC" rev-parse --abbrev-ref HEAD) at $(git -C "$CROCODASH_SRC" rev-parse --short HEAD), cloned to $CROCODASH_SRC"
