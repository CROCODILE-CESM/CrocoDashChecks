"""How long Topo.set_from_dataset() (mom6_forge's GEBCO bathymetry) takes, and its
peak memory:
  - by domain size: from 5 to 40 degrees at 0.1 degree, from full GEBCO;
  - by location: each location matrix.yaml turns on for bathymetry, on that
    location's own grid (across the seams, over the poles), from GEBCO coarsened
    8x (1/30 degree): full GEBCO over a polar cap needs hundreds of GB. Each also
    checks the result: no missing depths, and some ocean.

Needs GEBCO on GLADE; the 40 degree case needs ~60 GB. In the CrocoDash env:
    pytest performance/test_topo.py --benchmark-json=performance/topo.json
"""

from pathlib import Path

import numpy as np
import psutil
import pytest

import matrix
from memtrack import measure_rss

GEBCO_DIR = (
    "/glade/campaign/cesm/cesmdata/inputdata/ocn/mom/croc/crocogallerydata/gebco"
)
GEBCO_PATH = f"{GEBCO_DIR}/GEBCO_2024.nc"
GEBCO_COARSE_PATH = f"{GEBCO_DIR}/GEBCO_2024_coarse_x8.nc"
GEBCO_AVAILABLE = Path(GEBCO_PATH).exists() and Path(GEBCO_COARSE_PATH).exists()
needs_gebco = pytest.mark.skipif(not GEBCO_AVAILABLE, reason="GEBCO is on GLADE only")


def _has_enough_memory_for(domain_deg):
    """domain_deg=40 needs ~60 GB; require >=90 GB headroom (cgroup-aware)."""
    if domain_deg < 40:
        return True
    for cgroup_path in (
        "/sys/fs/cgroup/memory.max",  # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
    ):
        try:
            val = open(cgroup_path).read().strip()
            if val != "max":
                return int(val) / 1024**3 >= 90
            break
        except FileNotFoundError:
            continue
    return psutil.virtual_memory().total / 1024**3 >= 90


def _bench(benchmark, grid, gebco_path, tmp_path):
    """Time one set_from_dataset() call on grid, and return the Topo it made."""
    from mom6_forge.topo import Topo

    topo = Topo(grid, min_depth=10.0, git=False)
    box = {}

    def run():
        result, box["rss_mb"] = measure_rss(
            topo.set_from_dataset,
            bathymetry_path=gebco_path,
            longitude_coordinate_name="lon",
            latitude_coordinate_name="lat",
            vertical_coordinate_name="elevation",
            write_to_file=False,
            output_dir=str(tmp_path),
        )
        return result

    benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
    benchmark.extra_info["rss_mb"] = box.get("rss_mb")
    benchmark.extra_info["n_cells"] = grid.nx * grid.ny
    return topo


@needs_gebco
@pytest.mark.parametrize("domain_deg", [5, 10, 20, 40])
def test_set_from_dataset(benchmark, domain_deg, tmp_path):
    """Topo.set_from_dataset() across domain extents at fixed 0.1° resolution.

    Covers the full pipeline: GEBCO slice -> regrid_dataset_via_xesmf ->
    binary_fill_holes -> depth constraints. Cost is dominated by the size of
    the GEBCO slice (determined by domain extent), not by destination
    resolution.
    """
    if not _has_enough_memory_for(domain_deg):
        pytest.skip(
            f"domain_deg={domain_deg} needs ~60 GB RAM — request a high-memory node"
        )

    from mom6_forge.grid import Grid

    grid = Grid(
        lenx=float(domain_deg),
        leny=float(domain_deg),
        resolution=0.1,
        xstart=0.0,
        ystart=0.0,
    )
    _bench(benchmark, grid, GEBCO_PATH, tmp_path)


@needs_gebco
@pytest.mark.parametrize("location", matrix.locations("bathymetry"))
def test_by_location(benchmark, location, tmp_path):
    topo = _bench(benchmark, matrix.grid(location), GEBCO_COARSE_PATH, tmp_path)
    depth = np.asarray(topo.depth)
    ocean = int((depth > 0).sum())
    benchmark.extra_info.update(location=location, ocean_cells=ocean)
    assert not np.isnan(depth).any(), f"{location}: missing depths"
    assert ocean > 0, f"{location}: no ocean"
