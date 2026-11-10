#!/usr/bin/env python3
"""
generate_dashboard.py — report/index.html: one page saying what this repo
checks and where each check stands right now.

Reads, each optional (a missing one renders as "no results yet"):
  results/cesm_runs.json  the weekly CESM runs (cesm_runs/run_mom_tests.py writes
                          it to the test-results branch; publish.yml fetches it)
  results/health.json     the daily data-access check (scripts/data_access.pbs)
  results/latest.json     the performance snapshot (scripts/run_benchmarks.sh)

Every number on the page is computed from those files.

Output: report/index.html, and report/badges/{cesm_runs,data_access}.json
(shields.io endpoint badges for the README, from the same counts as the tiles).
"""

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from report_common import NAV_PAGES, page_shell, publish_results_json

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
OUTPUT_FILE = REPO_ROOT / "report" / "index.html"
BADGE_DIR = REPO_ROOT / "report" / "badges"
REPO_URL = "https://github.com/CROCODILE-CESM/CrocoDashChecks"
MOUNTAIN_TZ = ZoneInfo("America/Denver")

# CIME's test phases in the order a test goes through them, and what each is
# for a CrocoDash-built case (see cesm_runs/README.md).
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

PERF_DESCRIPTIONS = {
    "mom6_scaling.html": "How MOM6's speed on Derecho scales with NTASKS_OCN.",
    "runoff_mapping.html": "GLOFAS runoff mapping (gen_rof_maps) cost up a ladder of ocean domain sizes.",
    "regridding.html": "xESMF/ESMF weight generation and apply cost across grid sizes.",
    "crocodash.html": "OBC forcing pipeline (regrid + merge) cost vs. chunk size.",
    "mom6_forge.html": "Bathymetry pipeline (Topo.set_from_dataset) cost vs. domain size.",
}

DASH_CSS = """
  .lede { color: var(--ink-2); max-width: 72ch; margin: 1.25rem 0 0; font-size: 0.95rem; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1rem; margin-top: 1.25rem; }
  .tile, .panel { background: var(--surface); border: 1px solid var(--border);
                  border-radius: 8px; padding: 1rem 1.25rem; }
  .tile h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
             color: var(--ink-2); margin: 0 0 0.4rem; font-weight: 600; }
  .tile h2 a { color: inherit; text-decoration: none; }
  .tile .value { font-size: 2.6rem; font-weight: 600; line-height: 1.1; }
  .tile .unit { color: var(--ink-2); font-size: 0.9rem; margin-left: 0.3rem; }
  .tile .chips { margin-top: 0.6rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .tile .detail { color: var(--ink-2); font-size: 0.8rem; margin: 0.6rem 0 0; }
  .chip { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.78rem;
          font-weight: 600; padding: 0.15rem 0.6rem; border-radius: 999px;
          border: 1px solid var(--border); background: var(--page); color: var(--ink);
          white-space: nowrap; }
  .chip::before { content: ""; width: 0.55rem; height: 0.55rem; border-radius: 50%;
                  background: var(--dot, var(--muted)); }
  .chip-good { --dot: var(--good); }
  .chip-warning { --dot: var(--warning); }
  .chip-critical { --dot: var(--critical); }
  .panel { margin-top: 1.25rem; overflow-x: auto; }
  .panel h2 { font-size: 1.05rem; margin: 0 0 0.25rem; }
  .panel .sub { color: var(--ink-2); font-size: 0.85rem; margin: 0 0 1rem; max-width: 80ch; }
  .split { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
           gap: 0 1.25rem; align-items: start; }
  @media (max-width: 860px) { .split { grid-template-columns: minmax(0, 1fr); } }
  table.dash th, table.dash td { text-align: left; vertical-align: middle; padding: 0.45rem 0.6rem; }
  table.dash td.num, table.dash th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.8rem; }
  .muted { color: var(--muted); }
  .phases { display: inline-flex; gap: 2px; }
  .ph { display: inline-block; width: 16px; height: 12px; border-radius: 3px; background: var(--grid); }
  .ph-pass { background: var(--good); }
  .ph-fail { background: var(--critical); }
  .legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; color: var(--ink-2);
            font-size: 0.78rem; margin: 0.8rem 0 0; align-items: center; }
  .legend .ph { margin-right: 0.3rem; vertical-align: -1px; }
  .note { color: var(--ink-2); font-size: 0.8rem; margin: 0.6rem 0 0; }
  .why { color: var(--ink-2); font-size: 0.75rem; margin-top: 0.15rem; overflow-wrap: anywhere; }
  @media (max-width: 640px) { .wide-only { display: none; } .ph { width: 9px; }
                              table.dash th, table.dash td { padding: 0.4rem 0.3rem; } }
  .meter { display: flex; gap: 2px; height: 8px; margin: 0.2rem 0 1rem; }
  .meter span { border-radius: 4px; }
  .meter .m-ok { background: var(--good); }
  .meter .m-bad { background: var(--critical); }
  .how { list-style: none; margin: 0; padding: 0; font-size: 0.85rem; }
  .how li + li { border-top: 1px solid var(--grid); }
  .how li { padding: 0.65rem 0; }
  .how b { display: block; margin-bottom: 0.15rem; }
  .how span { color: var(--ink-2); }
  .perf { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.75rem; }
  .perf a { display: block; padding: 0.75rem 0.9rem; border: 1px solid var(--border);
            border-radius: 6px; text-decoration: none; background: var(--page); }
  .perf a:hover { border-color: var(--accent); }
  .perf b { color: var(--ink); display: block; margin-bottom: 0.2rem; font-size: 0.9rem; }
  .perf span { color: var(--ink-2); font-size: 0.8rem; }
"""


