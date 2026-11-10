#!/usr/bin/env python3
"""Build the CrocoDashChecks site: a page saying where each check stands, and one
of performance measurements with their fits.

Reads, each optional (a missing one renders as "no results yet"):
  cesm_runs/cesm_runs.json       weekly CESM runs (publish.yml fetches it from the
                                 test-results branch)
  data_access/health.json        daily data-access check
  performance/*.json             performance snapshots

Writes site/_build/: index.html (the checks), performance.html, the two README badges (badges/*.json, from the
same counts as the page's tiles), and copies of cesm_runs.json and health.json.
Every number on the page comes from those files.

    python site/build_site.py
"""

import json
import math
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "_build"
CESM_RUNS = ROOT / "cesm_runs" / "cesm_runs.json"
HEALTH = ROOT / "data_access" / "health.json"
PERF = ROOT / "performance"
REPO_URL = "https://github.com/CROCODILE-CESM/CrocoDashChecks"
MOUNTAIN_TZ = ZoneInfo("America/Denver")

# CIME's test phases, in order, and what each is for a CrocoDash-built case.
PHASES = [
    ("CREATE_NEWCASE", "crocodash create"),
    ("XML", "test options"),
    ("SETUP", "case.setup"),
    ("SHAREDLIB_BUILD", "shared libs build"),
    ("MODEL_BUILD", "model build"),
    ("SUBMIT", "case.submit"),
    ("RUN", "model run"),
]
# A check older than this means its schedule stopped running.
STALE_DAYS = {"cesm": 8, "health": 2}
# CESM's stub components, left out of the components column.
STUB_COMPONENTS = {
    "SATM",
    "SLND",
    "SICE",
    "SOCN",
    "SROF",
    "SGLC",
    "SWAV",
    "SESP",
    "SIAC",
}

# The dataviz reference palette's ink, surface and status roles. Status colors
# only ever mark state, always beside a text label.
CSS = """
  :root { color-scheme: light;
          --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
          --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7;
          --border: rgba(11,11,11,0.10); --accent: #2a78d6;
          --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
          --good: #0ca30c; --warning: #fab219; --critical: #d03b3b; }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; margin: 0;
         background: var(--page); color: var(--ink); }
  a { color: var(--accent); }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 0 16px; box-sizing: border-box; }
  header { background: var(--surface); border-bottom: 1px solid var(--grid); }
  header .wrap { padding-top: 1.25rem; padding-bottom: 1rem; }
  header h1 { margin: 0 0 0.2rem; font-size: 1.5rem; }
  header p { margin: 0; color: var(--ink-2); font-size: 0.95rem; max-width: 80ch; }
  footer { padding: 1.5rem 0 2rem; font-size: 0.8rem; color: var(--muted); }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1rem; margin-top: 1.25rem; }
  .tile, .panel { background: var(--surface); border: 1px solid var(--border);
                  border-radius: 8px; padding: 1rem 1.25rem; }
  .tile h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
             color: var(--ink-2); margin: 0 0 0.4rem; font-weight: 600; }
  .tile h2 a { color: inherit; text-decoration: none; }
  .value { font-size: 2.6rem; font-weight: 600; line-height: 1.1; }
  .unit { color: var(--ink-2); font-size: 0.9rem; margin-left: 0.3rem; }
  .chips { margin-top: 0.6rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .note { color: var(--ink-2); font-size: 0.8rem; margin: 0.6rem 0 0; }
  .chip { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.78rem;
          font-weight: 600; padding: 0.15rem 0.6rem; border-radius: 999px;
          border: 1px solid var(--border); background: var(--page); white-space: nowrap; }
  .chip::before { content: ""; width: 0.55rem; height: 0.55rem; border-radius: 50%;
                  background: var(--dot, var(--muted)); }
  .chip-good { --dot: var(--good); }
  .chip-warning { --dot: var(--warning); }
  .chip-critical { --dot: var(--critical); }
  .panel { margin-top: 1.25rem; overflow-x: auto; }
  .panel h2 { font-size: 1.05rem; margin: 0 0 0.25rem; }
  .panel h3 { font-size: 0.92rem; margin: 1.25rem 0 0.25rem; }
  .sub { color: var(--ink-2); font-size: 0.85rem; margin: 0 0 1rem; max-width: 80ch; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th, td { text-align: left; vertical-align: middle; padding: 0.45rem 0.6rem; }
  th { border-bottom: 1px solid var(--axis); color: var(--ink-2); font-weight: 600; }
  tr + tr td { border-top: 1px solid var(--grid); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.8rem; }
  .why { color: var(--ink-2); font-size: 0.75rem; margin-top: 0.15rem; overflow-wrap: anywhere; }
  .phases { display: inline-flex; gap: 2px; }
  .ph { display: inline-block; width: 16px; height: 12px; border-radius: 3px; background: var(--grid); }
  .ph-pass { background: var(--good); }
  .ph-fail { background: var(--critical); }
  .legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; color: var(--ink-2);
            font-size: 0.78rem; margin: 0.8rem 0 0; align-items: center; }
  .legend .ph { margin-right: 0.3rem; vertical-align: -1px; }
  .meter { display: flex; gap: 2px; height: 8px; margin: 0.2rem 0 1rem; }
  .meter span { border-radius: 4px; }
  .m-ok { background: var(--good); }
  .m-bad { background: var(--critical); }
  .how { list-style: none; margin: 0; padding: 0; font-size: 0.85rem; }
  .how li { padding: 0.6rem 0; }
  .how li + li { border-top: 1px solid var(--grid); }
  .how b { display: block; margin-bottom: 0.15rem; }
  .how span { color: var(--ink-2); }
  .charts { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr));
            gap: 1.25rem 2rem; margin: 1rem 0 0.5rem; }
  .chart { margin: 0; min-width: 0; }
  .chart h4 { font-size: 0.9rem; margin: 0; font-weight: 600; }
  .take { font-size: 0.8rem; color: var(--ink); margin: 0.1rem 0 0.3rem; }
  details { margin-top: 0.75rem; }
  summary { cursor: pointer; color: var(--ink-2); font-size: 0.85rem; }
  .key { display: flex; flex-wrap: wrap; gap: 0.15rem 0.9rem; font-size: 0.75rem;
         color: var(--ink-2); margin: 0 0 0.25rem; }
  .key i { display: inline-block; vertical-align: middle; margin-right: 0.3rem; background: var(--c); }
  .k-line { width: 14px; height: 2px; border-radius: 1px; }
  .k-dot { width: 8px; height: 8px; border-radius: 50%; }
  .k-line + .k-dot { margin-left: -0.75rem; margin-right: 0.55rem; }
  .chart svg { width: 100%; height: auto; display: block; overflow: visible; }
  .chart text { font-size: 11px; fill: var(--muted); font-variant-numeric: tabular-nums; }
  .chart text.ttl { fill: var(--ink-2); }
  .gl { stroke: var(--grid); stroke-width: 1; }
  .ax, .ref { stroke: var(--axis); stroke-width: 1; }
  .fit { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .dot { stroke: var(--surface); stroke-width: 2; }
  .hit { fill: transparent; }
  .pt { outline: none; }
  .pt:hover .dot, .pt:focus .dot { r: 6; }
  .pt:focus-visible .dot { stroke: var(--ink); }
  #tip { position: fixed; display: none; pointer-events: none; z-index: 10; max-width: 280px;
         background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
         padding: 0.4rem 0.6rem; font-size: 0.78rem; box-shadow: 0 2px 10px rgba(11,11,11,0.08); }
  #tip b { display: block; font-size: 0.9rem; color: var(--ink); }
  #tip b i { display: inline-block; width: 12px; height: 2px; border-radius: 1px;
             vertical-align: middle; margin-right: 0.4rem; }
  #tip span { display: block; color: var(--ink-2); }
  @media (max-width: 640px) { .wide-only { display: none; } .ph { width: 9px; }
                              .chart text { font-size: 15px; }
                              th, td { padding: 0.4rem 0.3rem; } }
"""


