"""How long gen_rof_maps() (mom6_forge's GLOFAS runoff -> ocean mapping files)
takes, and its peak memory, against the production ROF mesh: up a ladder of
ocean domains (1 degree box to the Indo-Pacific), and at fixed footprint over
resolutions.

Needs the ROF mesh on GLADE (ROF_MESH_PATH) and a mom6_forge with the
runoff-mapping write-path fix (mom6_forge #125), so run it in the mom6_forge env:
    pytest performance/test_mapping.py --benchmark-json=performance/runoff_mapping.json

Keep every box clear of the 0/360 seam (asserted below): older mom6_forge
silently takes a near-global bbox for a box touching it and never finishes.
"""

import inspect
import shutil
from pathlib import Path

import pytest
import xarray as xr

from memtrack import measure_peak_rss

# Smoothing radii, in km. Matches the real CrocIndoPacific_112 production case,
# which matters at the top end of the sweep: rmax sets the cKDTree ball radius, so
# a larger value multiplies the neighbor count per ocean cell and would make the
# ~2.4M-cell domain's smoothing step dominate everything else.
RMAX_KM = 20
FOLD_KM = 20

# The destination-size ladder, ascending, ~4x per rung: 144 -> 576 -> 2.3K ->
# 9.2K -> 34K -> 116K -> 576K -> 2.4M cells at 1/12 deg.
#   box -> (xstart, lenx, ystart, leny) in degrees east / north
#
# The four `box_*` rungs are square boxes anchored at the Gulf of Mexico's
# southwest corner, so they nest inside the gulf_of_mexico rung: the small end of
# the sweep is literally a zoom-in on the smallest real configuration, not an
# unrelated patch of ocean. They sit below any domain anyone would actually
# configure, and exist to show where the curve starts before real-case sizes take
# over. From gulf_of_mexico up, every rung is a domain CROC really builds.
#
# Keep every box clear of the 0/360 periodic seam -- see the assertion below. The
# north_atlantic rung was originally (280.0, 80.0, ...), whose eastern edge lands on
# exactly lon 360, and it did not complete in over an hour at ~98% CPU. Shifted 5 deg
# west, the identical 576K-cell case finishes in 106 s. There is no destination-size
# cliff here; there was one malformed box. The underlying bbox bug is fixed (mom6_forge
# PR #125), but the ladder stays off-seam so its numbers remain comparable.
DOMAINS = {
    "box_1deg": {"box": (262.0, 1.0, 18.0, 1.0)},
    "box_2deg": {"box": (262.0, 2.0, 18.0, 2.0)},
    "box_4deg": {"box": (262.0, 4.0, 18.0, 4.0)},
    "box_8deg": {"box": (262.0, 8.0, 18.0, 8.0)},
    "gulf_of_mexico": {"box": (262.0, 18.0, 18.0, 13.0)},
    "caribbean": {"box": (270.0, 35.0, 5.0, 23.0)},
    # lon 275..355, not 280..360: 280 + 80 = 360 puts the eastern edge on the seam.
    "north_atlantic": {"box": (275.0, 80.0, 20.0, 50.0)},
    # Sized to the existing CrocIndoPacific_112 case: ~1920x1260 = 2.4M cells at 1/12 deg.
    "indo_pacific": {"box": (30.0, 160.0, -45.0, 105.0)},
}

# A destination mesh whose nodes land on exactly lon 360 has 601 nodes at 360.0, which
# normalizes to 0.0 -- and a pre-PR-#125 mom6_forge then reports a near-global longitude
# bbox for it, which disables map_overlap's longitude masking so the regrid runs against
# the whole global latitude band. It does not finish in any practical time, with no error
# and no memory growth to hint at the cause. Fixed now, but fail loudly at import anyway:
# this ladder was measured off-seam, and against an older mom6_forge a reintroduced seam
# box would silently hang a run for an hour.
for _name, _spec in DOMAINS.items():
    _xstart, _lenx, _, _ = _spec["box"]
    assert _xstart > 0 and _xstart + _lenx < 360, (
        f"domain {_name!r} touches the 0/360 periodic seam "
        f"(lon {_xstart}..{_xstart + _lenx}); shift it -- this ladder's numbers were "
        f"measured off-seam, and on a pre-PR-#125 mom6_forge gen_rof_maps will hang"
    )

# Destination resolution for the domain sweep — 1/12 deg, the resolution the real
# CARIB12 / CrocIndoPacific_112 cases run at.
DOMAIN_SWEEP_RESOLUTION_DEG = 1 / 12

# Resolutions for the resolution sweep, held over one fixed domain.
RESOLUTIONS_DEG = [1 / 4, 1 / 8, 1 / 12, 1 / 25]
RESOLUTION_SWEEP_DOMAIN = "gulf_of_mexico"

ROF_MESH_PATH = "/glade/campaign/cesm/cesmdata/inputdata/lnd/dlnd7/GLOFAS/GLOFAS.v4.dis24.ESMFmesh_20260501.nc"


def _mesh_available():
    return bool(ROF_MESH_PATH) and Path(ROF_MESH_PATH).exists()