def load(name):
    path = RESULTS_DIR / name
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


def tile(title, href, value, unit, chips, detail):
    return (
        f'<div class="tile"><h2><a href="{href}">{title}</a></h2>'
        f'<div><span class="value">{value}</span><span class="unit">{unit}</span></div>'
        f'<div class="chips">{chips}</div><p class="detail">{detail}</p></div>'
    )


def no_results_tile(title, href, how):
    return tile(title, href, "&ndash;", "", chip("warning", "No results yet"), how)


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


# --- weekly CESM runs ------------------------------------------------------


def cesm_status(runs):
    tests = runs["tests"]
    passed = sum(t["passed"] for t in tests)
    return passed, len(tests)


def cesm_tile(runs):
    href = "#cesm"
    if not runs:
        return no_results_tile(
            "Weekly CESM runs", href, "Runs every Monday on Derecho."
        )
    passed, total = cesm_status(runs)
    state = (
        chip("good", "All passing")
        if passed == total
        else chip("critical", f"{total - passed} failing")
    )
    return tile(
        "Weekly CESM runs",
        href,
        f"{passed}/{total}",
        "tests passing",
        state + stale_chip(runs["date"], "cesm"),
        f"Last run {when(runs['date'])}",
    )


def phase_strip(phases):
    status = dict(phases)
    cells = []
    for phase, label in PHASES:
        st = status.get(phase)
        css = {"PASS": "ph-pass", "FAIL": "ph-fail"}.get(st, "")
        cells.append(
            f'<span class="ph {css}" title="{label}: {st or "not reached"}"></span>'
        )
    return (
        f'<span class="phases" role="img" aria-label="phases">{"".join(cells)}</span>'
    )


def result_chip(test):
    if test["passed"]:
        return chip("good", "Pass")
    status = dict(test["phases"])
    failed = next(
        (label for phase, label in PHASES if status.get(phase) == "FAIL"), None
    )
    return (
        chip("critical", f"Failed: {failed}")
        if failed
        else chip("warning", "Incomplete")
    )