def load(path):
    return json.loads(path.read_text()) if path.exists() else None


def parse_time(iso):
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def when(iso):
    """A results file's timestamp, in Mountain Time like the schedules."""
    return parse_time(iso).astimezone(MOUNTAIN_TZ).strftime("%a %b %-d, %H:%M %Z")


def age_days(iso):
    return (datetime.now(timezone.utc) - parse_time(iso)).days


def chip(state, text):
    """A state marker: a status-colored dot beside its label, never color alone."""
    return f'<span class="chip chip-{state}">{escape(text)}</span>'


def stale_chip(iso, kind):
    days = age_days(iso)
    return chip("warning", f"Stale: {days} days old") if days > STALE_DAYS[kind] else ""


def tile(title, href, value, unit, chips, note):
    return (
        f'<div class="tile"><h2><a href="{href}">{title}</a></h2>'
        f'<div><span class="value">{value}</span><span class="unit">{unit}</span></div>'
        f'<div class="chips">{chips}</div><p class="note">{note}</p></div>'
    )


def fmt_s(s):
    return f"{s:.1f} s" if s < 60 else f"{s / 60:.1f} min"


def fmt_mb(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


# --- weekly CESM runs ------------------------------------------------------


def cesm_status(runs):
    return sum(t["passed"] for t in runs["tests"]), len(runs["tests"])


def cesm_tile(runs):
    if not runs:
        return tile(
            "Weekly CESM runs",
            "#cesm",
            "&ndash;",
            "",
            chip("warning", "No results yet"),
            "",
        )
    passed, total = cesm_status(runs)
    state = (
        chip("good", "All passing")
        if passed == total
        else chip("critical", f"{total - passed} failing")
    )
    return tile(
        "Weekly CESM runs",
        "#cesm",
        f"{passed}/{total}",
        "tests passing",
        state + stale_chip(runs["date"], "cesm"),
        f"Last run {when(runs['date'])}",
    )


def components(longname):
    """The active components of a compset long name, e.g. MOM6 (MARBL-BIO)."""
    out = []
    for token in longname.split("_")[1:]:
        name, *mods = token.split("%")
        if name in STUB_COMPONENTS:
            continue
        mods = [m for m in mods if m != "REGIONAL"]
        out.append(f"{name} ({', '.join(mods)})" if mods else name)
    return " &middot; ".join(escape(c) for c in out)


def commit_link(ref, repo):
    if not ref:
        return "unknown"
    url = f"https://github.com/CROCODILE-CESM/{repo}/commit/{ref['commit']}"
    return f'<span class="mono">{escape(ref["branch"])}</span> at <a class="mono" href="{url}">{escape(ref["commit"])}</a>'


def phase_strip(phases):
    status = dict(phases)
    cells = "".join(
        f'<span class="ph {({"PASS": "ph-pass", "FAIL": "ph-fail"}).get(status.get(p), "")}" '
        f'title="{label}: {status.get(p) or "not reached"}"></span>'
        for p, label in PHASES
    )
    return f'<span class="phases" role="img" aria-label="phases">{cells}</span>'


def result_chip(test):
    if test["passed"]:
        return chip("good", "Pass")
    status = dict(test["phases"])
    failed = next((label for p, label in PHASES if status.get(p) == "FAIL"), None)
    return (
        chip("critical", f"Failed: {failed}")
        if failed
        else chip("warning", "Incomplete")
    )


def cesm_section(runs):
    head = (
        "<div class='panel' id='cesm'><h2>Weekly CESM runs on Derecho</h2>"
        "<p class='sub'>Every Monday, each regional SMS test in MOM_interface's "
        "<span class='mono'>testlist_mom.xml</span> is built with CrocoDash on our test domain and "
        f"run in CESM on a Derecho node (<a href='{REPO_URL}/tree/main/cesm_runs'>cesm_runs/</a>).</p>"
    )
    if not runs:
        return head + "<p>No results yet.</p></div>"
    rows = "".join(
        f"<tr><td class='mono'>{escape(t['compset'])}</td><td class='mono wide-only'>{escape(t['test'])}</td>"
        f"<td class='wide-only'>{components(t['longname'])}</td><td>{phase_strip(t['phases'])}</td>"
        f"<td>{result_chip(t)}</td></tr>"
        for t in sorted(runs["tests"], key=lambda t: (t["passed"], t["compset"]))
    )
    order = " &rarr; ".join(label for _, label in PHASES)
    return (
        head + "<table><thead><tr><th>Compset</th><th class='wide-only'>Test</th>"
        "<th class='wide-only'>Components</th><th>Phases</th><th>Result</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<p class='legend'><span><span class='ph ph-pass'></span>passed</span>"
        "<span><span class='ph ph-fail'></span>failed</span><span><span class='ph'></span>not reached</span>"
        f"<span>Phases, left to right: {order}</span></p>"
        f"<p class='note'>Run {when(runs['date'])} with CESM {commit_link(runs.get('cesm'), 'CESM')} "
        f"and CrocoDash {commit_link(runs.get('crocodash'), 'CrocoDash')}.</p></div>"
    )


# --- daily data access ----------------------------------------------------


def health_status(health):
    checks = health["validate_checks"]
    return sum(1 for c in checks if c["ok"]), len(checks)


def health_tile(health):
    if not health:
        return tile(
            "Data access",
            "#data-access",
            "&ndash;",
            "",
            chip("warning", "No results yet"),
            "",
        )
    ok, total = health_status(health)
    if ok == total:
        state = chip("good", "All OK")
    else:
        state = chip(
            "warning" if ok >= 0.8 * total else "critical", f"{total - ok} failing"
        )
    return tile(
        "Data access",
        "#data-access",
        f"{ok}/{total}",
        "access methods OK",
        state + stale_chip(health["date"], "health"),
        f"Checked {when(health['date'])}",
    )


def health_section(health):
    head = (
        "<div class='panel' id='data-access'><h2>Data access, daily on GLADE</h2>"
        "<p class='sub'>Every day, each way CrocoDash can fetch data "
        "(<span class='mono'>ProductRegistry.validate_function</span>) is called for real on Casper, "
        "with GLADE and our credentials.</p>"
    )
    if not health:
        return head + "<p>No results yet.</p></div>"
    checks = health["validate_checks"]
    ok, total = health_status(health)
    meter = "".join(
        f'<span class="{css}" style="flex:{n}"></span>'
        for css, n in (("m-ok", ok), ("m-bad", total - ok))
        if n
    )
    rows = "".join(
        f"<tr><td>{escape(r['product'])}</td><td><span class='mono'>{escape(r['method'])}</span>"
        + (f"<div class='why'>{escape(r['detail'])}</div>" if r.get("detail") else "")
        + f"</td><td>{chip('good', 'OK') if r['ok'] else chip('critical', 'Failing')}</td>"
        f"<td class='num'>{fmt_s(r['elapsed_s'])}</td></tr>"
        for r in sorted(checks, key=lambda r: (r["ok"], r["product"], r["method"]))
    )
    return (
        head + f"<p class='note'>{ok} of {total} access methods working</p>"
        f'<div class="meter" role="img" aria-label="{ok} of {total} OK">{meter}</div>'
        "<table><thead><tr><th>Product</th><th>Access method</th><th>Status</th>"
        f"<th class='num'>Time</th></tr></thead><tbody>{rows}</tbody></table>"
        "<p class='note'>Raw results: <a href='health.json'>health.json</a></p></div>"
    )


# --- performance ------------------------------------------------------------


def bench_rows(snapshot, test):
    return [
        b
        for b in (snapshot or {}).get("benchmarks", [])
        if b["name"].startswith(test + "[")
    ]


def table(headers, rows):
    head = "".join(f"<th{' class=num' if num else ''}>{h}</th>" for h, num in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td{' class=num' if num else ''}>{v}</td>"
            for v, (_, num) in zip(r, headers)
        )
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def lstsq(rows, ys):
    """Least-squares coefficients for ys ~ rows (one list of terms per row),
    from the normal equations: the fits here have a handful of terms."""
    n = len(rows[0])
    a = [
        [sum(r[i] * r[j] for r in rows) for j in range(n)]
        + [sum(r[i] * y for r, y in zip(rows, ys))]
        for i in range(n)
    ]
    for c in range(n):
        pivot = max(range(c, n), key=lambda r: abs(a[r][c]))
        a[c], a[pivot] = a[pivot], a[c]
        for r in range(n):
            if r != c:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [a[i][n] / a[i][i] for i in range(n)]


def fit_error(predicted, measured):
    errors = sorted(abs(p - y) / y for p, y in zip(predicted, measured))
    return f"median {errors[len(errors) // 2]:.0%}, worst {errors[-1]:.0%}"


def logspace(lo, hi, n=40):
    return [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]


# ---- Charts: inline SVG. Dots are measurements, 2px lines are fits; series
# take the dataviz reference palette's first three categorical slots (validated
# all-pairs). Every dot is a focusable hover target; the tables below each set
# of charts hold the same numbers.
SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"]
CW, CH = 440, 250
PAD_L, PAD_R, PAD_T, PAD_B = 46, 14, 26, 40


def axis(values, log, ticks=None):
    """(lo, hi, ticks): whole decades on a log axis, clean steps from zero on a
    linear one."""
    if ticks:
        return ticks[0], ticks[-1], ticks
    if log:
        lo = 10 ** math.floor(math.log10(min(values)))
        hi = 10 ** math.ceil(math.log10(max(values)))
        hi = hi * 10 if hi == lo else hi
        return lo, hi, [lo * 10**i for i in range(round(math.log10(hi / lo)) + 1)]
    raw = max(values) / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    hi = step * math.ceil(max(values) / step - 1e-9)
    return 0, hi, [i * step for i in range(round(hi / step) + 1)]


def tick_label(v, compact):
    if compact:
        for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if v >= div:
                return f"{v / div:g}{unit}"
    return f"{v:,g}"


def chart(
    title, xlab, ylab, series, xlog=False, ylog=False, xticks=None, ref=False, note=""
):
    """series: [{name, points: [(x, y, value, [detail, ...])], fit: [(x, y)]}].
    ref draws fit = measured on a log-log square scale."""
    xy = [(p[0], p[1]) for s in series for p in s["points"]]
    xy += [p for s in series for p in s.get("fit", [])]
    xlo, xhi, xt = axis([x for x, _ in xy], xlog, xticks)
    ylo, yhi, yt = axis([y for _, y in xy], ylog)
    if ref:
        xlo, xhi, xt = ylo, yhi, yt = axis([v for p in xy for v in p], True)
    pw, ph = CW - PAD_L - PAD_R, CH - PAD_T - PAD_B

    def frac(v, lo, hi, log):
        return math.log10(v / lo) / math.log10(hi / lo) if log else (v - lo) / (hi - lo)

    def sx(x):
        return PAD_L + frac(x, xlo, xhi, xlog or ref) * pw

    def sy(y):
        return PAD_T + ph - frac(y, ylo, yhi, ylog or ref) * ph

    svg = [f"<text class='ttl' x='0' y='12'>{ylab}</text>"]
    for v in yt:
        svg.append(
            f"<line class='gl' x1='{PAD_L}' x2='{PAD_L + pw}' y1='{sy(v):.1f}' y2='{sy(v):.1f}'/>"
            f"<text x='{PAD_L - 6}' y='{sy(v) + 4:.1f}' text-anchor='end'>"
            f"{tick_label(v, yt[-1] >= 1e4)}</text>"
        )
    svg.append(
        f"<line class='ax' x1='{PAD_L}' x2='{PAD_L + pw}' y1='{PAD_T + ph}' y2='{PAD_T + ph}'/>"
    )
    for v in xt:
        svg.append(
            f"<text x='{sx(v):.1f}' y='{PAD_T + ph + 16}' text-anchor='middle'>"
            f"{tick_label(v, xt[-1] >= 1e4)}</text>"
        )
    svg.append(
        f"<text class='ttl' x='{PAD_L + pw / 2}' y='{CH - 4}' text-anchor='middle'>{xlab}</text>"
    )
    if ref:
        svg.append(
            f"<line class='ref' x1='{sx(xlo):.1f}' y1='{sy(ylo):.1f}' x2='{sx(xhi):.1f}' y2='{sy(yhi):.1f}'/>"
        )
    for s, color in zip(series, SERIES):
        if s.get("fit"):
            d = " ".join(
                f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}"
                for i, (x, y) in enumerate(s["fit"])
            )
            svg.append(f"<path class='fit' d='{d}' style='stroke:{color}'/>")
    for s, color in zip(series, SERIES):
        for x, y, value, detail in s["points"]:
            svg.append(
                f"<g class='pt' tabindex='0' data-c='{color}' data-v='{escape(value)}' "
                f"data-l='{escape('|'.join([s['name']] + detail if s['name'] else detail))}'>"
                f"<circle class='hit' cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='12'/>"
                f"<circle class='dot' cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='4.5' style='fill:{color}'/></g>"
            )
    if ref:
        key = (
            f"<span><i class='k-dot' style='--c:{SERIES[0]}'></i>a case</span>"
            "<span><i class='k-line' style='--c:var(--axis)'></i>fit = measured</span>"
        )
    elif len(series) == 1:
        key = (
            f"<span><i class='k-dot' style='--c:{SERIES[0]}'></i>measured</span>"
            f"<span><i class='k-line' style='--c:{SERIES[0]}'></i>fit</span>"
        )
    else:
        key = (
            "".join(
                f"<span><i class='k-line' style='--c:{c}'></i><i class='k-dot' style='--c:{c}'></i>"
                f"{s['name']}</span>"
                for s, c in zip(series, SERIES)
            )
            + "<span>dots measured, lines fit</span>"
        )
    return (
        f"<figure class='chart'><h4>{title}</h4><p class='take'>{note}</p>"
        f"<div class='key'>{key}</div>"
        f"<svg viewBox='0 0 {CW} {CH}' role='img' aria-label='{escape(title)}'>"
        + "".join(svg)
        + "</svg></figure>"
    )


