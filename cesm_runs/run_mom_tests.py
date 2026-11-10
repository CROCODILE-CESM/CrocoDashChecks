#!/usr/bin/env python
"""Run MOM_interface's regional smoke tests with CrocoDash-built cases.

MOM_interface's testlist_mom.xml decides *what* is tested. For every regional
(grid=USER_RES) SMS test there, this script keeps only the compset and the
test options (_D, _Ld2, ...), builds that compset with CrocoDash on our own
domain (config.yaml), runs it, and records each phase in a CIME TestStatus
file, so CIME's own cs.status reads the results.

Testmods are not used: the case comes from CrocoDash instead. ERS and other
multi-run test types are skipped; CESM's own create_test covers those with the
Panama testmods.

Usage (on a Derecho compute node, see run_mom_tests.pbs):
    python run_mom_tests.py --cesmroot ~/CESM --test-root ~/scratch/croc_tests
"""

import argparse
import copy
import datetime
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

STOP_OPTIONS = {"Ln": "nsteps", "Lh": "nhours", "Ld": "ndays", "Lm": "nmonths", "Ly": "nyears"}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--cesmroot", required=True, type=Path)
    p.add_argument("--test-root", required=True, type=Path)
    p.add_argument("--testlist", type=Path, help="default: MOM_interface testlist_mom.xml in cesmroot")
    p.add_argument("--config", type=Path, default=HERE / "config.yaml")
    p.add_argument("--test-id", default=datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    p.add_argument("--machine", default="derecho")
    p.add_argument("--compiler", default="intel")
    p.add_argument("--project", default="NCGD0011")
    p.add_argument("--only", nargs="*", default=[], help="keep tests whose name contains any of these")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--ntasks", type=int, default=4,
                   help="MPI tasks per test unless the test sets _P<n>; keep parallel*ntasks <= cores")
    p.add_argument("--data-ntasks", type=int,
                   help="MPI tasks for the data atmosphere, data runoff and mediator (default: --ntasks)")
    p.add_argument("--dry-run", action="store_true", help="list the tests and exit")
    p.add_argument("--badge-dir", type=Path,
                   help="also write a shields.io endpoint badge (JSON) per test here")
    return p.parse_args()


def select_tests(args):
    """Regional SMS tests for this machine/compiler, as (testname, compset, opts, options)."""
    testlist = args.testlist or (
        args.cesmroot / "components/mom/cime_config/testdefs/testlist_mom.xml"
    )
    seen, tests = set(), []
    for t in Testlist(str(testlist)).get_tests(machine=args.machine, compiler=args.compiler):
        testcase, caseopts, grid, compset, *_ = parse_test_name(t["testname"] + "." + t["grid"] + "." + t["compset"])
        if grid != "USER_RES" or testcase != "SMS":
            continue
        name = ".".join([t["testname"], grid, compset, f"{args.machine}_{args.compiler}", "crocodash"])
        if name in seen or (args.only and not any(s in name for s in args.only)):
            continue
        seen.add(name)
        tests.append((name, compset, caseopts or [], t.get("options", {})))
    return tests


def compset_longname(cesmroot, alias):
    for f in (cesmroot / "components").glob("*/cime_config/config_compsets.xml"):
        for node in ET.parse(f).getroot().iter("compset"):
            if node.findtext("alias") == alias:
                return node.findtext("lname")
    return alias  # already a longname


def crocodash_config(cfg, args, compset, testdir):
    """config.yaml + this test's compset/paths, forcings filtered to its components."""
    lname = compset_longname(args.cesmroot, compset)
    out = {k: copy.deepcopy(cfg[k]) for k in ("grid", "topo", "vgrid")}
    out["case"] = {
        **cfg.get("case", {}),
        "cesmroot": str(args.cesmroot),
        "caseroot": str(testdir / testdir.name),
        # Not under testdir: MOM6 holds INPUTDIR in 128 characters and silently
        # drops the slash it appends, so the long test names broke every path.
        "inputdir": str(args.test_root / "inputdir" / f"{compset}.{args.test_id}"),
        "compset": compset,
        "machine": args.machine,
        "project": args.project,
    }
    forcings = {}
    for key, kwargs in cfg["forcings"].items():
        if key == "common" or all(part in lname for part in key.split("+")):
            forcings.update(kwargs)
    out["forcings"] = forcings
    return out


def xmlchanges(caseopts, options, ntasks, data_ntasks=None):
    changes = []
    for opt in caseopts:
        if opt == "D":
            changes.append("DEBUG=TRUE")
        elif opt[:2] in STOP_OPTIONS:
            changes.append(f"STOP_OPTION={STOP_OPTIONS[opt[:2]]},STOP_N={opt[2:]}")
        elif opt.startswith("P") and opt[1:].isdigit():
            ntasks = int(opt[1:])
        else:
            raise ValueError(f"unsupported test option _{opt}")
    # The tiny ocean, ice and wave grids only decompose onto a few tasks, but
    # DATM and DROF read global JRA and GLOFAS data: on those few tasks their
    # initialization alone outlasted an hour. So they and the mediator can get
    # more, all from ROOTPE 0.
    data_ntasks = max(data_ntasks or ntasks, ntasks)
    changes.append(f"NTASKS={ntasks},ROOTPE=0")
    changes.append(f"NTASKS_ATM={data_ntasks},NTASKS_ROF={data_ntasks},NTASKS_CPL={data_ntasks}")
    # Derecho's default launcher (mpibind) takes every core in the PBS job,
    # which collides when several tests run at once, so launch exactly the
    # ranks the case needs.
    changes.append(f"MPI_RUN_COMMAND=mpiexec -n {data_ntasks} --cpu-bind none")
    if "wallclock" in options:
        changes.append(f"JOB_WALLCLOCK_TIME={options['wallclock']}")
    return changes


