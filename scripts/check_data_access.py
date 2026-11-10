#!/usr/bin/env python3
"""
check_data_access.py — Data-access health check: HTTP link reachability
and raw-function validation (validate_function) for every registered
CrocoDash product.

Always runs:
  • Link checks — HTTP HEAD/GET on URLs in benchmarks/link_config.json

Also runs when CrocoDash is importable (i.e. on GLADE/Derecho with the
CrocoDash conda env active):
  • validate_function — toy-calls every registered access method via
    ProductRegistry.validate_function(), each in its own process,
    VALIDATE_WORKERS at a time. A call still running after VALIDATE_TIMEOUT
    is killed with everything it started, and whatever it downloaded goes
    with its temp dir.

Writes a single results/health.json, always overwritten — this is a
snapshot of current status, not a history.

Usage
-----
    conda run -n CrocoDash python scripts/check_data_access.py
"""

import concurrent.futures
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

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / "benchmarks" / "link_config.json"
OUTPUT_FILE = REPO_ROOT / "results" / "health.json"

LINK_TIMEOUT = 20
VALIDATE_TIMEOUT = 900  # seconds per validate_function call (15 min)
VALIDATE_WORKERS = 8  # access methods checked at once


def _check_link(url):
    """HEAD with GET fallback. Returns (ok: bool, elapsed_seconds)."""
    t0 = time.monotonic()
    try:
        r = requests.head(url, allow_redirects=True, timeout=LINK_TIMEOUT)
        if r.status_code == 200:
            return True, time.monotonic() - t0
    except Exception:
        pass
    t0 = time.monotonic()
    try:
        r = requests.get(url, stream=True, allow_redirects=True, timeout=LINK_TIMEOUT)
        next(r.iter_content(chunk_size=1), None)
        return r.status_code == 200, time.monotonic() - t0
    except Exception:
        return False, time.monotonic() - t0


def run_link_checks(products):
    rows = []
    for product, url in sorted(products.items()):
        ok, elapsed = _check_link(url)
        rows.append(
            {"product": product, "url": url, "ok": ok, "elapsed_s": round(elapsed, 2)}
        )
        print(
            f"  link  [{'OK  ' if ok else 'FAIL'}] {product}: {url}  ({elapsed:.1f}s)"
        )
    return rows


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
    ok = (
        registry is not None
        and registry.validate_function(product, method) is not False
    )
    sys.exit(0 if ok else 1)


def _failure_detail(output):
    """The line most likely to say why a check failed: its last error line,
    else its last line."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    return (errors or lines or [""])[-1][:300]


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
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(CONFIG_FILE.read_text())
    products = cfg.get("products", {})

    print("=== Link checks ===")
    link_checks = run_link_checks(products)
    link_ok = sum(1 for r in link_checks if r["ok"])

    print("\n=== validate_function checks ===")
    validate_checks = []
    registry = _try_import_crocodash()
    if registry is not None:
        validate_checks = run_validate_checks(registry)
    val_ok = sum(1 for r in validate_checks if r["ok"])

    data = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "link_checks": link_checks,
        "validate_checks": validate_checks,
    }
    OUTPUT_FILE.write_text(json.dumps(data, indent=2))
    print(f"\nResults written to {OUTPUT_FILE}")

    print(f"\nLinks:    {link_ok}/{len(link_checks)} OK")
    if validate_checks:
        print(f"Functions:{val_ok}/{len(validate_checks)} OK")
    else:
        print("Functions: skipped (CrocoDash not available)")

    any_fail = link_ok < len(link_checks) or (
        validate_checks and val_ok < len(validate_checks)
    )
    if any_fail:
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--one"]:
        _validate_one(*sys.argv[2:4])
    main()