TOOLTIP_JS = """
const tip = document.getElementById("tip");
function show(g) {
  tip.replaceChildren();
  const v = document.createElement("b"), key = document.createElement("i");
  key.style.background = g.dataset.c;
  v.append(key, document.createTextNode(g.dataset.v));
  tip.append(v);
  for (const line of g.dataset.l.split("|")) {
    const s = document.createElement("span");
    s.textContent = line;
    tip.append(s);
  }
  tip.style.display = "block";
  const r = g.getBoundingClientRect(), t = tip.getBoundingClientRect();
  let x = r.right + 6;
  if (x + t.width > innerWidth - 8) x = r.left - t.width - 6;
  const y = Math.min(Math.max(8, r.top + r.height / 2 - t.height / 2), innerHeight - t.height - 8);
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = y + "px";
}
const hide = () => { tip.style.display = "none"; };
for (const g of document.querySelectorAll(".pt")) {
  g.addEventListener("pointerenter", () => show(g));
  g.addEventListener("focus", () => show(g));
  g.addEventListener("pointerleave", hide);
  g.addEventListener("blur", hide);
}
"""


# The open-boundary cost model (see performance/test_obc.py). REGRID gives each
# of min(workers, slices) forked workers an equal run of 30-day slices, so the
# terms are per run, per slice (serial) and per slice a worker does (parallel).
# One worker runs in-process, so it adds no worker memory.
def obc_terms(e):
    per_worker = math.ceil(e["slices"] / e["workers"])
    src, cells = e["n_src"] / 1e6, e["n_cells"] / 1e6
    pool = min(e["workers"], e["slices"]) if e["workers"] > 1 else 0
    time = [1, e["slices"], e["slices"] * cells, per_worker]
    time += [per_worker * src, per_worker * cells]
    memory = [1, src, cells, pool, pool * cells]
    return time, memory


