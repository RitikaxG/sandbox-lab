#!/usr/bin/env python3
"""G1 check (2026-11-05, #52): a fork bomb fills sandbox A to its pids.max (1,024, set by the API at create). Does
sandbox B, on the same kernel, notice?

Usage: python3 check_neighbour.py [--runs 10]   (needs nothing else on localhost:8080 and no sandbox-lab containers)

1. Build and start the API; create A and B. Refuse to go on unless both really have PidsLimit 1024: without it the
   bomb stalls Docker for ~12 min (#40).
2. Control: `echo hi` in B through the API, --runs times.
3. exec the bomb in A with timeout_s 3 (same bomb as break 4), and wait until A's process count stops growing.
4. While A is full: the same `echo hi` runs in B, A's CPU from `docker stats`, `docker ps` time, A's count again.
5. Delete both through the API.

Appends one row per run to ../../results/l1-neighbour.csv.
"""
import argparse
import csv
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime

from break_disconnect import REPO, api_up, docker_view, start_api
from break_forkbomb import BOMB, PidWatch, call, timed

OUT = REPO / "results" / "l1-neighbour.csv"
LIMIT = 1024


def pids_limit(cid):
    r = subprocess.run(["docker", "inspect", "-f", "{{.HostConfig.PidsLimit}}", cid], capture_output=True, text=True)
    return r.stdout.strip()


def echoes(sid, runs):
    """(call times in ms, how many gave exit 0 and "hi", last result)"""
    times, good, last = [], 0, None
    for _ in range(runs):
        status, res, ms = call("POST", f"/sandboxes/{sid}/exec", {"cmd": ["echo", "hi"], "timeout_s": 5})
        times.append(ms)
        good += status == 200 and res.get("exit_code") == 0 and res.get("stdout") == "hi\n"
        last = res
    return times, good, last


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=10)
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    row = dict(date=datetime.now().isoformat(timespec="seconds"), runs=a.runs)
    watch = None
    try:
        _, sa, _ = call("POST", "/sandboxes")
        _, sb, _ = call("POST", "/sandboxes")
        for s in (sa, sb):
            got = pids_limit(s["runtime_id"])
            if got != str(LIMIT):
                sys.exit(f"sandbox {s['id']} has PidsLimit {got}, not {LIMIT}: not running the bomb")
        print(f"A {sa['id']}, B {sb['id']}: both PidsLimit {LIMIT}")

        before, good, _ = echoes(sb["id"], a.runs)
        row.update(control_p50_ms=statistics.median(before), control_max_ms=max(before), control_ok=good)
        print(f"control, B: echo hi x{a.runs}: {good} ok, median {statistics.median(before)} ms, times {before}")

        watch = PidWatch(sa["runtime_id"])
        status, res, ms = call("POST", f"/sandboxes/{sa['id']}/exec", {"cmd": ["sh", "-c", BOMB], "timeout_s": 3})
        print(f"bomb in A -> {status} in {ms} ms: " + (f"exit {res['exit_code']}, stopped_by {res['stopped_by']}, "
              f"{len(res['leaks'])} leaks" if status == 200 else str(res)))
        row.update(bomb_status=status, bomb_ms=ms)
        for _ in range(50):
            if (watch.now() or 0) >= LIMIT - 30:
                break
            time.sleep(0.2)
        row.update(a_pids_before=watch.now())
        print(f"A's processes: {watch.now()}")

        during, good, last = echoes(sb["id"], a.runs)
        row.update(during_p50_ms=statistics.median(during), during_max_ms=max(during), during_ok=good,
                   a_pids_after=watch.now(), ratio=round(statistics.median(during) / statistics.median(before), 2))
        print(f"A full, B: echo hi x{a.runs}: {good} ok, median {statistics.median(during)} ms, times {during}")
        if good < a.runs:
            print(f"last result: {last}")
        print(f"A's processes after: {watch.now()}")

        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.PIDs}}",
                            sa["runtime_id"]], capture_output=True, text=True, timeout=60)
        row.update(a_stats=r.stdout.strip())
        print(f"docker stats, A: {r.stdout.strip()}")
        code, ms = timed(["docker", "ps", "-q"])
        row.update(docker_ps_ms=ms if code == 0 else f"{code} after {ms}")
        print(f"docker ps -> {code} in {ms} ms")

        for s in (sa, sb):
            status, _, ms = call("DELETE", f"/sandboxes/{s['id']}")
            print(f"delete {s['id']} -> {status} in {ms} ms")
    finally:
        if watch:
            watch.stop()
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "runs", "control_p50_ms", "control_max_ms", "control_ok", "bomb_status",
                                          "bomb_ms", "a_pids_before", "during_p50_ms", "during_max_ms", "during_ok",
                                          "a_pids_after", "ratio", "a_stats", "docker_ps_ms"])
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\n1 row appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
