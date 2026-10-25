#!/usr/bin/env python3
"""Split smolvm branch's full trip into its three commands and time each one.

Usage: python3 measure_branch_steps.py [runs]     (default 10)

Per run: `machine branch --from l0b-src` · `machine exec <child> -- true` · `machine delete -f <child>`,
each timed on its own. Control: `machine exec l0b-src -- true` (an exec with no branch at all).
Starts the `--branchable` alpine source `l0b-src` if needed and deletes it at the end.
One warm-up run (not counted). Raw numbers: ../../results/l0-branch-steps.csv
"""
import csv
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = "l0b-src"
OUT = REPO / "results" / "l0-branch-steps.csv"
SETTLE_S = 10
TIMEOUT_S = 90   # a hung command fails loudly instead of waiting forever
STEPS = ["branch", "exec_child", "delete", "exec_source_control"]


def timed(*cmd):
    start = time.perf_counter()
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        sys.exit(f"{' '.join(cmd)} did not finish in {TIMEOUT_S} s (hang)")
    if r.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed (exit {r.returncode}):\n{r.stderr[-800:]}")
    return (time.perf_counter() - start) * 1000


def ensure_source():
    ls = subprocess.run(["smolvm", "machine", "ls"], capture_output=True, text=True).stdout
    line = next((l for l in ls.splitlines() if l.split()[:1] == [SOURCE]), "")
    if "running" in line:
        return
    if not line:
        timed("smolvm", "machine", "create", "--name", SOURCE, "--image", "alpine", "--", "sleep", "86400")
    timed("smolvm", "machine", "start", "--name", SOURCE, "--branchable")
    # Let the fresh source settle before branching: on 2026-10-25 a branch taken ~1 s after start hung
    # (the child's setup script timed out every 2 min and `branch` never returned).
    timed("smolvm", "machine", "exec", "--name", SOURCE, "--", "true")
    time.sleep(SETTLE_S)


def one(i):
    child = f"l0b-step-{i}"
    return {
        "branch": timed("smolvm", "machine", "branch", "--from", SOURCE, "--name", child),
        "exec_child": timed("smolvm", "machine", "exec", "--name", child, "--", "true"),
        "delete": timed("smolvm", "machine", "delete", "-f", "--name", child),
        "exec_source_control": timed("smolvm", "machine", "exec", "--name", SOURCE, "--", "true"),
    }


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    ensure_source()
    stamp = datetime.now().isoformat(timespec="seconds")
    machine = f"{platform.machine()} macOS {platform.mac_ver()[0]}"
    try:
        w = one(0)
        print("warm-up (not counted): " + "  ".join(f"{k} {v:.0f}" for k, v in w.items()))
        results = {s: [] for s in STEPS}
        new_file = not OUT.exists()
        with OUT.open("a", newline="") as f:
            wr = csv.writer(f)
            if new_file:
                wr.writerow(["timestamp", "machine", "run"] + [f"{s}_ms" for s in STEPS])
            for i in range(1, runs + 1):
                r = one(i)
                for s in STEPS:
                    results[s].append(r[s])
                wr.writerow([stamp, machine, i] + [f"{r[s]:.1f}" for s in STEPS])
                print(f"  run {i:2}: " + "  ".join(f"{s} {r[s]:4.0f}" for s in STEPS))
    finally:
        subprocess.run(["smolvm", "machine", "delete", "-f", "--name", SOURCE], capture_output=True)
    print("\nstep                  median ms")
    for s in STEPS:
        print(f"{s:21} {statistics.median(results[s]):6.0f}")
    total = sum(statistics.median(results[s]) for s in STEPS[:3])
    print(f"{'branch+exec+delete':21} {total:6.0f}   (sum of medians)")
    left = [l.split()[0] for l in subprocess.run(["smolvm", "machine", "ls"], capture_output=True,
                                                 text=True).stdout.splitlines() if l.startswith("l0b-")]
    print(f"smolvm machines left from this script: {len(left)} {left}")


if __name__ == "__main__":
    main()