def linspace(lo, hi, n=2):
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def tables(parts):
    """The charts' numbers, folded away under them."""
    return f"<details><summary>Tables</summary>{''.join(parts)}</details>"


def formula(lines, legend):
    return f"<p class='mono'>{'<br>'.join(lines)}</p><p class='sub'>{legend}</p>"


def obc_section(benchmarks):
    terms = [obc_terms(b["extra_info"]) for b in benchmarks]
    times = [b["stats"]["mean"] for b in benchmarks]
    mems = [b["extra_info"]["peak_mb"] / 1024 for b in benchmarks]
    t = lstsq([tt for tt, _ in terms], times)
    m = lstsq([mm for _, mm in terms], mems)

    def fit(e):
        """(seconds, GB) the fit gives for a case."""
        tt, mm = obc_terms(e)
        return sum(c * x for c, x in zip(t, tt)), sum(c * x for c, x in zip(m, mm))

    def case(e):
        return [
            f"{e['size_deg']:g}° box, {e['source_res_deg']:g}° source, {e['days']} days, "
            f"{e['workers']} worker{'s' if e['workers'] > 1 else ''}",
            f"{e['n_src']:,} source points, {e['n_cells']:,} domain cells",
        ]

    def time_pt(x, b):
        e = b["extra_info"]
        y = b["stats"]["mean"]
        return (x, y, fmt_s(y), case(e) + [f"fit {fmt_s(fit(e)[0])}"])

    def mem_pt(x, b):
        e = b["extra_info"]
        return (
            x,
            e["peak_mb"] / 1024,
            fmt_mb(e["peak_mb"]),
            case(e) + [f"fit {fmt_mb(fit(e)[1] * 1024)}"],
        )

    def one(points, fit_line):
        return [{"name": "", "points": points, "fit": fit_line}]

    def ei(b, k):
        return b["extra_info"][k]

    sweep = {
        test: sorted(
            bench_rows({"benchmarks": benchmarks}, test),
            key=lambda b: (
                ei(b, "n_src"),
                ei(b, "n_cells"),
                ei(b, "days"),
                ei(b, "workers"),
            ),
        )
        for test in (
            "test_by_source_resolution",
            "test_by_domain_size",
            "test_by_days",
            "test_by_workers",
        )
    }
    charts = []
    rows = sweep["test_by_source_resolution"]
    if rows:
        e0 = rows[0]["extra_info"]
        charts.append(
            chart(
                "Time by source points",
                "Source points",
                "Time (s)",
                one(
                    [time_pt(ei(b, "n_src"), b) for b in rows],
                    [
                        (p, fit({**e0, "n_src": p})[0])
                        for p in linspace(0, ei(rows[-1], "n_src"))
                    ],
                ),
                note=f"Linear: {t[4]:.0f} s more per million source points per 30 days. "
                "10&deg; box, 1 worker.",
            )
        )
    rows = sweep["test_by_domain_size"]
    if rows:
        charts.append(
            chart(
                "Time by domain size",
                "Domain cells",
                "Time (s)",
                one(
                    [time_pt(ei(b, "n_cells"), b) for b in rows],
                    [(ei(b, "n_cells"), fit(b["extra_info"])[0]) for b in rows],
                ),
                note=f"Linear too: {t[2] + t[5]:.0f} s more per million domain cells per 30 days. "
                "0.25&deg; source, 1 worker.",
            )
        )
    rows = sweep["test_by_days"]
    if rows:
        e0 = rows[0]["extra_info"]
        per_slice = fit({**e0, "days": 60, "slices": 2})[0] - fit(e0)[0]
        charts.append(
            chart(
                "Time by days",
                "Days",
                "Time (s)",
                one(
                    [time_pt(ei(b, "days"), b) for b in rows],
                    [(ei(b, "days"), fit(b["extra_info"])[0]) for b in rows],
                ),
                xticks=[0, 90, 180, 270, 360],
                note=f"Linear: {per_slice:.1f} s per 30 days. 10&deg; box, 1 worker.",
            )
        )
    rows = sweep["test_by_workers"]
    if rows:
        configs = sorted(
            {(ei(b, "size_deg"), ei(b, "source_res_deg")) for b in rows},
            key=lambda c: (c[0], -c[1]),
        )
        own = {
            c: sorted(
                (b for b in rows if (ei(b, "size_deg"), ei(b, "source_res_deg")) == c),
                key=lambda b: ei(b, "workers"),
            )
            for c in configs
        }

        def by_workers(point, value):
            return [
                {
                    "name": f"{size:g}&deg; box, {src:g}&deg; source",
                    "points": [point(ei(b, "workers"), b) for b in own[(size, src)]],
                    "fit": [
                        (
                            w,
                            value(
                                fit({**own[(size, src)][0]["extra_info"], "workers": w})
                            ),
                        )
                        for w in range(1, ei(own[(size, src)][-1], "workers") + 1)
                    ],
                }
                for size, src in configs
            ]

        speedups = [
            own[c][0]["stats"]["mean"] / own[c][-1]["stats"]["mean"] for c in configs
        ]
        charts.append(
            chart(
                "Time by workers",
                "Workers",
                "Time (s)",
                by_workers(time_pt, lambda f: f[0]),
                xticks=[0, 2, 4, 6, 8, 10, 12],
                note=f"Falls as 1/workers toward a floor: {min(speedups):.1f}&ndash;"
                f"{max(speedups):.1f}&times; faster at {ei(rows[-1], 'workers')}. "
                "Flat from 6 to 11, so use a count that divides the 12 slices.",
            )
        )
        charts.append(
            chart(
                "Peak memory by workers",
                "Workers",
                "Peak memory (GB)",
                by_workers(mem_pt, lambda f: f[1]),
                xticks=[0, 2, 4, 6, 8, 10, 12],
                note=f"Linear: {m[3]:.2f} GB per worker, plus {m[4]:.2f} GB per worker per "
                "million domain cells.",
            )
        )
    rows = sweep["test_by_domain_size"]
    if rows:
        charts.append(
            chart(
                "Peak memory by domain size",
                "Domain cells",
                "Peak memory (GB)",
                one(
                    [mem_pt(ei(b, "n_cells"), b) for b in rows],
                    [(ei(b, "n_cells"), fit(b["extra_info"])[1]) for b in rows],
                ),
                note=f"Linear: {m[2]:.1f} GB per million domain cells. 1 worker.",
            )
        )
    predicted = [fit(b["extra_info"]) for b in benchmarks]
    for i, what, unit, pt in (
        (0, "time", "s", time_pt),
        (1, "peak memory", "GB", mem_pt),
    ):
        charts.append(
            chart(
                f"Fit against measurement: {what}",
                f"Fit ({unit}, log scale)",
                f"Measured ({unit})",
                [
                    {
                        "name": "",
                        "points": [
                            (p[i],) + pt(0, b)[1:]
                            for p, b in zip(predicted, benchmarks)
                        ],
                    }
                ],
                ref=True,
                note=f"All {len(benchmarks)} cases: "
                + fit_error([p[i] for p in predicted], times if i == 0 else mems),
            )
        )

    table_parts = []
    for test, title, axis_name, label in (
        (
            "test_by_source_resolution",
            "By source resolution",
            "Source",
            lambda e: f"{e['source_res_deg']:g}&deg;",
        ),
        (
            "test_by_domain_size",
            "By domain size",
            "Domain",
            lambda e: f"{e['size_deg']:g}&deg; square",
        ),
        ("test_by_days", "By days", "Days", lambda e: e["days"]),
        (
            "test_by_workers",
            "By workers (360 days)",
            "Box, source, workers",
            lambda e: f"{e['size_deg']:g}&deg;, {e['source_res_deg']:g}&deg;, {e['workers']}",
        ),
    ):
        if sweep[test]:
            table_parts.append(
                f"<h3>{title}</h3>"
                + table(
                    [
                        (axis_name, 0),
                        ("Source points", 1),
                        ("Domain cells", 1),
                        ("Time", 1),
                        ("Fit", 1),
                        ("Peak memory", 1),
                        ("Fit", 1),
                    ],
                    [
                        (
                            label(b["extra_info"]),
                            f"{ei(b, 'n_src'):,}",
                            f"{ei(b, 'n_cells'):,}",
                            fmt_s(b["stats"]["mean"]),
                            fmt_s(fit(b["extra_info"])[0]),
                            fmt_mb(ei(b, "peak_mb")),
                            fmt_mb(fit(b["extra_info"])[1] * 1024),
                        )
                        for b in sweep[test]
                    ],
                )
            )
    return (
        "<div class='panel' id='obc'><h2>Open boundaries</h2>"
        + formula(
            [
                f"time (s) &asymp; {t[0]:.2g} + S&times;({t[1]:.2g} + {t[2]:.2g}&middot;C) + "
                f"k&times;({t[3]:.2g} + {t[4]:.2g}&middot;P + {t[5]:.2g}&middot;C)",
                f"memory (GB) &asymp; {m[0]:.2g} + {m[1]:.2g}&middot;P + {m[2]:.2g}&middot;C + "
                f"w&times;({m[3]:.2g} + {m[4]:.2g}&middot;C)",
            ],
            "S 30-day slices, k slices per worker, w workers, P million source points, "
            "C million domain cells. REGRID + MERGE on synthetic data "
            f"(<a href='{REPO_URL}/blob/main/performance/test_obc.py'>test_obc.py</a>).",
        )
        + f"<div class='charts'>{''.join(charts)}</div>"
        + tables(table_parts)
        + "</div>"
    )


