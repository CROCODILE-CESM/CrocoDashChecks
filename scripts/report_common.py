#!/usr/bin/env python3
"""
report_common.py — Shared page shell (CSS + header + nav + footer) for every
generate_*_report.py script. Several generators render into the same report/
directory and cross-link each other; keeping the shell in one place means the
nav links can't drift out of sync page-by-page.

Also publishes the raw results/*.json each page is built from into report/,
next to the rendered HTML, so the underlying data is fetchable at a stable
Pages URL instead of only living in the git repo.
"""

import shutil

# (href, label, source results/*.json filename or None, nav group) for every
# page in report/, in nav-bar order. The json name is what gets linked as "raw
# data" on that page, and is the file publish_results_json() copies into report/.
NAV_PAGES = [
    ("index.html", "Dashboard", None, None),
    ("health.html", "Data access", "health.json", "Checks"),
    ("mom6_scaling.html", "MOM6 scaling", "mom6_scaling.json", "Performance"),
    ("runoff_mapping.html", "Runoff mapping", "latest.json", "Performance"),
    ("regridding.html", "Regridding", "latest.json", "Performance"),
    ("crocodash.html", "CrocoDash OBC", "latest.json", "Performance"),
    ("mom6_forge.html", "mom6_forge bathymetry", "latest.json", "Performance"),
]

# Colors are the dataviz reference palette's ink, surface and status roles.
# Status colors (good/warning/critical) only ever mark state, always beside a
# text label, never a data series.
BASE_CSS = """
  :root { color-scheme: light;
          --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
          --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7;
          --border: rgba(11,11,11,0.10); --accent: #2a78d6;
          --good: #0ca30c; --good-text: #006300; --warning: #fab219; --critical: #d03b3b; }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         margin: 0; padding: 0; background: var(--page); color: var(--ink); }
  a { color: var(--accent); }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 0 16px; box-sizing: border-box; }
  header { background: var(--surface); border-bottom: 1px solid var(--grid); }
  header .wrap { padding-top: 1.25rem; padding-bottom: 0.6rem; }
  header h1 { margin: 0 0 0.2rem; font-size: 1.5rem; }
  header p { margin: 0 0 0.8rem; color: var(--ink-2); font-size: 0.92rem; }
  header nav { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.3rem 1.1rem;
               font-size: 0.85rem; }
  header nav .group { color: var(--muted); font-size: 0.7rem; text-transform: uppercase;
                      letter-spacing: 0.05em; margin-left: 0.4rem; }
  header nav a { color: var(--ink-2); text-decoration: none; padding: 0.15rem 0;
                 border-bottom: 2px solid transparent; }
  header nav a:hover { color: var(--ink); }
  header nav a[aria-current="page"] { color: var(--ink); font-weight: 600;
                                      border-bottom-color: var(--accent); }
  section { padding: 1.25rem 0 0.25rem; }
  section h2 { font-size: 1.1rem; margin: 0 0 0.8rem; color: var(--ink); }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
          padding: 1rem 1.25rem; margin-bottom: 1.25rem; overflow-x: auto; }
  .card h3 { margin: 0 0 0.6rem; font-size: 0.95rem; color: var(--ink);
             font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  .card p { margin: 0; color: var(--ink-2); font-size: 0.88rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th, td { text-align: right; padding: 0.35rem 0.6rem; }
  th:first-child, td:first-child { text-align: left; }
  thead th, tr:first-child th { border-bottom: 1px solid var(--axis); color: var(--ink-2);
                                font-weight: 600; }
  tbody tr + tr td, tr + tr td { border-top: 1px solid var(--grid); }
  .ok { color: var(--good-text); font-weight: 600; }
  .fail { color: var(--critical); font-weight: 600; }
  footer { padding: 1.5rem 0 2rem; font-size: 0.8rem; color: var(--muted); }
"""

