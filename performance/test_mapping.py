"""How long gen_rof_maps() (mom6_forge's GLOFAS runoff -> ocean mapping files)
takes, and its peak memory, against the production ROF mesh: up a ladder of
ocean domains (1 degree box to the Indo-Pacific), at fixed footprint over
resolutions, and over the smoothing radius rmax. Each case also records how many
weights (n_s) the two maps hold, which is what CESM's coupler pays for. It also
runs at each location matrix.yaml turns on for runoff_mapping (none by default).

Needs the ROF mesh and the coarsened GEBCO (for the land mask) on GLADE, and a
mom6_forge with a fast mapping write path (see _has_write_path_fix; the one in
CrocoDash has it). In the CrocoDash env, in a PBS job with 100 GB or more:
    pytest performance/test_mapping.py --benchmark-json=performance/runoff_mapping.json

Keep every box clear of the 0/360 seam (asserted below): older mom6_forge
silently takes a near-global bbox for a box touching it and never finishes.
"""

import inspect
import shutil
from pathlib import Path

import numpy as np
import psutil
import pytest
import xarray as xr
from scipy import ndimage

import matrix
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

# The rmax sweep: smoothing radius at fixed 1/12 deg, over real domains.
#
# What the weight counts are, from mom6_forge.mapping.gen_rof_maps:
#   - nearest-neighbor map: every GLOFAS cell inside the ocean mesh's lon/lat box maps
#     to its one nearest coastal ocean cell. GLOFAS's mask is all ones, so its ocean
#     and inland cells count too: n_s = GLOFAS cells in the box (box area / 0.05 deg^2),
#     whatever the ocean resolution, mask or rmax.
#   - smoothed map: each of those cells is then spread over every ocean cell within
#     rmax (crow's-fly) of its coastal cell, found by a BFS through ocean cells, so
#     n_s = sum over source cells of that neighborhood's size, ~ (rmax / dx)^2 each.
#
# fold = rmax. fold only sets the weight values, exp(-d / fold); which cells get a
# weight is set by rmax alone (the BFS cutoff), so n_s, time and memory do not depend
# on fold. Tying fold to rmax keeps the kernel's shape the same at every radius (a cell
# at the rim gets e^-1 of the center's weight), and makes the rmax = 20 cases the same
# configuration as the two sweeps above (RMAX_KM = FOLD_KM = 20). A fixed fold = 20 at
# rmax = 80 would store weights down to e^-4 (2%) of the center's: paying the full
# memory cost of the big radius for weights that barely move any runoff.
#
# indo_pacific at rmax = 80 is the biggest case here: predicted from geometry (each
# GLOFAS cell's nearest coastal cell, times the ocean cells within rmax of it; this
# matched the two smaller domains' measured n_s to 0.5%) at 1.66e9 weights, 77% of
# 2^31, ~90 GB and a 29 GB file. rmax = 100 there would pass 2^31 (2.55e9), so the
# sweep stops at 80.
RMAX_SWEEP_KM = [10, 20, 40, 80]
RMAX_SWEEP_DOMAINS = ["gulf_of_mexico", "north_atlantic", "indo_pacific"]
RMAX_SWEEP_RESOLUTION_DEG = 1 / 12

ROF_MESH_PATH = "/glade/campaign/cesm/cesmdata/inputdata/lnd/dlnd7/GLOFAS/GLOFAS.v4.dis24.ESMFmesh_20260501.nc"

# The land mask for the ocean meshes. Since mom6_forge PR #137, gen_rof_maps maps
# runoff only onto coastal ocean cells (ocean cells with a land neighbor) and smooths
# only from them, so an all-ocean mesh has nowhere to put runoff and the call raises
# "maps no runoff at all". GEBCO coarsened to 1/30 deg (117 MB) is plenty for a mask
# at 1/12 deg and coarser.
GEBCO_MASK_PATH = "/glade/campaign/cesm/cesmdata/inputdata/ocn/mom/croc/crocogallerydata/gebco/GEBCO_2024_coarse_x8.nc"


def _mesh_available():
    return all(p and Path(p).exists() for p in (ROF_MESH_PATH, GEBCO_MASK_PATH))