def run(cmd, log, cwd=None):
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n")
        f.flush()
        return subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode == 0


def run_succeeded(caseroot):
    # case.run only logs "success" after CIME's own check of the coupler log
    # for its termination text, so CaseStatus is enough.
    status = caseroot / "CaseStatus"
    return status.exists() and "case.run success" in status.read_text()


def write_badge(testdir, name, badge_dir):
    """shields.io endpoint JSON: passing, or the first phase that failed."""
    ts_file = testdir / "TestStatus"
    lines = ts_file.read_text().splitlines() if ts_file.exists() else []
    statuses = [line.split()[:3] for line in lines if len(line.split()) >= 3]
    failed = [phase for status, _, phase in statuses if status == TEST_FAIL_STATUS]
    passed = any(phase == RUN_PHASE and status == TEST_PASS_STATUS for status, _, phase in statuses)
    message = "passing" if passed else f"failing: {failed[0]}" if failed else "incomplete"
    # Keyed without machine/compiler/test id, so each run overwrites last run's badge.
    testname, grid, compset, *_ = name.split(".")
    badge = {
        "schemaVersion": 1,
        "label": f"{testname} {compset}",
        "message": f"{message} ({datetime.date.today()})",
        "color": "brightgreen" if passed else "red",
    }
    badge_dir.mkdir(parents=True, exist_ok=True)
    (badge_dir / f"{testname}.{compset}.json").write_text(json.dumps(badge) + "\n")


def run_test(test, cfg, args):
    name, compset, caseopts, options = test
    testdir = args.test_root / f"{name}.{args.test_id}"
    # The case name sets the CIME build/run dir, so it must be unique per test.
    caseroot = testdir / testdir.name
    testdir.mkdir(parents=True)
    # crocodash create needs the inputdir's parent to exist already.
    (args.test_root / "inputdir").mkdir(exist_ok=True)
    log = testdir / "croc_test.log"

    def phase(ts, phase_name, ok, comment=""):
        ts.set_status(phase_name, TEST_PASS_STATUS if ok else TEST_FAIL_STATUS,
                      comments="" if ok else (comment or f"see {log}"))
        return ok

    with TestStatus(test_dir=str(testdir), test_name=name) as ts:
        config_file = testdir / "crocodash_config.yaml"
        config_file.write_text(yaml.safe_dump(crocodash_config(cfg, args, compset, testdir)))
        if not phase(ts, CREATE_NEWCASE_PHASE,
                     run(["crocodash", "create", "--config", config_file, "--override"], log)):
            return
        try:
            changes = xmlchanges(caseopts, options, args.ntasks, args.data_ntasks)
        except ValueError as e:
            phase(ts, XML_PHASE, False, str(e))
            return
        if not phase(ts, XML_PHASE, all(run(["./xmlchange", c], log, caseroot) for c in changes)):
            return
        # crocodash create already ran case.setup, so redo it with the new PE layout.
        if not phase(ts, SETUP_PHASE, run(["./case.setup", "--reset"], log, caseroot)):
            return
        built = run(["./case.build"], log, caseroot)
        # CIME won't record a phase after a failed one, so stop at SHAREDLIB_BUILD.
        if not (phase(ts, SHAREDLIB_BUILD_PHASE, built) and phase(ts, MODEL_BUILD_PHASE, built)):
            return
        submitted = run(["./case.submit", "--no-batch"], log, caseroot)
        if not phase(ts, SUBMIT_PHASE, submitted):
            return
        phase(ts, RUN_PHASE, run_succeeded(caseroot), f"see {caseroot}/CaseStatus")


def main():
    args = parse_args()
    args.cesmroot = args.cesmroot.expanduser().resolve()
    args.test_root = args.test_root.expanduser().resolve()
    sys.path.insert(0, str(args.cesmroot / "cime"))
    # CIME is only importable once cesmroot is known.
    global Testlist, parse_test_name, TestStatus, create_cs_status
    global CREATE_NEWCASE_PHASE, XML_PHASE, SETUP_PHASE, SHAREDLIB_BUILD_PHASE
    global MODEL_BUILD_PHASE, SUBMIT_PHASE, RUN_PHASE, TEST_PASS_STATUS, TEST_FAIL_STATUS
    from CIME.XML.testlist import Testlist
    from CIME.utils import parse_test_name
    from CIME.cs_status_creator import create_cs_status
    from CIME.test_status import (
        TestStatus, CREATE_NEWCASE_PHASE, XML_PHASE, SETUP_PHASE, SHAREDLIB_BUILD_PHASE,
        MODEL_BUILD_PHASE, SUBMIT_PHASE, RUN_PHASE, TEST_PASS_STATUS, TEST_FAIL_STATUS,
    )

    tests = select_tests(args)
    for name, *_ in tests:
        print(name)
    if args.dry_run or not tests:
        return

    cfg = yaml.safe_load(args.config.read_text())
    args.test_root.mkdir(parents=True, exist_ok=True)
    create_cs_status(test_root=str(args.test_root), test_id=args.test_id)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        list(pool.map(lambda t: run_test(t, cfg, args), tests))
    subprocess.run([str(args.test_root / f"cs.status.{args.test_id}")])
    if args.badge_dir:
        for name, *_ in tests:
            write_badge(args.test_root / f"{name}.{args.test_id}", name, args.badge_dir)


if __name__ == "__main__":
    main()