HEATMAP_CSS = """
  #regrid-cost { }
  .hm-legend-label { display: flex; align-items: center; gap: 0.5rem;
                       font-size: 0.78rem; color: #555; margin: 0 0 1.25rem; }
  .hm-legend-bar { display: inline-block; width: 140px; height: 10px;
                     border-radius: 5px; }
  .hm-group { margin-bottom: 1.5rem; }
  .hm-group h3 { font-size: 0.95rem; color: #333; margin: 0 0 0.15rem; }
  .hm-group-sub { font-size: 0.75rem; color: #777; margin: 0 0 0.75rem; }
  .hm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
              gap: 1.25rem; }
  .hm-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
               padding: 0.9rem 1rem; }
  .hm-panel h4 { margin: 0 0 0.6rem; font-size: 0.82rem; color: #333;
                  font-family: 'SFMono-Regular', Consolas, monospace; font-weight: 600; }
  table.heatmap { border-collapse: separate; border-spacing: 3px; width: 100%; }
  table.heatmap th { font-size: 0.68rem; font-weight: 500; color: #777;
                      text-align: center; padding: 0.15rem; }
  table.heatmap td.hm-cell { text-align: center; font-variant-numeric: tabular-nums;
                              font-size: 0.7rem; padding: 0.5rem 0.3rem; border-radius: 4px; }
  table.heatmap td.hm-empty { color: #bbb; text-align: center; }
"""

LINECHART_CSS = """
  .linechart { width: 100%; max-width: 480px; height: auto; display: block; }
  .lc-sub { font-size: 0.75rem; color: #777; margin: -0.4rem 0 0.75rem; }
  .lc-axis { font-size: 9px; fill: #898781; font-family: -apple-system, sans-serif; }
  .lc-value { font-size: 10px; fill: #333; font-variant-numeric: tabular-nums;
               font-family: -apple-system, sans-serif; }
  .lc-legend { display: flex; flex-wrap: wrap; gap: 1rem; margin: 0.25rem 0 0.75rem;
               font-size: 0.75rem; color: #555; }
  .lc-legend-item { display: flex; align-items: center; gap: 0.35rem; }
  .lc-legend-swatch { display: inline-block; width: 22px; height: 3px; border-radius: 2px; }
"""


def render_nav(current):
    """Nav links to every report page, under their group labels, with the
    page being rendered marked as current."""
    parts, group = [], None
    for href, label, _, page_group in NAV_PAGES:
        if page_group and page_group != group:
            parts.append(f'<span class="group">{page_group}</span>')
        group = page_group
        mark = ' aria-current="page"' if href == current else ""
        parts.append(f'<a href="{href}"{mark}>{label}</a>')
    return "".join(parts)


def json_link_for(current):
    """The raw results/*.json filename this page is built from, or None."""
    return next(
        (json_name for href, _, json_name, _ in NAV_PAGES if href == current), None
    )


def page_shell(current, title, subtitle_html, body_html, footer_text, extra_css=""):
    """Wrap body_html in the common doctype/head/header/footer. `current` is
    the page's own filename (e.g. "regridding.html"), used to build the nav
    bar, mark the current page, and link the raw JSON this page renders."""
    json_name = json_link_for(current)
    json_link = (
        f' &middot; <a href="{json_name}">Raw data (JSON)</a>' if json_name else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{BASE_CSS}{extra_css}</style>
</head>
<body>
<header><div class="wrap">
  <h1>{title}</h1>
  <p>{subtitle_html}{json_link}</p>
  <nav>{render_nav(current)}</nav>
</div></header>
<main class="wrap">
{body_html}
</main>
<footer class="wrap">{footer_text}</footer>
</body>
</html>
"""


def publish_results_json(results_file, report_dir):
    """Copy the raw results JSON into report/ so it's served at the same
    stable Pages URL as the rendered HTML — fetchable by helper scripts
    without touching the git repo or scraping HTML."""
    if results_file.exists():
        shutil.copy2(results_file, report_dir / results_file.name)
