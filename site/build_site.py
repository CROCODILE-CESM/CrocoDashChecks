#!/usr/bin/env python3
"""Build the CrocoDashChecks site: one page saying where each check stands.

Reads, each optional (a missing one renders as "no results yet"):
  cesm_runs/cesm_runs.json       weekly CESM runs (publish.yml fetches it from the
                                 test-results branch)
  data_access/health.json        daily data-access check
  performance/*.json             performance snapshots

Writes site/_build/: index.html, the two README badges (badges/*.json, from the
same counts as the page's tiles), and copies of cesm_runs.json and health.json.
Every number on the page comes from those files.

    python site/build_site.py
"""

import json
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
  @media (max-width: 640px) { .wide-only { display: none; } .ph { width: 9px; }
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


def performance_section():
    topo, rof, scaling = (
        load(PERF / f)
        for f in ("topo.json", "runoff_mapping.json", "mom6_scaling.json")
    )
    parts = [
        "<div class='panel' id='performance'><h2>Performance</h2>"
        "<p class='sub'>One-time measurements of CrocoDash's expensive steps, for sizing jobs. "
        f"Run by hand on GLADE (<a href='{REPO_URL}/tree/main/performance'>performance/</a>).</p>"
    ]
    obc = load(PERF / "obc.json")
    if obc and obc.get("benchmarks"):
        cpus = obc["benchmarks"][0]["extra_info"]["cpus"]
        parts.append(
            "<p class='sub'>Open boundaries: CrocoDash's <span class='mono'>"
            "ConditionsConfigurator.process_bc</span> on the synthetic "
            "<span class='mono'>reference_ocean</span> product (a month of daily data, "
            f"four boundaries, 0.1&deg; model grid, {cpus} cores). Memory counts the "
            "forked REGRID workers, so it is an upper bound.</p>"
        )
    for test, sweep, axis, label in (
        (
            "test_by_source_resolution",
            "by source resolution, 10&deg; box",
            "Source resolution",
            lambda e: f"{e['source_res_deg']:g}&deg;",
        ),
        (
            "test_by_domain_size",
            "by domain size, 0.25&deg; source",
            "Domain",
            lambda e: f"{e['size_deg']:g}&deg; square",
        ),
    ):
        rows = sorted(bench_rows(obc, test), key=lambda b: b["extra_info"]["n_src"])
        if rows:
            parts.append(
                f"<h3>Open boundaries, {sweep}</h3>"
                + table(
                    [
                        (axis, 0),
                        ("Source points", 1),
                        ("Boundary cells", 1),
                        ("Time", 1),
                        ("Peak memory", 1),
                    ],
                    [
                        (
                            label(b["extra_info"]),
                            f"{b['extra_info']['n_src']:,}",
                            f"{b['extra_info']['n_dst']:,}",
                            fmt_s(b["stats"]["mean"]),
                            fmt_mb(b["extra_info"]["peak_rss_mb"]),
                        )
                        for b in rows
                    ],
                )
            )
    rows = sorted(
        bench_rows(topo, "test_set_from_dataset"),
        key=lambda b: b["params"]["domain_deg"],
    )
    if rows:
        parts.append(
            "<h3>Bathymetry: GEBCO to the model grid (mom6_forge <span class='mono'>Topo.set_from_dataset</span>)</h3>"
            + table(
                [("Domain", 0), ("Time", 1), ("Memory added", 1)],
                [
                    (
                        f"{b['params']['domain_deg']}&deg; square at 0.1&deg;",
                        fmt_s(b["stats"]["mean"]),
                        fmt_mb(b["extra_info"]["rss_mb"]),
                    )
                    for b in rows
                ],
            )
        )
    for test, title, label in (
        (
            "test_gen_rof_maps_domain",
            "Runoff mapping: GLOFAS to ocean, by domain",
            lambda b: escape(b["extra_info"]["domain"].replace("_", " ")),
        ),
        (
            "test_gen_rof_maps_resolution",
            "Runoff mapping: by resolution, Gulf of Mexico",
            lambda b: f"{b['extra_info']['resolution_deg']:.3g}&deg;",
        ),
    ):
        rows = sorted(bench_rows(rof, test), key=lambda b: b["extra_info"]["n_dst"])
        if rows:
            parts.append(
                f"<h3>{title} (mom6_forge <span class='mono'>gen_rof_maps</span>)</h3>"
                + table(
                    [
                        ("Domain" if "domain" in test else "Resolution", 0),
                        ("Ocean cells", 1),
                        ("Time", 1),
                        ("Peak memory", 1),
                    ],
                    [
                        (
                            label(b),
                            f"{b['extra_info']['n_dst']:,}",
                            fmt_s(b["stats"]["mean"]),
                            fmt_mb(b["extra_info"]["peak_rss_mb"]),
                        )
                        for b in rows
                    ],
                )
            )
    if scaling:
        runs = scaling["domains"] + [scaling["reference_sweep"]]
        parts.append(
            "<h3 id='mom6-scaling'>MOM6 speed vs. NTASKS_OCN on Derecho</h3>"
            f"<p class='sub'>Compset <span class='mono'>{escape(scaling['compset'])}</span>, "
            f"{escape(scaling['queue'])} queue. Each domain's grid is in the raw "
            "<a href='https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/performance/mom6_scaling.json'>JSON</a>.</p>"
            + table(
                [
                    ("Domain", 0),
                    ("NTASKS_OCN", 1),
                    ("Simulated years/day", 1),
                    ("Run time", 1),
                ],
                [
                    (
                        escape(d["name"]),
                        p["ntasks_ocn"],
                        f"{p['throughput_sim_years_per_day']:.1f}",
                        fmt_s(p["tot_run_time_s"]),
                    )
                    for d in runs
                    for p in d["points"]
                ],
            )
        )
    return "".join(parts) + "</div>"


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
            "By hand, with pytest (see <span class='mono'>performance/</span>).",
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


def main():
    runs, health = load(CESM_RUNS), load(HEALTH)
    body = (
        f"<div class='kpis'>{cesm_tile(runs)}{health_tile(health)}</div>"
        f"{cesm_section(runs)}{health_section(health)}{how_section()}{performance_section()}"
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CrocoDashChecks</title>
<style>{CSS}</style>
</head>
<body>
<header><div class="wrap"><h1>CrocoDashChecks</h1>
<p>Checks that CrocoDash works end to end on NCAR's systems: every week it builds and runs real
CESM cases with CrocoDash, and every day it checks that every data source CrocoDash reads still works.</p>
</div></header>
<main class="wrap">{body}</main>
<footer class="wrap">Built by site/build_site.py &middot; <a href="{REPO_URL}">CrocoDashChecks on GitHub</a></footer>
</body>
</html>
"""
    (OUT / "badges").mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page)
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
