"""What the site's pages share: where the results are, how old they are, and
how to show them.

index.ipynb, performance.ipynb and write_badges.py import this. Every number
on the site comes from the results files named here; a missing file shows as
"no results yet".
"""

import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from IPython.display import Markdown, display

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "integration"
CESM_RUNS = INTEGRATION / "cesm_runs.json"  # fetched from test-results
HEALTH = ROOT / "data_access" / "health.json"
WORKFLOW = INTEGRATION / "workflow.json"  # the workflow's timings (pytest-benchmark)
WORKFLOW_OUTCOMES = (
    INTEGRATION / "workflow.xml"
)  # what passed, failed or was skipped, and why
MATRIX = INTEGRATION / "matrix.yaml"  # the grids, and what runs on each
REPO_URL = "https://github.com/CROCODILE-CESM/CrocoDashChecks"
SITE_URL = "https://crocodile-cesm.github.io/CrocoDashChecks"

# A check older than this many days means its schedule stopped running.
STALE_DAYS = {"workflow": 8, "cesm": 8, "health": 8}

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

# Status marks: always an icon beside a word, never color alone.
OK, FAIL, WARN, NOT_RUN = "✅", "❌", "⚠️", "⬜"


def load(path):
    """A results file's contents, or None if it isn't there."""
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None


def matrix():
    """matrix.yaml's rows: {grid name: its grid, and what runs on it}."""
    return yaml.safe_load(MATRIX.read_text())["grids"]


def _text(path, rev):
    """A file's text in this checkout, or as it was in git commit rev; None if missing."""
    if rev is None:
        return path.read_text() if path.exists() else None
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{path.relative_to(ROOT)}"],
        capture_output=True,
        text=True,
    )
    return shown.stdout if shown.returncode == 0 else None


def workflow(rev=None):
    """The last run of integration/test_workflow.py (or the one committed in
    rev), or None:
    {"date", "crocodash": {branch, commit} or None,
     "cases": {test id: its pytest-benchmark case}, for the steps that passed,
     "outcomes": {test id: (OK, FAIL or NOT_RUN for skipped, why)}}.
    A test id is e.g. "test_bc[equator_0e]"."""
    timings, junit = _text(WORKFLOW, rev), _text(WORKFLOW_OUTCOMES, rev)
    if timings is None or junit is None:
        return None
    timings = json.loads(timings)
    suite = ET.fromstring(junit)
    if suite.tag != "testsuite":
        suite = suite.find("testsuite")
    props = {p.get("name"): p.get("value") for p in suite.iter("property")}
    outcomes = {}
    for case in suite.iter("testcase"):
        mark, why = OK, ""
        for tag, tag_mark in (("failure", FAIL), ("error", FAIL), ("skipped", NOT_RUN)):
            node = case.find(tag)
            if node is not None:
                # A step's own error comes through its forked child as a RuntimeError.
                message = (node.get("message") or "").strip().split("\n")[0]
                mark, why = tag_mark, message.removeprefix("RuntimeError: ")
                break
        outcomes[case.get("name")] = (mark, why)
    commit = props.get("crocodash_commit")
    return {
        "date": timings["datetime"],
        "crocodash": (
            {"branch": props.get("crocodash_branch"), "commit": commit}
            if commit
            else None
        ),
        "cases": {b["name"]: b for b in timings["benchmarks"]},
        "outcomes": outcomes,
    }


def past_workflows(n):
    """The n runs of the workflow before the current one, newest first, from the
    git history of its results (each weekly run commits them). Fewer if the
    history is shorter, e.g. in a shallow clone."""
    current = workflow()
    log = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "log",
            "--format=%H",
            "--",
            str(WORKFLOW.relative_to(ROOT)),
        ],
        capture_output=True,
        text=True,
    )
    past, dates = [], {current["date"]} if current else set()
    for rev in log.stdout.split():
        run = workflow(rev)
        if run and run["date"] not in dates:
            past.append(run)
            dates.add(run["date"])
        if len(past) == n:
            break
    return past


def resolution(grid):
    """A matrix.yaml grid's resolution as written, e.g. 1/12° or 100 km."""
    if "resolution_km" in grid:
        return f"{grid['resolution_km']:g} km"
    return f"{grid['resolution']}°"


def _time(iso):
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def when(iso):
    """A results file's timestamp in Mountain Time, like the schedules."""
    return (
        _time(iso)
        .astimezone(ZoneInfo("America/Denver"))
        .strftime("%a %b %-d, %H:%M %Z")
    )


def age_days(iso):
    return (datetime.now(timezone.utc) - _time(iso)).days


def is_stale(iso, kind):
    return age_days(iso) > STALE_DAYS[kind]


def cesm_counts(runs):
    """(tests passed, tests run) in a weekly CESM-run summary."""
    return sum(t["passed"] for t in runs["tests"]), len(runs["tests"])


def health_counts(health):
    """(access methods OK, methods checked) in a data-access snapshot."""
    checks = health["validate_checks"]
    return sum(c["ok"] for c in checks), len(checks)


def commit(ref, repo):
    """'main at abc1234', linked to the commit on GitHub."""
    if not ref:
        return "not recorded"
    url = f"https://github.com/CROCODILE-CESM/{repo}/commit/{ref['commit']}"
    return f"`{ref['branch']}` at [`{ref['commit']}`]({url})"


def table(headers, rows):
    """A compact Markdown table: one header row, then one row per item.
    table-sm is the theme's own class for tight cells; widths auto keeps each
    column as narrow as its content."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return (
        "```{table}\n:class: table-sm\n:widths: auto\n\n" + "\n".join(lines) + "\n```"
    )


def plain(text):
    """Text shown as is, e.g. an error message: Markdown's special characters
    escaped (table() escapes | itself)."""
    for ch in "\\`*_[]<>#":
        text = text.replace(ch, "\\" + ch)
    return text


def show(markdown):
    """Put Markdown on the page."""
    display(Markdown(markdown))


def fmt_s(seconds):
    return f"{seconds:.1f} s" if seconds < 60 else f"{seconds / 60:.1f} min"


def fmt_gb(gb):
    return f"{gb:.1f} GB" if gb >= 1 else f"{gb * 1024:.0f} MB"
