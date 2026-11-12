"""The test matrix (matrix.yaml) and the case every check builds (case.yaml).

import matrix
for row in matrix.rows("bc"):             # the grids open boundaries run on
    config = matrix.config(row, workdir)  # that row's CrocoDash case config
"""

import copy
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
GRIDS = yaml.safe_load((ROOT / "matrix.yaml").read_text())["grids"]
CASE = yaml.safe_load((ROOT / "case.yaml").read_text())
FORCINGS = {"bc": "Open boundaries", "runoff": "Runoff mapping"}  # what a row can run

for _name, _row in GRIDS.items():
    _unknown = set(_row.get("forcings", [])) - set(FORCINGS)
    assert not _unknown, f"matrix.yaml: {_name} lists unknown forcings {_unknown}"
    # The CESM runs build every forcing (every compset needs open boundaries, and
    # GLOFAS runoff needs its map), so their rows run each one on its own too.
    _missing = set(FORCINGS) - set(_row.get("forcings", []))
    assert not (
        _row.get("cesm_runs") and _missing
    ), f"matrix.yaml: {_name} has cesm_runs, so it must also list {sorted(_missing)}"


def rows(what=None):
    """Every row, or the rows that run a forcing (or "cesm_runs"), in matrix.yaml's order."""
    if what is None:
        return list(GRIDS)
    if what == "cesm_runs":
        return [name for name, row in GRIDS.items() if row.get("cesm_runs")]
    return [name for name, row in GRIDS.items() if what in row.get("forcings", [])]


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
