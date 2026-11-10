#!/usr/bin/env python3
"""Daily data-access check: calls every access method CrocoDash registers
(validate_method) for real, and writes health.json next to this file, a
snapshot overwritten each run. Methods that read the user's own files get real
ones from METHOD_ARGS.

Each method runs in its own process, VALIDATE_WORKERS at a time. One still
running after VALIDATE_TIMEOUT is killed with everything it started, and
whatever it downloaded goes with its temp dir. A failing method records its
last error line as `detail`.

Usage (in the CrocoDash env, on GLADE; check.pbs runs it daily on Casper):
    python data_access/check.py
"""

import concurrent.futures
import inspect
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_FILE = Path(__file__).resolve().parent / "health.json"
VALIDATE_TIMEOUT = 900  # seconds per validate_function call (15 min)
VALIDATE_WORKERS = 8  # access methods checked at once

# Inputs for the methods that read files the user points them at, which have
# nothing to read otherwise. Each method gets only the arguments it takes, so
# one table works across CrocoDash branches (freq is newer than main).
HAWAII = (
    "/glade/campaign/cgd/oce/projects/CROCODILE/workshops/2026/dart/hawaii_pmo/ocn/hist"
)
IN_HAWAII = {
    "dates": ["2023-06-15", "2023-06-18"],
    "lat_min": 22.0,
    "lat_max": 23.0,
    "lon_min": 201.0,
    "lon_max": 202.0,
}
METHOD_ARGS = {
    ("cesm_mom_output", "get_mom6_output_data"): {
        **IN_HAWAII,
        "dataset_path": HAWAII,
        "file_glob": "hawaii_pmo.mom6.h.[sz]*.2023-06.nc",  # z-space + surface
        "freq": "D",
    },
    # The same run split one variable per file; see the README there.
    ("cesm_mom_output", "get_mom6_single_variable_data"): {
        **IN_HAWAII,
        "dataset_path": "/glade/work/manishrv/croc_ci/inputs/mom6_tseries",
        "freq": "MS",
    },
    # The gallery's CESM3 restart, on tx2_3v3, and that grid from inputdata.
    ("cice_restart", "get_cice_restart_subset"): {
        "restart_path": "/glade/u/home/dbailey/b.e30_alpha09b.B1850C_MTso.ne30_t233_wgx3.360.cice.r.0201-01-01-00000.nc",
        "grid_path": "/glade/campaign/cesm/cesmdata/inputdata/ocn/mom/tx2_3v3/cice_grid_tx2_3v3_260305_cdf5.nc",
    },
}


def _try_import_crocodash():
    try:
        from CrocoDash.raw_data_access.datasets import load_all_datasets
        from CrocoDash.raw_data_access.registry import ProductRegistry

        load_all_datasets()
        return ProductRegistry
    except Exception as exc:
        print(f"  CrocoDash not importable ({exc.__class__.__name__}: {exc})")
        print("  Skipping validate_function checks.")
        return None


def _validate_one(product, method):
    """Child-process entry point: exit 0 if the access method works.

    BaseProduct.validate_method catches its own exceptions, logs them and
    returns False rather than raising, so the return value is what counts.
    """
    registry = _try_import_crocodash()
    if registry is None:
        sys.exit(1)
    cls = registry.get_product(product)
    takes = inspect.signature(cls._access_methods[method].__func__).parameters
    args = {
        k: v for k, v in METHOD_ARGS.get((product, method), {}).items() if k in takes
    }
    sys.exit(0 if cls.validate_method(method, **args) is not False else 1)


def _failure_detail(output):
    """Why a check failed: its last error line, else its last line, without
    the logger's timestamp/name prefix or validate_method's "Validation failed
    for ...:" preamble."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    line = (errors or lines or [""])[-1]
    line = line.split(" - ERROR - ", 1)[-1]
    if line.startswith("Validation failed for ") and ": " in line:
        line = line.split(": ", 1)[1]
    return line[:300]


def _check_access_method(product, method):
    """Run one validate_function call in its own process group, so a timeout
    can kill it and anything it started (curl, download threads)."""
    tmp = tempfile.mkdtemp(prefix=f"check_{product}_")
    t0 = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, __file__, "--one", product, method],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "TMPDIR": tmp},
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=VALIDATE_TIMEOUT)
        status = "OK  " if proc.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        status = "TIME"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    row = {
        "product": product,
        "method": method,
        "ok": status == "OK  ",
        "elapsed_s": round(time.monotonic() - t0, 2),
    }
    if status == "TIME":
        row["detail"] = f"timed out after {VALIDATE_TIMEOUT} s"
    elif status == "FAIL":
        row["detail"] = _failure_detail(output)
    print(
        f"  func  [{status}] {product} / {method}  ({row['elapsed_s']:.1f}s)"
        + (f"  {row['detail']}" if "detail" in row else "")
    )
    return row


def run_validate_checks(registry):
    """Calls validate_function for every registered (product, method) pair,
    VALIDATE_WORKERS at a time."""
    pairs = [
        (product, method)
        for product in sorted(registry.list_products())
        for method in sorted(registry.list_access_methods(product))
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=VALIDATE_WORKERS) as ex:
        return list(ex.map(lambda pm: _check_access_method(*pm), pairs))


def main():
    # Line-buffered, so a PBS log shows each check as it finishes.
    sys.stdout.reconfigure(line_buffering=True)
    registry = _try_import_crocodash()
    checks = run_validate_checks(registry) if registry is not None else []
    data = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validate_checks": checks,
    }
    OUTPUT_FILE.write_text(json.dumps(data, indent=2))
    ok = sum(1 for r in checks if r["ok"])
    print(f"\n{ok}/{len(checks)} access methods OK; written to {OUTPUT_FILE}")
    if not checks or ok < len(checks):
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--one"]:
        _validate_one(*sys.argv[2:4])
    main()