def cesm_panel(runs):
    intro = (
        "Every Monday, each regional SMS test in MOM_interface's <span class='mono'>testlist_mom.xml</span> "
        "is built with CrocoDash on our test domain and run in CESM on a Derecho node. "
        f"See <a href='{REPO_URL}/tree/main/cesm_runs'>cesm_runs/</a>."
    )
    if not runs:
        return f"<div class='panel' id='cesm'><h2>Weekly CESM runs on Derecho</h2><p class='sub'>{intro}</p><p>No results yet.</p></div>"
    rows = "".join(
        f"<tr><td class='mono'>{escape(t['compset'])}</td><td class='mono wide-only'>{escape(t['test'])}</td>"
        f"<td class='wide-only'>{components(t['longname'])}</td><td>{phase_strip(t['phases'])}</td>"
        f"<td>{result_chip(t)}</td></tr>"
        for t in sorted(runs["tests"], key=lambda t: (t["passed"], t["compset"]))
    )
    order = " &rarr; ".join(label for _, label in PHASES)
    tested = (
        f"Run {when(runs['date'])} with CESM {commit_link(runs.get('cesm'), 'CESM')} "
        f"and CrocoDash {commit_link(runs.get('crocodash'), 'CrocoDash')}."
    )
    return (
        "<div class='panel' id='cesm'><h2>Weekly CESM runs on Derecho</h2>"
        f"<p class='sub'>{intro}</p>"
        "<table class='dash'><thead><tr><th>Compset</th><th class='wide-only'>Test</th><th class='wide-only'>Components</th>"
        f"<th>Phases</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<p class='legend'><span><span class='ph ph-pass'></span>passed</span>"
        f"<span><span class='ph ph-fail'></span>failed</span>"
        f"<span><span class='ph'></span>not reached</span>"
        f"<span>Phases, left to right: {order}</span></p>"
        f"<p class='note'>{tested}</p></div>"
    )


# --- daily data access ----------------------------------------------------


def health_checks(health):
    return health.get("validate_checks", []) + health.get("link_checks", [])


def health_status(health):
    checks = health_checks(health)
    return sum(1 for c in checks if c["ok"]), len(checks)


def health_tile(health):
    href = "health.html"
    if not health or not health.get("date"):
        return no_results_tile("Data access", href, "Checked every day on GLADE.")
    ok, total = health_status(health)
    if ok == total:
        state = chip("good", "All OK")
    else:
        state = chip(
            "warning" if ok >= 0.8 * total else "critical",
            f"{total - ok} failing",
        )
    return tile(
        "Data access",
        href,
        f"{ok}/{total}",
        "checks OK",
        state + stale_chip(health["date"], "health"),
        f"Checked {when(health['date'])}",
    )


def meter(ok, total):
    if not total:
        return ""
    bad = total - ok
    parts = f'<span class="m-ok" style="flex:{ok}"></span>' if ok else ""
    parts += f'<span class="m-bad" style="flex:{bad}"></span>' if bad else ""
    return (
        f'<div class="meter" role="img" aria-label="{ok} of {total} OK">{parts}</div>'
    )


def health_panel(health):
    intro = (
        "Every day, each way CrocoDash can fetch data (<span class='mono'>ProductRegistry.validate_function</span>) "
        "is called for real on Casper, with GLADE and our credentials, and each product's documentation link is checked."
    )
    if not health or not health.get("date"):
        return f"<div class='panel'><h2>Data access, daily on GLADE</h2><p class='sub'>{intro}</p><p>No results yet.</p></div>"
    validate = health.get("validate_checks", [])
    links = health.get("link_checks", [])
    rows = "".join(
        f"<tr><td>{escape(r['product'])}</td><td><span class='mono'>{escape(r['method'])}</span>"
        + (f"<div class='why'>{escape(r['detail'])}</div>" if r.get("detail") else "")
        + "</td>"
        f"<td>{chip('good', 'OK') if r['ok'] else chip('critical', 'Failing')}</td>"
        f"<td class='num'>{r['elapsed_s']:.1f} s</td></tr>"
        for r in sorted(validate, key=lambda r: (r["ok"], r["product"], r["method"]))
    )
    v_ok = sum(1 for r in validate if r["ok"])
    l_ok = sum(1 for r in links if r["ok"])
    bad_links = ", ".join(escape(r["product"]) for r in links if not r["ok"])
    link_line = f"Documentation links: {l_ok} of {len(links)} reachable" + (
        f" (not: {bad_links})." if bad_links else "."
    )
    return (
        "<div class='panel'><h2>Data access, daily on GLADE</h2>"
        f"<p class='sub'>{intro}</p>"
        f"<p class='note'>Access methods: {v_ok} of {len(validate)} working</p>{meter(v_ok, len(validate))}"
        "<table class='dash'><thead><tr><th>Product</th><th>Access method</th><th>Status</th>"
        f"<th class='num'>Time</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<p class='note'>{link_line} Details: <a href='health.html'>Data access</a> &middot; "
        "<a href='health.json'>health.json</a></p></div>"
    )


