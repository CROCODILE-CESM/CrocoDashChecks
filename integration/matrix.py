"""The matrix (matrix.yaml) and the case every check builds (case.yaml).

import matrix
for row in matrix.rows("bc"):             # the grids open boundaries run on
    config = matrix.config(row, workdir)  # that row's CrocoDash case config

    python integration/matrix.py testing  # a suite's rows, for weekly.sh
"""

import copy
import sys
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
_MATRIX = yaml.safe_load((ROOT / "matrix.yaml").read_text())
SUITES = {suite: _MATRIX[suite] for suite in ("testing", "performance")}
GRIDS = {**SUITES["testing"], **SUITES["performance"]}  # every row
assert len(GRIDS) == sum(
    map(len, SUITES.values())
), "matrix.yaml: a row is in both suites"
CASE = yaml.safe_load((ROOT / "case.yaml").read_text())
FORCINGS = {"bc": "Open boundaries", "runoff": "Runoff mapping"}  # what a row can run

# A testing row's `crocodash create` processes every forcing, and its CESM runs
# use that case; a performance row's case is only configured, then each forcing
# it lists is timed on its own.
for _name, _row in SUITES["testing"].items():
    assert (
        "forcings" not in _row
    ), f"matrix.yaml: {_name}: forcings are for performance rows"
for _name, _row in SUITES["performance"].items():
    _unknown = set(_row.get("forcings", [])) - set(FORCINGS)
    assert not _unknown, f"matrix.yaml: {_name} lists unknown forcings {_unknown}"
    assert not _row.get(
        "cesm_runs"
    ), f"matrix.yaml: {_name}: cesm_runs is for testing rows"


def rows(what=None, suite=None):
    """Every row (or a suite's), or the rows that run a forcing (or "cesm_runs"),
    in matrix.yaml's order."""
    grids = GRIDS if suite is None else SUITES[suite]
    if what is None:
        return list(grids)
    if what == "cesm_runs":
        return [name for name, row in grids.items() if row.get("cesm_runs")]
    return [name for name, row in grids.items() if what in row.get("forcings", [])]


def is_polar(row):
    return "crs" in GRIDS[row]["grid"]


def _merge(base, changes):
    """base with changes merged in, section by section."""
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def config(row, workdir):
    """A row's CrocoDash case config: case.yaml, the row's changes to it, and
    its grid. A CrocoDash config builds only latitude/longitude boxes, so a
    polar grid is written to a supergrid file in workdir first."""
    cfg = _merge(copy.deepcopy(CASE), GRIDS[row].get("case", {}))
    spec = GRIDS[row]["grid"]
    if is_polar(row):
        from mom6_forge.grid import Grid

        half = spec["width_km"] * 1e3 / 2
        path = Path(workdir) / "polar_supergrid.nc"
        Grid.from_projection(
            spec["crs"], -half, half, -half, half, spec["resolution_km"] * 1e3, name=row
        ).write_supergrid(str(path))
        cfg["grid"] = {"supergrid_path": str(path), "name": row}
    else:
        resolution = float(Fraction(str(spec["resolution"])))
        cfg["grid"] = {**spec, "resolution": resolution, "name": row}
    return cfg


if __name__ == "__main__":
    print(*rows(suite=sys.argv[1]))
