#!/usr/bin/env python3
"""Write the README's two badges, and copies of the raw results, into the built
site. Run it after sphinx-build:

    sphinx-build site site/_build/html
    python site/write_badges.py

Each badge is a shields.io "endpoint" file (badges/cesm_runs.json and
badges/data_access.json) with the same counts as the Status page: green when
everything passes, orange or red when something fails, yellow when the
results are stale (the schedule stopped running).
"""

import json
import shutil

from checks import (
    CESM_RUNS,
    HEALTH,
    ROOT,
    cesm_counts,
    health_counts,
    is_stale,
    load,
)

OUT = ROOT / "site" / "_build" / "html"


def badge(label, results, counts, word, kind, orange_from):
    """orange_from: the fraction passing at or above which a failure is orange, not red."""
    if results is None:
        return {
            "schemaVersion": 1,
            "label": label,
            "message": "no results",
            "color": "lightgrey",
        }
    ok, total = counts(results)
    message = f"{ok}/{total} {word}"
    if ok == total:
        color = "brightgreen"
    elif ok >= orange_from * total:
        color = "orange"
    else:
        color = "red"
    if is_stale(results["date"], kind):
        message, color = f"{message}, stale", "yellow"
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def main():
    runs, health = load(CESM_RUNS), load(HEALTH)
    badges = {
        "cesm_runs.json": badge(
            "weekly CESM runs", runs, cesm_counts, "passing", "cesm", 1
        ),
        "data_access.json": badge(
            "data access", health, health_counts, "OK", "health", 0.8
        ),
    }
    (OUT / "badges").mkdir(parents=True, exist_ok=True)
    for name, b in badges.items():
        (OUT / "badges" / name).write_text(json.dumps(b) + "\n")
    # The raw results, for anyone who wants the numbers behind the Status page.
    for f in (CESM_RUNS, HEALTH):
        if f.exists():
            shutil.copy2(f, OUT / f.name)
    print(f"Badges written to {OUT / 'badges'}")


if __name__ == "__main__":
    main()
