#!/usr/bin/env python3
"""
generate_scaling_report.py — Build a static HTML page from results/mom6_scaling.json.

Two sections:
  1. Location comparison — four 100×100 domains (Caribbean, Equatorial Pacific, Arctic,
     Antarctic) each run at NTASKS_OCN=20 and 40 on Derecho's develop queue. One combined
     multi-line chart (all domains, since there are only two NTASKS points each), a
     cross-domain comparison table, plus a per-domain results table.
  2. Historical NTASKS sweep — the original Bahamas full-sweep data kept for reference.

Output: report/mom6_scaling.html
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = REPO_ROOT / "results" / "mom6_scaling.json"
OUTPUT_FILE = REPO_ROOT / "report" / "mom6_scaling.html"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_report import _linechart_svg, _normalize_log  # noqa: E402
from report_common import LINECHART_CSS, page_shell, publish_results_json  # noqa: E402

SCALING_EXTRA_CSS = """
  .lc-legend { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 0.25rem; }
  .lc-legend-item { font-size: 0.8rem; color: #555; display: flex; align-items: center; gap: 0.35rem; }
  .lc-legend-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
"""


def load_scaling():
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        return json.load(f)


def fmt_s(v):
    return f"{v:.1f} s" if v < 60 else f"{v / 60:.1f} min"


def make_table_html(points):
    if not points:
        return "<p><em>No results yet.</em></p>"
    baseline = min(points, key=lambda p: p["ntasks_ocn"])
    baseline_per_core = (
        baseline["throughput_sim_years_per_day"] / baseline["ntasks_ocn"]
    )
    rows = []
    for p in points:
        per_core = p["throughput_sim_years_per_day"] / p["ntasks_ocn"]
        efficiency = 100.0 * per_core / baseline_per_core
        rows.append(
            f"<tr><td>{p['ntasks_ocn']}</td>"
            f"<td>{p['throughput_sim_years_per_day']:.2f}</td>"
            f"<td>{fmt_s(p['tot_run_time_s'])}</td>"
            f"<td>{p['ocn_cost_pe_hrs']:.1f}</td>"
            f"<td>{efficiency:.0f}%</td></tr>"
        )
    return (
        "<table><tr><th>NTASKS_OCN</th><th>Throughput (sim-years/day)</th>"
        "<th>Total Run Time</th><th>OCN Cost (pe-hrs/sim-year)</th>"
        f"<th>Parallel efficiency (vs N={baseline['ntasks_ocn']})</th></tr>"
        f"{''.join(rows)}</table>"
    )


DOMAIN_COLORS = ["#2a78d6", "#1baf7a", "#d68c2a", "#c33d69"]


def _multi_linechart_svg(series, y_fmt=lambda v: f"{v:.1f}", width=480, height=280):
    """series: list of (name, color, [(x_label, y_value), ...]) sharing one x-axis.
    Plain inline SVG, no charting library -- multiple colored lines + a legend,
    for comparing a handful of domains at the same small set of NTASKS points."""
    pad_l, pad_r, pad_t, pad_b = 46, 20, 24, 44
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    all_x = sorted({x for _, _, pts in series for x, _ in pts}, key=lambda v: int(v))
    all_y = [y for _, _, pts in series for _, y in pts]
    if not all_x or not all_y:
        return "<p><em>No results yet.</em></p>"
    vmin, vmax = min(all_y), max(all_y)
    n = len(all_x)

    def x_at(i):
        return pad_l + (i / (n - 1) if n > 1 else 0.5) * plot_w

    def y_at(v):
        t = _normalize_log(v, vmin, vmax)
        return pad_t + (1 - t) * plot_h

    x_index = {x: i for i, x in enumerate(all_x)}

    gridlines = "".join(
        f"<line x1='{pad_l}' y1='{pad_t + f * plot_h:.1f}' "
        f"x2='{pad_l + plot_w}' y2='{pad_t + f * plot_h:.1f}' "
        f"stroke='#e1e0d9' stroke-width='1'/>"
        for f in (0.0, 0.25, 0.5, 0.75, 1.0)
    )
    x_labels = "".join(
        f"<text x='{x_at(i):.1f}' y='{height - pad_b + 18}' text-anchor='middle' "
        f"class='lc-axis'>N={x}</text>"
        for i, x in enumerate(all_x)
    )

    lines_html = []
    for name, color, pts in series:
        pts_sorted = sorted(pts, key=lambda p: x_index[p[0]])
        coords = [(x_at(x_index[x]), y_at(v)) for x, v in pts_sorted]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        dots = "".join(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='{color}'>"
            f"<title>{name} N={pts_sorted[i][0]}: {y_fmt(pts_sorted[i][1])}</title></circle>"
            for i, (x, y) in enumerate(coords)
        )
        lines_html.append(
            f"<polyline points='{poly}' fill='none' stroke='{color}' stroke-width='2'/>{dots}"
        )

    legend = "".join(
        f"<span class='lc-legend-item'><span class='lc-legend-swatch' "
        f"style='background:{color}'></span>{name}</span>"
        for name, color, _ in series
    )

    return f"""
    <svg class="linechart" viewBox="0 0 {width} {height}" role="img"
         aria-label="Line chart comparing throughput across domains and NTASKS_OCN">
      {gridlines}
      {''.join(lines_html)}
      {x_labels}
    </svg>
    <div class="lc-legend">{legend}</div>"""


def build_domain_table_section(domain):
    points = sorted(domain.get("points", []), key=lambda p: p["ntasks_ocn"])
    name = domain["name"]
    grid = domain.get("grid", "")
    table = make_table_html(points)
    return f"""
    <div class="card">
      <h3>{name}</h3>
      <p class="lc-sub">{grid}</p>
      {table}
    </div>"""


def make_comparison_table_html(domains):
    """One row per domain, columns = NTASKS points present across all domains."""
    all_ntasks = sorted(
        {p["ntasks_ocn"] for d in domains for p in d.get("points", [])}
    )
    if not all_ntasks:
        return "<p><em>No comparison data yet.</em></p>"

    header = "".join(f"<th>N={n}</th>" for n in all_ntasks)
    rows = []
    for d in domains:
        by_n = {p["ntasks_ocn"]: p["throughput_sim_years_per_day"] for p in d.get("points", [])}
        cells = "".join(
            f"<td>{by_n[n]:.2f}</td>" if n in by_n else "<td>—</td>"
            for n in all_ntasks
        )
        rows.append(f"<tr><td>{d['name']}</td>{cells}</tr>")

    return (
        "<table><tr><th>Domain</th>" + header + "</tr>"
        + "".join(rows) + "</table>"
    )


def build_html(data):
    if not data:
        body = "<section><p>No scaling results found.</p></section>"
        return page_shell(
            "mom6_scaling.html",
            "CrocoDashChecks MOM6 Scaling Report",
            "Location-dependent scaling sweep on Derecho.",
            body,
            "Generated by scripts/generate_scaling_report.py",
            extra_css=LINECHART_CSS + SCALING_EXTRA_CSS,
        )

    domains = data.get("domains", [])
    ref = data.get("reference_sweep")

    # --- Section 1: location comparison ---
    if domains:
        meta = (
            f"<p class='lc-sub'>Compset: <code>{data.get('compset', '?')}</code> &mdash; "
            f"machine: {data.get('machine', '?')}, queue: {data.get('queue', '?')} &mdash; "
            f"date range: {', '.join(data.get('date_range', []))}</p>"
        )
        chart_series = [
            (
                d["name"],
                DOMAIN_COLORS[i % len(DOMAIN_COLORS)],
                [
                    (str(p["ntasks_ocn"]), p["throughput_sim_years_per_day"])
                    for p in sorted(d.get("points", []), key=lambda p: p["ntasks_ocn"])
                ],
            )
            for i, d in enumerate(domains)
        ]
        combined_chart = _multi_linechart_svg(
            [s for s in chart_series if s[2]], y_fmt=lambda v: f"{v:.1f} y/day"
        )
        domain_tables = "".join(build_domain_table_section(d) for d in domains)
        comparison = make_comparison_table_html(domains)
        location_section = f"""
    <section>
      <h2>Throughput by Geographic Location</h2>
      {meta}
      <p>Each domain is 100×100 grid points, flat 1000 m bathymetry, 10 vertical levels,
         run at NTASKS_OCN=20 and 40 on Derecho's develop queue (~24-day simulation).
         Does MOM6/CESM throughput vary by where on Earth the domain sits?</p>
      <p><strong>Note:</strong> DT (baroclinic timestep) is auto-selected by CrocoDash based
         on grid spacing — a coarser grid allows a larger CFL-stable DT, which reduces
         wallclock time independently of geographic location. All domains here use a matched
         DT=600 s so the comparison reflects location effects rather than timestep artifacts.
         Increasing or decreasing DT has a direct proportional effect on throughput.</p>
      <div class="card">
        <h3>Throughput (sim-years/day) by domain and NTASKS_OCN</h3>
        {combined_chart}
      </div>
      <div class="card">
        <h3>Cross-domain comparison — throughput (sim-years/day)</h3>
        {comparison}
      </div>
      {domain_tables}
    </section>"""
    else:
        location_section = "<section><p>No location-comparison results yet.</p></section>"

    # --- Section 2: historical reference sweep ---
    if ref and ref.get("points"):
        ref_points = sorted(ref["points"], key=lambda p: p["ntasks_ocn"])
        ref_chart_pts = [
            (str(p["ntasks_ocn"]), p["throughput_sim_years_per_day"]) for p in ref_points
        ]
        ref_chart = _linechart_svg(
            ref_chart_pts, y_fmt=lambda v: f"{v:.1f} y/day", color="#6c757d"
        )
        ref_table = make_table_html(ref_points)
        ref_section = f"""
    <section>
      <h2>Reference: Bahamas Full NTASKS Sweep</h2>
      <p class="lc-sub">{ref.get('grid', '')} &mdash; queue: {ref.get('queue', '')}</p>
      <div class="card">
        <h3>Throughput vs. NTASKS_OCN (1–80 cores)</h3>
        <p class="lc-sub">x-axis: NTASKS_OCN</p>
        {ref_chart}
        {ref_table}
      </div>
    </section>"""
    else:
        ref_section = ""

    body = location_section + ref_section

    return page_shell(
        "mom6_scaling.html",
        "CrocoDashChecks MOM6 Scaling Report",
        "Location-dependent scaling sweep on Derecho.",
        body,
        "Generated by scripts/generate_scaling_report.py",
        extra_css=LINECHART_CSS + SCALING_EXTRA_CSS,
    )


def main():
    data = load_scaling()
    if not data:
        print(f"No scaling results found in {RESULTS_FILE}.", file=sys.stderr)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_html(data))
    publish_results_json(RESULTS_FILE, OUTPUT_FILE.parent)
    print(f"Scaling report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