def power_fit(xs, ys):
    """(a, p) for y = a x^p, fitted in log space."""
    c = lstsq([[1, math.log(x)] for x in xs], [math.log(y) for y in ys])
    return math.exp(c[0]), c[1]


def bathymetry_section(topo):
    rows = sorted(
        bench_rows(topo, "test_set_from_dataset"),
        key=lambda b: b["params"]["domain_deg"],
    )
    if not rows:
        return ""
    area = [b["params"]["domain_deg"] ** 2 for b in rows]
    times = [b["stats"]["mean"] for b in rows]
    mems = [b["extra_info"]["rss_mb"] / 1024 for b in rows]
    (ta, tp), (ma, mp) = power_fit(area, times), power_fit(area, mems)
    span = logspace(area[0], area[-1])

    def pt(a, b, y, value, fitted):
        return (
            a,
            y,
            value,
            [f"{b['params']['domain_deg']}° square at 0.1°", f"fit {fitted}"],
        )

    charts = [
        chart(
            "Time by domain area",
            "Square degrees (log scale)",
            "Time (s, log scale)",
            [
                {
                    "name": "",
                    "points": [
                        pt(
                            a,
                            b,
                            b["stats"]["mean"],
                            fmt_s(b["stats"]["mean"]),
                            fmt_s(ta * a**tp),
                        )
                        for a, b in zip(area, rows)
                    ],
                    "fit": [(a, ta * a**tp) for a in span],
                }
            ],
            xlog=True,
            ylog=True,
            note=f"Close to linear in area (A<sup>{tp:.2f}</sup>): "
            f"{fmt_s(ta * 1600**tp)} for a 40&deg; square.",
        ),
        chart(
            "Memory by domain area",
            "Square degrees (log scale)",
            "Memory added (GB, log scale)",
            [
                {
                    "name": "",
                    "points": [
                        pt(a, b, y, fmt_mb(y * 1024), fmt_mb(ma * a**mp * 1024))
                        for a, b, y in zip(area, rows, mems)
                    ],
                    "fit": [(a, ma * a**mp) for a in span],
                }
            ],
            xlog=True,
            ylog=True,
            note=f"A bit faster than area (A<sup>{mp:.2f}</sup>): "
            f"{fmt_mb(ma * 1600**mp * 1024)} for a 40&deg; square.",
        ),
    ]
    return (
        "<div class='panel' id='bathymetry'><h2>Bathymetry</h2>"
        + formula(
            [
                f"time (s) &asymp; {ta:.2g}&middot;A<sup>{tp:.2f}</sup>",
                f"memory added (GB) &asymp; {ma:.2g}&middot;A<sup>{mp:.2f}</sup>",
            ],
            f"A square degrees. GEBCO to a 0.1&deg; grid (mom6_forge "
            f"<span class='mono'>Topo.set_from_dataset</span>); {len(rows)} cases: time "
            f"{fit_error([ta * a**tp for a in area], times)}, memory "
            f"{fit_error([ma * a**mp for a in area], mems)}.",
        )
        + f"<div class='charts'>{''.join(charts)}</div>"
        + tables(
            [
                table(
                    [
                        ("Domain", 0),
                        ("Time", 1),
                        ("Fit", 1),
                        ("Memory added", 1),
                        ("Fit", 1),
                    ],
                    [
                        (
                            f"{b['params']['domain_deg']}&deg; square",
                            fmt_s(b["stats"]["mean"]),
                            fmt_s(ta * a**tp),
                            fmt_mb(b["extra_info"]["rss_mb"]),
                            fmt_mb(ma * a**mp * 1024),
                        )
                        for a, b in zip(area, rows)
                    ],
                )
            ]
        )
        + "</div>"
    )


