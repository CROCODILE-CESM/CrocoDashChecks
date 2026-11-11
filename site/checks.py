"""What the site's pages share: where the results are, how old they are, and
how to show them.

index.ipynb, performance.ipynb and write_badges.py import this. Every number
on the site comes from the JSON files named here; a missing file shows as
"no results yet".
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from IPython.display import Markdown, display

ROOT = Path(__file__).resolve().parent.parent
CESM_RUNS = ROOT / "cesm_runs" / "cesm_runs.json"  # fetched from test-results
HEALTH = ROOT / "data_access" / "health.json"
PERF = ROOT / "performance"
REPO_URL = "https://github.com/CROCODILE-CESM/CrocoDashChecks"
SITE_URL = "https://crocodile-cesm.github.io/CrocoDashChecks"

# A check older than this many days means its schedule stopped running.
STALE_DAYS = {"cesm": 8, "health": 2}

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
    """A Markdown table: one header row, then one row per item."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


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
