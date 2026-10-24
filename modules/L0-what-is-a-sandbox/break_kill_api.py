#!/usr/bin/env python3
"""Break (L0): kill the sandbox API while 5 sandboxes exist, then count what is left.

Usage: python3 break_kill_api.py          (needs nothing else listening on localhost:8080)

1. Build and start the API; create 5 sandboxes; keep their IDs (as a caller would).
2. Kill the API abruptly (SIGKILL: no chance to clean up, like a crash).
3. Count containers with label sandbox-lab in Docker, and their state.
4. Start the API again; ask GET /sandboxes.
5. Send DELETE /sandboxes/<id> for one of the 5; report the status code.
6. Count containers in Docker again. Leftovers are NOT removed: they are the result.
   Clean up afterwards: docker rm -f $(docker ps -aq --filter label=sandbox-lab)

Appends one row per run to ../../results/l0-kill-api-orphans.csv.
"""
import csv
import json
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API = "http://localhost:8080"
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "l0-kill-api-orphans.csv"


def request(method, path):
    req = urllib.request.Request(API + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def api_up():
    try:
        request("GET", "/sandboxes")
        return True
    except OSError:
        return False


def start_api():
    log = open(REPO / "bin" / "sandbox-api.log", "a")
    proc = subprocess.Popen([str(REPO / "bin" / "sandbox-api")], cwd=REPO, stdout=log, stderr=log)
    for _ in range(50):
        if api_up():
            return proc
        time.sleep(0.1)
    sys.exit("sandbox-api did not start; see bin/sandbox-api.log")


def docker_view():
    out = subprocess.run(["docker", "ps", "-a", "--filter", "label=sandbox-lab",
                          "--format", '{{.Label "sandbox-lab.id"}} {{.State}} {{.Names}}'],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [line.split() for line in out if line.strip()]


def main():
    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    before = docker_view()
    if before:
        sys.exit(f"{len(before)} sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)

    print("1. start the API, create 5 sandboxes")
    api = start_api()
    ids = []
    for _ in range(5):
        status, sb = request("POST", "/sandboxes")
        ids.append(sb["id"])
        print(f"   created {sb['id']}  ({status}, {sb['create_ms']} ms)")

    print(f"\n2. kill the API abruptly (SIGKILL, pid {api.pid})")
    api.kill()
    api.wait()
    print(f"   API answering? {api_up()}")

    print("\n3. what Docker has (label sandbox-lab):")
    after_kill = docker_view()
    for sid, state, name in after_kill:
        print(f"   {sid}  {state:8} {name}")
    running = sum(1 for _, state, _ in after_kill if state == "running")
    print(f"   -> {len(after_kill)} containers, {running} running")

    print("\n4. restart the API, GET /sandboxes")
    api = start_api()
    status, listed = request("GET", "/sandboxes")
    print(f"   {status}: {len(listed)} sandboxes listed")

    print(f"\n5. DELETE /sandboxes/{ids[0]}  (an ID the caller kept from step 1)")
    del_status, body = request("DELETE", f"/sandboxes/{ids[0]}")
    print(f"   {del_status} {json.dumps(body) if body else ''}")
    api.terminate()
    api.wait()

    final = docker_view()
    print(f"\n6. containers still in Docker: {len(final)}  "
          f"({sum(1 for _, s, _ in final if s == 'running')} running)")
    print("   clean up: docker rm -f $(docker ps -aq --filter label=sandbox-lab)")

    new_file = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "machine", "created", "left_after_kill", "running_after_kill",
                        "listed_after_restart", "delete_status", "left_at_end"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), f"{platform.machine()} macOS {platform.mac_ver()[0]}",
                    len(ids), len(after_kill), running, len(listed), del_status, len(final)])


if __name__ == "__main__":
    main()