# What CESM's coupler holds for the smoothed runoff map: two route handles (liquid
# and ice) of ~167 bytes a weight, measured on CrocIndoPacific_DROF_112 (4.0e8
# weights, 133 GB on the mediator node).
COUPLER_BYTES_PER_WEIGHT = 2 * 167


def runoff_section(rof):
    """gen_rof_maps cost, fitted over every case (see performance/test_mapping.py):
    the smoothed map's weight count n_s from geometry, then time and memory from
    ocean cells and n_s."""
    sets = [
        (
            "test_gen_rof_maps_domain",
            "By domain, rmax 20 km",
            lambda e: e["domain"].replace("_", " "),
        ),
        (
            "test_gen_rof_maps_resolution",
            "By resolution, Gulf of Mexico, rmax 20 km",
            lambda e: f"{e['resolution_deg']:.3g}°",
        ),
        (
            "test_gen_rof_maps_rmax",
            "By rmax, 1/12°",
            lambda e: f"{e['domain'].replace('_', ' ')}, rmax {e['rmax_km']} km",
        ),
    ]
    rows = {
        test: sorted(
            bench_rows(rof, test),
            key=lambda b: (b["extra_info"]["n_ocn"], b["extra_info"]["rmax_km"]),
        )
        for test, *_ in sets
    }
    allrows = [b for r in rows.values() for b in r]
    if not allrows or "ocn_cell_km2" not in allrows[0]["extra_info"]:
        return ""

    def e(b):
        return b["extra_info"]

    def spread(x):  # pi rmax^2 / a: ocean cells within rmax of a coastal cell
        return math.pi * x["rmax_km"] ** 2 / x["ocn_cell_km2"]

    # n_s / N - 1 = k * spread, through the origin. An rmax narrower than a cell
    # spreads nowhere (n_s = N), so those cases stay out of the fit.
    wide = [b for b in allrows if e(b)["rmax_km"] ** 2 > e(b)["ocn_cell_km2"]]
    (k,) = lstsq(
        [[spread(e(b))] for b in wide],
        [e(b)["nnsm_n_s"] / e(b)["nn_n_s"] - 1 for b in wide],
    )

    def fw(x, rmax=None):
        r = x["rmax_km"] if rmax is None else rmax
        return x["nn_n_s"] * (1 + k * math.pi * r**2 / x["ocn_cell_km2"])

    def cw(b):  # (million ocean cells, billion weights)
        return e(b)["n_ocn"] / 1e6, e(b)["nnsm_n_s"] / 1e9

    times = [b["stats"]["mean"] for b in allrows]
    mems = [e(b)["peak_rss_mb"] / 1024 for b in allrows]
    t = lstsq([[1, *cw(b)] for b in allrows], times)
    m = lstsq([[1, cw(b)[1]] for b in allrows], mems)

    def ft(b):
        c, w = cw(b)
        return t[0] + t[1] * c + t[2] * w

    def fm(b):
        return m[0] + m[1] * cw(b)[1]

    # Weights against rmax, one exponent shared by the domains.
    domains = list(
        dict.fromkeys(e(b)["domain"] for b in rows["test_gen_rof_maps_rmax"])
    )
    rmax_rows = rows["test_gen_rof_maps_rmax"]
    if rmax_rows:
        *_, p = lstsq(
            [
                [float(e(b)["domain"] == d) for d in domains]
                + [math.log(e(b)["rmax_km"])]
                for b in rmax_rows
            ],
            [math.log(e(b)["nnsm_n_s"]) for b in rmax_rows],
        )

    def weights(n):
        return f"{n / 1e9:.2f} billion" if n >= 1e8 else f"{n / 1e6:.1f} million"

    def coupler_gb(n):
        return n * COUPLER_BYTES_PER_WEIGHT / 1024**3

    charts = [
        chart(
            "Time by ocean cells",
            "Ocean cells (log scale)",
            "Time (s)",
            [
                {
                    "name": name,
                    "points": [
                        (
                            e(b)["n_ocn"],
                            b["stats"]["mean"],
                            fmt_s(b["stats"]["mean"]),
                            [
                                label(e(b)),
                                f"{e(b)['n_ocn']:,} ocean cells",
                                f"fit {fmt_s(ft(b))}",
                            ],
                        )
                        for b in rows[test]
                    ],
                    "fit": [(e(b)["n_ocn"], ft(b)) for b in rows[test]],
                }
                for test, name, label in sets[:2]
                if rows[test]
            ],
            xlog=True,
            note=f"Flat at {t[0]:.0f} s, set by the global GLOFAS mesh, then "
            f"{t[1]:.0f} s more per million ocean cells.",
        ),
    ]
    if rows["test_gen_rof_maps_rmax"]:
        r_span = logspace(
            min(e(b)["rmax_km"] for b in rows["test_gen_rof_maps_rmax"]),
            max(e(b)["rmax_km"] for b in rows["test_gen_rof_maps_rmax"]),
        )
        charts.append(
            chart(
                "Weights by rmax",
                "rmax (km, log scale)",
                "Smoothed-map weights (log scale)",
                [
                    {
                        "name": d.replace("_", " "),
                        "points": [
                            (
                                e(b)["rmax_km"],
                                e(b)["nnsm_n_s"],
                                weights(e(b)["nnsm_n_s"]),
                                [
                                    f"rmax {e(b)['rmax_km']} km",
                                    f"fit {weights(fw(e(b)))}",
                                    f"coupler ~{fmt_mb(coupler_gb(e(b)['nnsm_n_s']) * 1024)}",
                                ],
                            )
                            for b in pts
                        ],
                        "fit": [(r, fw(e(pts[0]), r)) for r in r_span],
                    }
                    for d in domains
                    for pts in [
                        [
                            b
                            for b in rows["test_gen_rof_maps_rmax"]
                            if e(b)["domain"] == d
                        ]
                    ]
                ],
                xlog=True,
                ylog=True,
                xticks=[10, 20, 40, 80],
                note=f"About rmax<sup>{p:.1f}</sup>: doubling rmax multiplies the "
                f"weights by {2**p:.1f}, and the coupler's memory with them.",
            )
        )
    n_all = [e(b)["nnsm_n_s"] for b in allrows]
    charts.append(
        chart(
            "Peak memory by weights",
            "Smoothed-map weights (log scale)",
            "Peak memory (GB)",
            [
                {
                    "name": "",
                    "points": [
                        (
                            w,
                            y,
                            fmt_mb(y * 1024),
                            [
                                label(e(b)),
                                f"{weights(e(b)['nnsm_n_s'])} weights",
                                f"fit {fmt_mb(fm(b) * 1024)}",
                            ],
                        )
                        for test, _, label in sets
                        for b in rows[test]
                        for w, y in [(e(b)["nnsm_n_s"], e(b)["peak_rss_mb"] / 1024)]
                    ],
                    "fit": [
                        (n, m[0] + m[1] * n / 1e9)
                        for n in logspace(min(n_all), max(n_all))
                    ],
                }
            ],
            xlog=True,
            note=f"Flat at {m[0]:.0f} GB, set by the global GLOFAS mesh, then "
            f"{m[1]:.0f} GB more per billion weights.",
        )
    )
    return (
        "<div class='panel' id='runoff'><h2>Runoff mapping</h2>"
        + formula(
            [
                f"time (s) &asymp; {t[0]:.3g} + {t[1]:.3g}&middot;C + {t[2]:.3g}&middot;W",
                f"memory (GB) &asymp; {m[0]:.3g} + {m[1]:.3g}&middot;W",
                f"weights &asymp; N&middot;(1 + {k:.2f}&middot;&pi;r<sup>2</sup>/a)",
                f"coupler (GB) &asymp; {coupler_gb(1e9):.0f}&middot;W",
            ],
            "C million ocean cells, W billion weights in the smoothed map, N GLOFAS cells "
            "in the domain's box (its area / 0.0025 deg&sup2;), r rmax (km), a ocean cell "
            "area (km&sup2;). GLOFAS to the ocean grid (mom6_forge "
            f"<span class='mono'>gen_rof_maps</span>, fold = rmax); {len(allrows)} cases: "
            f"time {fit_error([ft(b) for b in allrows], times)}, memory "
            f"{fit_error([fm(b) for b in allrows], mems)}, weights "
            f"{fit_error([fw(e(b)) for b in wide], [e(b)['nnsm_n_s'] for b in wide])} "
            "(rmax wider than a cell). The coupler line is CESM's two route handles, "
            f"{COUPLER_BYTES_PER_WEIGHT // 2} bytes a weight each, measured in a run.",
        )
        + f"<div class='charts'>{''.join(charts)}</div>"
        + tables(
            [
                f"<h3>{name}</h3>"
                + table(
                    [
                        ("Case", 0),
                        ("Ocean cells", 1),
                        ("Weights", 1),
                        ("Fit", 1),
                        ("Time", 1),
                        ("Fit", 1),
                        ("Peak memory", 1),
                        ("Fit", 1),
                        ("Coupler", 1),
                    ],
                    [
                        (
                            escape(label(e(b))),
                            f"{e(b)['n_ocn']:,}",
                            weights(e(b)["nnsm_n_s"]),
                            weights(fw(e(b))),
                            fmt_s(b["stats"]["mean"]),
                            fmt_s(ft(b)),
                            fmt_mb(e(b)["peak_rss_mb"]),
                            fmt_mb(fm(b) * 1024),
                            fmt_mb(coupler_gb(e(b)["nnsm_n_s"]) * 1024),
                        )
                        for b in rows[test]
                    ],
                )
                for test, name, label in sets
                if rows[test]
            ]
        )
        + "</div>"
    )


