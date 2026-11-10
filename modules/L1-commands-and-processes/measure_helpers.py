#!/usr/bin/env python3
"""How long does each step of an exec take in a throttled sandbox? (2026-11-05, #57; sets G2's helper deadline.)

Usage: python3 measure_helpers.py [--runs 10] [--burners 64]   (needs nothing else on localhost:8080 and no sandbox-lab
       containers)

1. Build and start the API; create A. `echo hi` x--runs as a control.
2. Start --burners endless loops in A; wait 2 s. The same `echo hi` x--runs.
3. Read each step's time from the API's log. Delete A.

Appends one row per step per phase to ../../results/l1-helper-times.csv.
"""
import argparse
import csv
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime

from break_disconnect import LOG, REPO, api_up, docker_view, log_lines, start_api
from break_forkbomb import call
from check_neighbour import echoes

OUT = REPO / "results" / "l1-helper-times.csv"
STEP = re.compile(r"docker: (exec-create|exec-run|exec-inspect|processes) \S+\s+(\d+) ms")


def steps(offset):
    """{step: [ms, ...]} from the log lines after offset."""
    found = {}
    for _, text in log_lines(offset):
        m = STEP.match(text)
        if m:
            found.setdefault(m[1], []).append(int(m[2]))
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--burners", type=int, default=64)
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    rows, date = [], datetime.now().isoformat(timespec="seconds")
    try:
        _, sa, _ = call("POST", "/sandboxes")
        for phase in ("control", "burning"):
            if phase == "burning":
                burn = f"i=0; while [ $i -lt {a.burners} ]; do (while :; do :; done) & i=$((i+1)); done; wait"
                threading.Thread(target=call, daemon=True, args=("POST", f"/sandboxes/{sa['id']}/exec",
                                 {"cmd": ["sh", "-c", burn], "timeout_s": 120})).start()
                time.sleep(2)
            offset = LOG.stat().st_size
            times, good, _ = echoes(sa["id"], a.runs)
            print(f"{phase}: echo hi x{a.runs}: {good} ok, median {statistics.median(times)} ms, max {max(times)}")
            for step, ms in steps(offset).items():
                print(f"  {step:13} n={len(ms):3} median {statistics.median(ms):7} max {max(ms):6} ms")
                rows.append(dict(date=date, burners=a.burners, phase=phase, step=step, n=len(ms),
                                 median_ms=statistics.median(ms), max_ms=max(ms)))
        call("DELETE", f"/sandboxes/{sa['id']}")
    finally:
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "burners", "phase", "step", "n", "median_ms", "max_ms"])
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} rows appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
