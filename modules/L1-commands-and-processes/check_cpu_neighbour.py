#!/usr/bin/env python3
"""CPU neighbour check (2026-11-05, #53): sandbox A burns CPU, with far fewer processes than its pids.max, so G1 never
comes into play. Does sandbox B, on the same 8 CPUs, notice? And what does A's own `echo hi` do? #54, #55 with the API's
2-CPU cap (G8); --no-cap lifts it from outside, by writing `max` to A's cgroup file `cpu.max` (`docker update --cpus 0` changes nothing), as #53
ran.

Usage: python3 check_cpu_neighbour.py [--runs 10] [--burners 64] [--no-cap]   (needs nothing else on localhost:8080
       and no sandbox-lab containers)

1. Build and start the API; create A and B.
2. Control: `echo hi` in B, then in A, through the API, --runs times each.
3. Start --burners endless loops in A (one exec, timeout_s 60, in the background of this script); wait 2 s.
4. While they run: the same `echo hi` in B, then in A; A's CPU from `docker stats`; `docker ps` time.
5. Delete A (with the loops still running), then B, through the API.

Appends one row per run to ../../results/l1-cpu-cap.csv. (#53's three rows, before G8: l1-cpu-neighbour.csv.)
"""
import argparse
import csv
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime

from break_disconnect import REPO, api_up, docker_view, start_api
from break_forkbomb import call, timed
from check_neighbour import echoes

OUT = REPO / "results" / "l1-cpu-cap.csv"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--burners", type=int, default=64)
    p.add_argument("--no-cap", action="store_true", help="lift A's CPU cap first")
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    row = dict(date=datetime.now().isoformat(timespec="seconds"), runs=a.runs, burners=a.burners,
               capped=not a.no_cap)
    try:
        _, sa, _ = call("POST", "/sandboxes")
        _, sb, _ = call("POST", "/sandboxes")
        path = f"/sys/fs/cgroup/docker/{sa['runtime_id']}/cpu.max"
        write = f"echo max > {path}; " if a.no_cap else ""
        nano = subprocess.run(["docker", "run", "--rm", "--privileged", "--cgroupns=host", "alpine", "sh", "-c",
                               f"{write}cat {path}"], check=True, capture_output=True, text=True).stdout.strip()
        if a.no_cap != nano.startswith("max"):
            sys.exit(f"A's cpu.max is {nano}, not what --no-cap={a.no_cap} needs")
        print(f"A {sa['id']}, B {sb['id']}, A's cpu.max {nano}")
        row.update(a_cpu_max=nano)

        before, good, _ = echoes(sb["id"], a.runs)
        row.update(control_p50_ms=statistics.median(before), control_max_ms=max(before), control_ok=good)
        print(f"control, B: echo hi x{a.runs}: {good} ok, median {statistics.median(before)} ms, times {before}")
        a_before, good, _ = echoes(sa["id"], a.runs)
        row.update(a_control_p50_ms=statistics.median(a_before), a_control_ok=good)
        print(f"control, A: echo hi x{a.runs}: {good} ok, median {statistics.median(a_before)} ms, times {a_before}")

        burn = (f"i=0; while [ $i -lt {a.burners} ]; do (while :; do :; done) & i=$((i+1)); done; wait")
        threading.Thread(target=call, daemon=True, args=("POST", f"/sandboxes/{sa['id']}/exec",
                         {"cmd": ["sh", "-c", burn], "timeout_s": 60})).start()
        time.sleep(2)

        during, good, last = echoes(sb["id"], a.runs)
        row.update(during_p50_ms=statistics.median(during), during_max_ms=max(during), during_ok=good,
                   ratio=round(statistics.median(during) / statistics.median(before), 2))
        print(f"A burning, B: echo hi x{a.runs}: {good} ok, median {statistics.median(during)} ms, times {during}")
        if good < a.runs:
            print(f"last result: {last}")

        a_during, good, last = echoes(sa["id"], a.runs)
        row.update(a_during_p50_ms=statistics.median(a_during), a_during_max_ms=max(a_during), a_during_ok=good,
                   a_ratio=round(statistics.median(a_during) / statistics.median(a_before), 2))
        print(f"A burning, A: echo hi x{a.runs}: {good} ok, median {statistics.median(a_during)} ms, times {a_during}")
        if good < a.runs:
            print(f"last result: {str(last)[:300]}")

        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.PIDs}}",
                            sa["runtime_id"]], capture_output=True, text=True, timeout=60)
        row.update(a_stats=r.stdout.strip())
        print(f"docker stats, A: {r.stdout.strip()}")
        code, ms = timed(["docker", "ps", "-q"])
        row.update(docker_ps_ms=ms if code == 0 else f"{code} after {ms}")
        print(f"docker ps -> {code} in {ms} ms")

        status, _, ms = call("DELETE", f"/sandboxes/{sa['id']}")
        row.update(delete_a_ms=ms)
        print(f"delete A -> {status} in {ms} ms")
        status, _, ms = call("DELETE", f"/sandboxes/{sb['id']}")
        print(f"delete B -> {status} in {ms} ms")
    finally:
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "runs", "burners", "capped", "a_cpu_max", "control_p50_ms",
                                          "control_max_ms", "control_ok", "a_control_p50_ms", "a_control_ok",
                                          "during_p50_ms", "during_max_ms", "during_ok", "ratio", "a_during_p50_ms",
                                          "a_during_max_ms", "a_during_ok", "a_ratio", "a_stats", "docker_ps_ms",
                                          "delete_a_ms"])
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\n1 row appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
