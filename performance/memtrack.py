"""
Shared RSS memory-measurement helper for pytest-benchmark tests.

ESMF performs large C/Fortran heap allocations invisible to Python's
sys.getsizeof/tracemalloc, so memory is tracked via psutil RSS deltas instead.
"""

import os
import threading

import psutil

# Sampling period for measure_peak_rss's watcher thread. Small enough to catch a
# transient allocation peak inside a multi-second call, large enough to be free.
_PEAK_POLL_SECONDS = 0.05


def measure_rss(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), returning (result, rss_delta_mb)."""
    proc = psutil.Process(os.getpid())
    before = proc.memory_info().rss
    result = fn(*args, **kwargs)
    after = proc.memory_info().rss
    return result, (after - before) / 1024**2


def measure_peak_rss(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), returning (result, peak_rss_mb).

    peak_rss_mb is the *absolute* high-water RSS of the process observed during
    the call, sampled from a background thread — not a before/after delta.

    Prefer this over measure_rss() when a benchmark's parametrized cases run in
    one process and each allocates large arrays. A delta is meaningless there:
    once an earlier case has grown the heap, a later case reusing those pages
    reports a delta near zero or even negative, which reads as "used no memory"
    when the real footprint was gigabytes. The absolute peak answers the question
    that actually matters for large meshes — whether the call fits in memory.

    The trade-off is that the peak includes whatever the process was already
    holding, so it is an upper bound on the call's own footprint rather than an
    attribution of it.
    """
    proc = psutil.Process(os.getpid())
    peak = proc.memory_info().rss
    done = threading.Event()

    def watch():
        nonlocal peak
        while not done.wait(_PEAK_POLL_SECONDS):
            try:
                peak = max(peak, proc.memory_info().rss)
            except psutil.Error:  # process introspection can race at teardown
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        result = fn(*args, **kwargs)
        peak = max(peak, proc.memory_info().rss)
    finally:
        done.set()
        watcher.join(timeout=1.0)
    return result, peak / 1024**2


class PeakRSS:
    """Tracks the largest RSS delta seen across repeated calls to .measure(fn).

    pytest-benchmark calls the timed function many times in the same process
    (unlike ASV's fresh-subprocess-per-benchmark model) — after the first call,
    the allocator often reuses already-freed pages, so later calls under-report
    memory use. Tracking the peak instead of the last call captures the real
    footprint regardless of call order.
    """

    def __init__(self):
        self.peak_mb = None

    def measure(self, fn, *args, **kwargs):
        result, delta = measure_rss(fn, *args, **kwargs)
        self.peak_mb = delta if self.peak_mb is None else max(self.peak_mb, delta)
        return result
