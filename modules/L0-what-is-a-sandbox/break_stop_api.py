#!/usr/bin/env python3
"""Break 1, variation (L0 depth day, 2026-10-29): stop the API *gently* (SIGTERM) instead of SIGKILL, with short-lived
sandboxes, and watch what is left before and after their command ends.

Usage: python3 break_stop_api.py [--signal TERM|KILL] [--sleep 30]   (needs nothing else on localhost:8080)

Checks two claims in postmortem 001:
  - "A gentler stop than SIGKILL would most likely leave the same 5 orphans" (INFERENCE)
  - "when sleep ends, the container stops but is not removed" (INFERENCE from the code; not waited for)

1. Build and start the API; create 5 sandboxes whose command is `sleep <N>` (default 30 s).
2. Stop the API with the chosen signal (default SIGTERM); report how it exited.
3. Count containers with label sandbox-lab, and their state.
4. Wait until every `sleep` has ended (N + 5 s); count again, with each container's state and exit code.
Leftovers are NOT removed: they are the result. Clean up: docker rm -f $(docker ps -aq --filter label=sandbox-lab)

Appends one row per run to ../../results/l0-stop-api-orphans.csv.
"""
import argparse
import csv
import json
import platform
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from break_kill_api import API, REPO, api_up, start_api

OUT = REPO / "results" / "l0-stop-api-orphans.csv"


def create(seconds):
    body = json.dumps({"image": "alpine", "cmd": ["sleep", str(seconds)]}).encode()
    req = urllib.request.Request(API + "/sandboxes", method="POST", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.loads(resp.read())


def docker_view():
    ids = subprocess.run(["docker", "ps", "-aq", "--filter", "label=sandbox-lab"],
                         capture_output=True, text=True, check=True).stdout.split()
    if not ids:
        return []
    out = subprocess.run(["docker", "inspect", "--format",
                          '{{index .Config.Labels "sandbox-lab.id"}} {{.State.Status}} {{.State.ExitCode}}', *ids],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [line.split() for line in out if line.strip()]


def show(rows):
    for sid, state, code in rows:
        print(f"   {sid}  {state:8} exit code {code}")
    running = sum(1 for _, state, _ in rows if state == "running")
    print(f"   -> {len(rows)} containers, {running} running")
    return running


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--signal", default="TERM", choices=["TERM", "KILL"])
    p.add_argument("--sleep", type=int, default=30)
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)

    print(f"1. start the API, create 5 sandboxes running `sleep {a.sleep}`")
    api = start_api()
    for _ in range(5):
        status, sb = create(a.sleep)
        print(f"   created {sb['id']}  ({status}, {sb['create_ms']} ms)")
    created_at = time.monotonic()

    print(f"\n2. stop the API with SIG{a.signal} (pid {api.pid})")
    api.send_signal(getattr(signal, "SIG" + a.signal))
    api.wait()
    print(f"   API exit: {api.returncode} (negative = killed by that signal number)   answering? {api_up()}")

    print("\n3. right after the stop, what Docker has (label sandbox-lab):")
    rows_stop = docker_view()
    running_stop = show(rows_stop)

    wait = max(0.0, a.sleep + 5 - (time.monotonic() - created_at))
    print(f"\n4. wait {wait:.0f} s until every `sleep {a.sleep}` has ended, then look again:")
    time.sleep(wait)
    rows_end = docker_view()
    running_end = show(rows_end)
    print("   clean up: docker rm -f $(docker ps -aq --filter label=sandbox-lab)")

    new_file = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "machine", "signal", "sleep_s", "created", "api_exit",
                        "left_after_stop", "running_after_stop", "left_after_sleep", "running_after_sleep"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), f"{platform.machine()} macOS {platform.mac_ver()[0]}",
                    "SIG" + a.signal, a.sleep, 5, api.returncode, len(rows_stop), running_stop,
                    len(rows_end), running_end])


if __name__ == "__main__":
    main()