def mom6_section(scaling):
    groups = [
        ("Bahamas sweep", [scaling["reference_sweep"]]),
        ("Four domains", scaling["domains"]),
    ]
    pts = [(d, p) for _, runs in groups for d in runs for p in d["points"]]
    a, b = lstsq(
        [[1, 1 / p["ntasks_ocn"]] for _, p in pts],
        [p["tot_run_time_s"] for _, p in pts],
    )

    def fitted(n):
        return a + b / n

    ns = [p["ntasks_ocn"] for _, p in pts]
    series = [
        {
            "name": name,
            "points": [
                (
                    p["ntasks_ocn"],
                    p["tot_run_time_s"],
                    fmt_s(p["tot_run_time_s"]),
                    [
                        d["name"],
                        f"{p['ntasks_ocn']} tasks, "
                        f"{p['throughput_sim_years_per_day']:.1f} simulated years/day",
                        f"fit {fmt_s(fitted(p['ntasks_ocn']))}",
                    ],
                )
                for d in runs
                for p in d["points"]
            ],
        }
        for name, runs in groups
    ]
    series[0]["fit"] = [(n, fitted(n)) for n in logspace(min(ns), max(ns))]
    sweep = sorted(scaling["reference_sweep"]["points"], key=lambda p: p["ntasks_ocn"])
    first, last = sweep[0], sweep[-1]
    return (
        "<div class='panel' id='mom6-scaling'><h2>MOM6 speed vs. NTASKS_OCN</h2>"
        + formula(
            [f"run time (s) &asymp; {a:.3g} + {b:.4g} &divide; N"],
            "N NTASKS_OCN. A month on Derecho, 100&times;100&times;10 grids "
            f"(<a href='{REPO_URL}/blob/main/performance/mom6_scaling.json'>JSON</a>); "
            f"{len(pts)} runs: "
            f"{fit_error([fitted(p['ntasks_ocn']) for _, p in pts], [p['tot_run_time_s'] for _, p in pts])}.",
        )
        + "<div class='charts'>"
        + chart(
            "Run time by tasks",
            "NTASKS_OCN (log scale)",
            "Run time (s, log scale)",
            series,
            xlog=True,
            ylog=True,
            note=f"Falls as 1/N toward a {a:.0f} s floor: "
            f"{first['tot_run_time_s'] / last['tot_run_time_s']:.0f}&times; faster on "
            f"{last['ntasks_ocn']} tasks than on {first['ntasks_ocn']}.",
        )
        + "</div>"
        + tables(
            [
                table(
                    [
                        ("Domain", 0),
                        ("NTASKS_OCN", 1),
                        ("Simulated years/day", 1),
                        ("Run time", 1),
                        ("Fit", 1),
                    ],
                    [
                        (
                            escape(d["name"]),
                            p["ntasks_ocn"],
                            f"{p['throughput_sim_years_per_day']:.1f}",
                            fmt_s(p["tot_run_time_s"]),
                            fmt_s(fitted(p["ntasks_ocn"])),
                        )
                        for d, p in pts
                    ],
                )
            ]
        )
        + "</div>"
    )