def _has_write_path_fix():
    """True if the installed mom6_forge writes mapping files via a fast path.

    Writing a large fixed-size variable straight to NETCDF3_64BIT triggers a
    backward-seeking 8 KB read-modify-write loop in libnetcdf's classic writer.
    Without a workaround a single run here takes ~36 minutes and peaks near
    13 GB, and on mom6_forge `main` before the shape-lookup fix it does not
    complete at all (OOM at ~29 GB) — so skip rather than silently burn hours.

    mom6_forge has avoided it two ways: writing NETCDF4 and converting with
    `nccopy -6` (PR #125), and, since PR #137, writing NETCDF4_CLASSIC
    directly. Probe for either; update this if the write path changes again.
    """
    import mom6_forge.mapping as mapping

    return "nccopy" in inspect.getsource(mapping) or 'format="NETCDF4' in (
        inspect.getsource(mapping.write_mapping_file)
    )


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


def _ocean_mask(grid):
    """1 where GEBCO is below sea level at the cell center, in the largest connected
    body of water; 0 elsewhere. Keeping only the largest body stops lakes and the
    Caspian from adding coastline a real case's topography would not have."""
    lon = (grid.tlon.values + 180) % 360 - 180  # GEBCO runs -180..180
    with xr.open_dataset(GEBCO_MASK_PATH) as ds:
        elevation = (
            ds["elevation"]
            .sel(
                lon=xr.DataArray(lon, dims=("y", "x")),
                lat=xr.DataArray(grid.tlat.values, dims=("y", "x")),
                method="nearest",
            )
            .values
        )
    labels, n = ndimage.label(elevation < 0)
    if n == 0:
        return np.zeros(labels.shape, dtype=np.int32)
    largest = np.bincount(labels.ravel())[1:].argmax() + 1
    return (labels == largest).astype(np.int32)


def _write_ocean_mesh(domain, resolution_deg, path, grid=None):
    """Build an ocean ESMF mesh for a named domain (or a given grid), as
    mom6_forge's own tests do: no real case files needed, just a Grid, its
    supergrid and a GEBCO land mask.

    Returns the path, the cell count, the ocean cell count, the coastal cell
    count (by gen_rof_maps' own definition: the cells runoff lands on), and the
    mean ocean cell area in km^2 (the smoothed map's weights scale as rmax^2 over it).
    """
    from mom6_forge.grid import Grid
    from mom6_forge.mapping import extract_coastline_mask, grid_from_esmf_mesh

    if grid is None:
        xstart, lenx, ystart, leny = DOMAINS[domain]["box"]
        grid = Grid(
            resolution=resolution_deg,
            xstart=xstart,
            lenx=lenx,
            ystart=ystart,
            leny=leny,
            name=f"rof_bench_{domain}",
        )
    mask = _ocean_mask(grid)
    grid.supergrid.to_esmf_mesh(str(path), mask=mask)
    n_coast = int(extract_coastline_mask(grid_from_esmf_mesh(str(path))).sum())
    cell_km2 = float(grid.tarea.values[mask == 1].mean() / 1e6)
    return path, grid.tlon.size, int(mask.sum()), n_coast, cell_km2


