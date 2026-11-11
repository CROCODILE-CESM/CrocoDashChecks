"""The test matrix in matrix.yaml: which checks run at which locations, and
the grid each location stands for.

    import matrix
    for location in matrix.locations("open_boundaries"):
        grid = matrix.grid(location)
"""

from pathlib import Path

import yaml

MATRIX = yaml.safe_load((Path(__file__).resolve().parent / "matrix.yaml").read_text())


def locations(check):
    """The locations a check runs at, in matrix.yaml's order."""
    names = MATRIX["checks"][check] or []
    unknown = [n for n in names if n not in MATRIX["locations"]]
    assert not unknown, f"matrix.yaml: {check} lists undefined locations {unknown}"
    return names


def is_polar(location):
    return "crs" in MATRIX["locations"][location]["grid"]


def grid(location, name=None):
    """A location's mom6_forge Grid: a lat/lon box, or a polar stereographic
    square centred on the pole."""
    from mom6_forge.grid import Grid

    spec = MATRIX["locations"][location]["grid"]
    name = name or location
    if is_polar(location):
        half = spec["width_km"] * 1e3 / 2
        return Grid.from_projection(
            spec["crs"],
            -half,
            half,
            -half,
            half,
            spec["resolution_km"] * 1e3,
            name=name,
        )
    return Grid(**spec, name=name)
