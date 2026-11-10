"""How long Topo.set_from_dataset() (mom6_forge's GEBCO bathymetry) takes, and its
peak memory, as the domain grows from 5 to 40 degrees at 0.1 degree.

Needs GEBCO on GLADE (GEBCO_PATH); the 40 degree case needs ~60 GB. In the
CrocoDash env:
    pytest performance/test_topo.py --benchmark-json=performance/topo.json
"""

from pathlib import Path

import psutil
import pytest

from memtrack import measure_rss

GEBCO_PATH = "/glade/campaign/cesm/cesmdata/inputdata/ocn/mom/croc/crocogallerydata/gebco/GEBCO_2024.nc"
GEBCO_AVAILABLE = bool(GEBCO_PATH) and Path(GEBCO_PATH).exists()


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


@pytest.mark.skipif(
    not GEBCO_AVAILABLE, reason="GEBCO_2024.nc not configured — GLADE only"
)
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
    from mom6_forge.topo import Topo

    grid = Grid(
        lenx=float(domain_deg),
        leny=float(domain_deg),
        resolution=0.1,
        xstart=0.0,
        ystart=0.0,
    )
    topo = Topo(grid, min_depth=10.0, git=False)
    box = {}

    def run():
        result, box["rss_mb"] = measure_rss(
            topo.set_from_dataset,
            bathymetry_path=GEBCO_PATH,
            longitude_coordinate_name="lon",
            latitude_coordinate_name="lat",
            vertical_coordinate_name="elevation",
            write_to_file=False,
            output_dir=str(tmp_path),
        )
        return result

    benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
    benchmark.extra_info["rss_mb"] = box.get("rss_mb")