def _run_gen_rof_maps(
    benchmark,
    domain,
    resolution_deg,
    tmp_path,
    label,
    rmax=RMAX_KM,
    fold=FOLD_KM,
    grid=None,
):
    """Shared body for all three sweeps: build the ocean mesh, time one
    gen_rof_maps() call over it, and record the parameters that make the number
    interpretable, and the size of the maps it wrote."""
    if not _mesh_available():
        pytest.skip("production ROF mesh or GEBCO not configured — GLADE only")
    if not _has_write_path_fix():
        pytest.skip(
            "installed mom6_forge lacks a fast mapping write path "
            "(mom6_forge PR #125 or #137) — a run would take ~36 min; "
            "update CrocoDash's mom6_forge submodule"
        )

    import mom6_forge.mapping as mapping
    from mom6_forge.mapping import (
        gen_rof_maps,
        get_nn_map_filepath,
        get_smoothed_map_filepath,
    )

    ocn_mesh_path, n_dst, n_ocn, n_coast, cell_km2 = _write_ocean_mesh(
        domain, resolution_deg, tmp_path / "ocn_mesh.nc", grid=grid
    )
    if n_coast == 0:
        pytest.skip(
            f"{domain} has no coastal ocean cells under the GEBCO mask, so "
            "gen_rof_maps has nowhere to put runoff"
        )
    output_dir = tmp_path / "mapping"
    prefix = f"bench_{label}_map"
    maps = {
        "nn": get_nn_map_filepath(prefix, output_dir),
        "nnsm": get_smoothed_map_filepath(prefix, output_dir, rmax, fold),
    }
    box = {}

    def run():
        # gen_rof_maps() skips work when its output already exists, and the
        # output files are 2 GB and up — clear the directory so a repeat round
        # measures the real cost, and so nothing accumulates on scratch.
        if output_dir.exists():
            shutil.rmtree(output_dir)
        # mom6_forge caches cell areas for its last two mesh files. Each case brings
        # a new ocean mesh, so the cache would evict the GLOFAS areas every other case
        # and those cases would skip computing them (~16 s and ~8 GB). A CrocoDash
        # case calls gen_rof_maps once, cold, so measure every call that way.
        getattr(mapping, "_CELL_AREA_CACHE", {}).clear()
        box["rss_before_mb"] = psutil.Process().memory_info().rss / 1024**2
        result, box["peak_rss_mb"] = measure_peak_rss(
            gen_rof_maps,
            rof_mesh_path=ROF_MESH_PATH,
            ocn_mesh_path=ocn_mesh_path,
            output_dir=output_dir,
            mapping_file_prefix=prefix,
            rmax=rmax,
            fold=fold,
        )
        return result

    try:
        benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
        # n_s is what the coupler pays for (a route handle per map, per weight),
        # so record it from the files themselves, before they are deleted.
        for key, path in maps.items():
            with xr.open_dataset(path) as ds:
                benchmark.extra_info[f"{key}_n_s"] = int(ds.sizes["n_s"])
            benchmark.extra_info[f"{key}_file_mb"] = path.stat().st_size / 1024**2
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    # Peak, not delta: these cases share one process and the 21.6M-element mesh
    # allocations get reused, so a delta reads as ~0 (or negative) after the first
    # case. See measure_peak_rss's docstring. rss_before_mb is what the process
    # already held when the call started, which bounds how much of the peak an
    # earlier case left behind.
    benchmark.extra_info["peak_rss_mb"] = box.get("peak_rss_mb")
    benchmark.extra_info["rss_before_mb"] = box.get("rss_before_mb")
    benchmark.extra_info["domain"] = domain
    benchmark.extra_info["resolution_deg"] = resolution_deg
    benchmark.extra_info["rmax_km"] = rmax
    benchmark.extra_info["fold_km"] = fold
    benchmark.extra_info["n_src"] = _element_count(ROF_MESH_PATH)
    benchmark.extra_info["n_dst"] = n_dst
    benchmark.extra_info["n_ocn"] = n_ocn
    benchmark.extra_info["n_coast"] = n_coast
    benchmark.extra_info["ocn_cell_km2"] = cell_km2


@pytest.mark.parametrize("domain", list(DOMAINS))
def test_gen_rof_maps_domain(benchmark, domain, tmp_path):
    """gen_rof_maps() across an ascending ocean-domain ladder at fixed 1/12 deg.

    Times the whole call — nearest-neighbor map + smoothed map, including both
    writes — since that is what a CrocoDash case actually pays when
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


@pytest.mark.parametrize(
    "domain, rmax",
    [
        pytest.param(domain, rmax, id=f"{domain}-r{rmax}")
        for domain in RMAX_SWEEP_DOMAINS
        for rmax in RMAX_SWEEP_KM
    ],
)
def test_gen_rof_maps_rmax(benchmark, domain, rmax, tmp_path):
    """gen_rof_maps() across smoothing radii, at fixed 1/12 deg, with fold = rmax.

    The nearest-neighbor map is the same at every radius; the smoothed map's
    weight count grows like rmax^2, and with it the time, the memory and the
    coupler's route-handle cost.
    """
    _run_gen_rof_maps(
        benchmark,
        domain,
        RMAX_SWEEP_RESOLUTION_DEG,
        tmp_path,
        label=f"{domain}_r{rmax}",
        rmax=rmax,
        fold=rmax,
    )


@pytest.mark.parametrize("location", matrix.locations("runoff_mapping"))
def test_gen_rof_maps_location(benchmark, location, tmp_path):
    """gen_rof_maps() on each location matrix.yaml turns on for runoff_mapping,
    on that location's own grid (across the seams, over the poles)."""
    _run_gen_rof_maps(
        benchmark,
        location,
        None,
        tmp_path,
        label=location,
        grid=matrix.grid(location, name=f"rof_bench_{location}"),
    )