# --- performance snapshot ---------------------------------------------------


def perf_tile(latest):
    href = "#performance"
    if not latest:
        return no_results_tile(
            "Performance snapshot", href, "Run by hand with scripts/run_benchmarks.sh."
        )
    n = len(latest.get("benchmarks", []))
    date = latest.get("datetime")
    return tile(
        "Performance snapshot",
        href,
        f"{n}",
        "benchmarks",
        chip("neutral", "One-time snapshot"),
        f"Snapshot from {when(date)}" if date else "",
    )


def perf_panel():
    cards = "".join(
        f"<a href='{href}'><b>{label}</b><span>{PERF_DESCRIPTIONS[href]}</span></a>"
        for href, label, _, group in NAV_PAGES
        if group == "Performance"
    )
    return (
        "<div class='panel' id='performance'><h2>Performance &amp; scaling</h2>"
        "<p class='sub'>One-time snapshots of how long the expensive steps take and how they scale, "
        "for sizing jobs. Run by hand on Derecho, not on a schedule.</p>"
        f"<div class='perf'>{cards}</div></div>"
    )


def how_panel():
    items = [
        (
            "Weekly CESM runs",
            "Mondays 02:00 MT. cron.hpc.ucar.edu submits a Derecho job "
            "(<span class='mono'>cesm_runs/cron_submit.sh</span>); results go to the "
            "<span class='mono'>test-results</span> branch.",
        ),
        (
            "Data access",
            "Daily 05:00 MT. cron.hpc.ucar.edu submits a Casper job "
            "(<span class='mono'>scripts/data_access_cron.sh</span>); it pushes "
            "<span class='mono'>results/health.json</span>, which rebuilds this site.",
        ),
        (
            "Performance",
            "By hand, when something changes "
            "(<span class='mono'>scripts/run_benchmarks.sh</span>).",
        ),
    ]
    rows = "".join(f"<li><b>{t}</b><span>{d}</span></li>" for t, d in items)
    return (
        f"<div class='panel'><h2>What runs when</h2><ul class='how'>{rows}</ul></div>"
    )


def badge(label, counts, word, iso, kind, warn_at):
    """A shields.io endpoint badge: the same counts, colors and staleness as
    the dashboard's tile for that check."""
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


def write_badges(runs, health):
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    have_health = health and health.get("date")
    badges = {
        "cesm_runs.json": badge(
            "weekly CESM runs",
            cesm_status(runs) if runs else None,
            "passing",
            runs and runs["date"],
            "cesm",
            warn_at=1,
        ),
        "data_access.json": badge(
            "data access",
            health_status(health) if have_health else None,
            "OK",
            have_health and health["date"],
            "health",
            warn_at=0.8,
        ),
    }
    for name, b in badges.items():
        (BADGE_DIR / name).write_text(json.dumps(b) + "\n")


def build_html(runs, health, latest):
    body = (
        "<p class='lede'>CrocoDashChecks checks that CrocoDash works end to end on NCAR's systems: "
        "every week it builds and runs real CESM cases with CrocoDash, every day it checks that "
        "every data source CrocoDash reads still works, and it keeps performance snapshots for sizing jobs.</p>"
        f"<div class='kpis'>{cesm_tile(runs)}{health_tile(health)}{perf_tile(latest)}</div>"
        f"{cesm_panel(runs)}"
        f"<div class='split'>{health_panel(health)}{how_panel()}</div>"
        f"{perf_panel()}"
    )
    footer = (
        f"Generated by scripts/generate_dashboard.py from results/*.json &middot; "
        f"<a href='{REPO_URL}'>CrocoDashChecks on GitHub</a>"
    )
    return page_shell(
        "index.html",
        "CrocoDashChecks",
        "Is CrocoDash working end to end?",
        body,
        footer,
        extra_css=DASH_CSS,
    )


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    runs, health = load("cesm_runs.json"), load("health.json")
    OUTPUT_FILE.write_text(build_html(runs, health, load("latest.json")))
    write_badges(runs, health)
    publish_results_json(RESULTS_DIR / "cesm_runs.json", OUTPUT_FILE.parent)
    print(f"Dashboard written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