def performance_body():
    topo, rof, scaling, obc = (
        load(PERF / f)
        for f in ("topo.json", "runoff_mapping.json", "mom6_scaling.json", "obc.json")
    )
    parts = []
    if obc and obc.get("benchmarks"):
        parts.append(obc_section(obc["benchmarks"]))
    parts.append(bathymetry_section(topo))
    parts.append(runoff_section(rof))
    if scaling:
        parts.append(mom6_section(scaling))
    return "".join(parts)


def performance_link():
    return (
        "<div class='panel' id='performance'><h2>Performance</h2>"
        "<p class='sub'>How long CrocoDash's expensive steps take and how much memory they "
        "need, with fits for sizing jobs: open boundaries, GEBCO bathymetry, GLOFAS runoff "
        "mapping, and MOM6's speed against its task count. "
        "<a href='performance.html'>Performance page</a></p></div>"
    )


def how_section():
    items = [
        (
            "Weekly CESM runs",
            "Mondays 02:00 MT: cron.hpc.ucar.edu runs <span class='mono'>cesm_runs/cron_submit.sh</span>, "
            "which submits a Derecho job; it pushes <span class='mono'>cesm_runs.json</span> to the "
            "<span class='mono'>test-results</span> branch.",
        ),
        (
            "Data access",
            "Daily 05:00 MT: cron.hpc.ucar.edu runs <span class='mono'>data_access/cron_submit.sh</span>, "
            "which submits a Casper job; it pushes <span class='mono'>data_access/health.json</span> to main, "
            "which rebuilds this page.",
        ),
        (
            "Performance",
            "By hand, with pytest (see <span class='mono'>performance/</span>); results on the "
            "<a href='performance.html'>performance page</a>.",
        ),
    ]
    rows = "".join(f"<li><b>{t}</b><span>{d}</span></li>" for t, d in items)
    return (
        f"<div class='panel'><h2>What runs when</h2><ul class='how'>{rows}</ul></div>"
    )


def badge(label, counts, word, iso, kind, warn_at):
    """A shields.io endpoint badge with the same counts, colors and staleness as the tile."""
    if counts is None:
        return {
            "schemaVersion": 1,
            "label": label,
            "message": "no results",
            "color": "lightgrey",
        }
    ok, total = counts
    message = f"{ok}/{total} {word}"
    color = (
        "brightgreen" if ok == total else "orange" if ok >= warn_at * total else "red"
    )
    if age_days(iso) > STALE_DAYS[kind]:
        message, color = f"{message}, stale", "yellow"
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def html_page(title, header, body, script=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
{script}</head>
<body>
<header><div class="wrap">{header}</div></header>
<main class="wrap">{body}</main>
<footer class="wrap">Built by site/build_site.py &middot; <a href="{REPO_URL}">CrocoDashChecks on GitHub</a></footer>
</body>
</html>
"""


def main():
    runs, health = load(CESM_RUNS), load(HEALTH)
    body = (
        f"<div class='kpis'>{cesm_tile(runs)}{health_tile(health)}</div>"
        f"{cesm_section(runs)}{health_section(health)}{performance_link()}{how_section()}"
    )
    page = html_page(
        "CrocoDashChecks",
        "<h1>CrocoDashChecks</h1><p>Checks that CrocoDash works end to end on NCAR's "
        "systems: every week it builds and runs real CESM cases with CrocoDash, and every "
        "day it checks that every data source CrocoDash reads still works. "
        "<a href='performance.html'>Performance</a></p>",
        body,
        # The MOM6 scaling table used to live here; links to it still land on it.
        "<script>if (location.hash === '#mom6-scaling') "
        "location.replace('performance.html#mom6-scaling');</script>\n",
    )
    perf = html_page(
        "CrocoDashChecks performance",
        "<h1>CrocoDashChecks performance</h1><p>What CrocoDash's expensive steps cost, with fits "
        "for sizing jobs. <a href='./'>Checks</a></p>",
        performance_body() + "<div id='tip' role='status'></div>"
        f"<script>{TOOLTIP_JS}</script>",
    )
    (OUT / "badges").mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page)
    (OUT / "performance.html").write_text(perf)
    badges = {
        "cesm_runs.json": badge(
            "weekly CESM runs",
            runs and cesm_status(runs),
            "passing",
            runs and runs["date"],
            "cesm",
            warn_at=1,
        ),
        "data_access.json": badge(
            "data access",
            health and health_status(health),
            "OK",
            health and health["date"],
            "health",
            warn_at=0.8,
        ),
    }
    for name, b in badges.items():
        (OUT / "badges" / name).write_text(json.dumps(b) + "\n")
    for f in (CESM_RUNS, HEALTH):
        if f.exists():
            shutil.copy2(f, OUT / f.name)
    print(f"Site written to {OUT}")


if __name__ == "__main__":
    main()