def _has_write_path_fix():
    """True if the installed mom6_forge writes mapping files via the fast path.

    Writing a large fixed-size variable straight to NETCDF3_64BIT (the format
    CESM mapping files must be in) triggers a backward-seeking 8 KB
    read-modify-write loop in libnetcdf's classic writer. mom6_forge works
    around it by writing NETCDF4 and converting with `nccopy -6`. Without that
    workaround a single run here takes ~36 minutes and peaks near 13 GB, and on
    mom6_forge `main` before the shape-lookup fix it does not complete at all
    (OOM at ~29 GB) — so skip rather than silently burn hours.

    Probes for the `nccopy` call because that is the fix's observable signature;
    update this probe if the write path is ever reimplemented another way.
    """
    import mom6_forge.mapping as mapping

    return "nccopy" in inspect.getsource(mapping)


_ELEMENT_COUNT_CACHE = {}


def _element_count(mesh_path):
    """Element count of an ESMF mesh, read from the header only and cached.

    Opening the 1.3 GB production mesh over GLADE costs tens of seconds, and the
    sweeps touch it once per case — read it once per session instead.
    """
    key = str(mesh_path)
    if key not in _ELEMENT_COUNT_CACHE:
        with xr.open_dataset(mesh_path) as ds:
            _ELEMENT_COUNT_CACHE[key] = int(ds.sizes["elementCount"])
    return _ELEMENT_COUNT_CACHE[key]


def _write_ocean_mesh(domain, resolution_deg, path):
    """Build an ocean ESMF mesh for a named domain, as mom6_forge's own tests do —
    no real case files needed, just a Grid and its supergrid."""
    from mom6_forge.grid import Grid

    xstart, lenx, ystart, leny = DOMAINS[domain]["box"]
    grid = Grid(
        resolution=resolution_deg,
        xstart=xstart,
        lenx=lenx,
        ystart=ystart,
        leny=leny,
        name=f"rof_bench_{domain}",
    )
    grid.supergrid.to_esmf_mesh(str(path), mask="all_unmasked")
    return path, grid.tlon.size


def _run_gen_rof_maps(benchmark, domain, resolution_deg, tmp_path, label):
    """Shared body for both sweeps: build the ocean mesh, time one gen_rof_maps()
    call over it, and record the parameters that make the number interpretable."""
    if not _mesh_available():
        pytest.skip("production ROF mesh not configured — GLADE only")
    if not _has_write_path_fix():
        pytest.skip(
            "installed mom6_forge lacks the mapping write-path fix "
            "from mom6_forge PR #125 — a run would take ~36 min; "
            "use the mom6_forge conda env"
        )

    from mom6_forge.mapping import gen_rof_maps

    ocn_mesh_path, n_dst = _write_ocean_mesh(
        domain, resolution_deg, tmp_path / "ocn_mesh.nc"
    )
    output_dir = tmp_path / "mapping"
    box = {}

    def run():
        # gen_rof_maps() skips work when its output already exists, and the
        # output files are ~2.2 GB each — clear the directory so a repeat round
        # measures the real cost, and so nothing accumulates on scratch.
        if output_dir.exists():
            shutil.rmtree(output_dir)
        result, box["peak_rss_mb"] = measure_peak_rss(
            gen_rof_maps,
            rof_mesh_path=ROF_MESH_PATH,
            ocn_mesh_path=ocn_mesh_path,
            output_dir=output_dir,
            mapping_file_prefix=f"bench_{label}_map",
            rmax=RMAX_KM,
            fold=FOLD_KM,
        )
        return result

    try:
        benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    # Peak, not delta: these cases share one process and the 21.6M-element mesh
    # allocations get reused, so a delta reads as ~0 (or negative) after the first
    # case. See measure_peak_rss's docstring.
    benchmark.extra_info["peak_rss_mb"] = box.get("peak_rss_mb")
    benchmark.extra_info["domain"] = domain
    benchmark.extra_info["resolution_deg"] = resolution_deg
    benchmark.extra_info["n_src"] = _element_count(ROF_MESH_PATH)
    benchmark.extra_info["n_dst"] = n_dst


@pytest.mark.parametrize("domain", list(DOMAINS))
def test_gen_rof_maps_domain(benchmark, domain, tmp_path):
    """gen_rof_maps() across an ascending ocean-domain ladder at fixed 1/12 deg.

    Times the whole call — nearest-neighbor map + smoothed map, including both
    NETCDF3_64BIT writes — since that is what a CrocoDash case actually pays when
    process_forcings() generates runoff mapping files.
    """
    _run_gen_rof_maps(
        benchmark,
        domain,
        DOMAIN_SWEEP_RESOLUTION_DEG,
        tmp_path,
        label=domain,
    )


@pytest.mark.parametrize("resolution_deg", RESOLUTIONS_DEG)
def test_gen_rof_maps_resolution(benchmark, resolution_deg, tmp_path):
    """gen_rof_maps() across ocean resolutions over one fixed domain.

    Geographic footprint is held constant, so the source/destination overlap
    window and the set of contributing rivers do not change — only the
    destination cell count does.
    """
    _run_gen_rof_maps(
        benchmark,
        RESOLUTION_SWEEP_DOMAIN,
        resolution_deg,
        tmp_path,
        label=f"res_{round(1 / resolution_deg)}",
    )
