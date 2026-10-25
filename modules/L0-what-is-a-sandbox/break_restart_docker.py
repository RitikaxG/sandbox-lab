#!/usr/bin/env python3
"""Break (L0, second run): restart Docker, not the API, while 5 sandboxes exist.

The reverse of break_kill_api.py: the API stays up with its in-memory list; Docker restarts underneath it.

Usage: python3 break_restart_docker.py      (needs nothing on localhost:8080, no sandbox-lab containers,
                                              and no other running containers: a Docker restart stops them all)

1. Build and start the API; create 5 sandboxes.
2. Restart Docker Desktop (`docker desktop restart`); wait until Docker answers again; time it.
3. What Docker has (label sandbox-lab), with each container's state.
4. What the API says: GET /sandboxes (its states).
5. Ask the API to exec `true` in one sandbox; report status and body.
6. Ask the API to DELETE another; report status.
7. Docker at the end. Leftovers are NOT removed: they are the result.
   Clean up afterwards: docker rm -f $(docker ps -aq --filter label=sandbox-lab)

Appends one row per run to ../../results/l0-restart-docker.csv.
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
OUT = REPO / "results" / "l0-restart-docker.csv"


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(API + path, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def api_up():
    try:
        request("GET", "/sandboxes")
        return True
    except OSError:
        return False


def docker_up():
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def docker_view():
    out = subprocess.run(["docker", "ps", "-a", "--filter", "label=sandbox-lab",
                          "--format", '{{.Label "sandbox-lab.id"}}|{{.State}}|{{.Status}}'],
                         capture_output=True, text=True, check=True).stdout
    return [line.split("|") for line in out.splitlines() if line.strip()]


def main():
    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    others = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split()
    if others:
        sys.exit(f"{len(others)} other containers are running; a Docker restart would stop them. Stop them first.")

    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    log = open(REPO / "bin" / "sandbox-api.log", "a")
    api = subprocess.Popen([str(REPO / "bin" / "sandbox-api")], cwd=REPO, stdout=log, stderr=log)
    for _ in range(50):
        if api_up():
            break
        time.sleep(0.1)
    try:
        print("1. create 5 sandboxes through the API")
        ids = []
        for _ in range(5):
            status, sb = request("POST", "/sandboxes")
            ids.append(sb["id"])
            print(f"   created {sb['id']}  ({status}, {sb['state']})")

        print("\n2. restart Docker Desktop (the API keeps running)")
        start = time.perf_counter()
        subprocess.run(["docker", "desktop", "restart"], capture_output=True)
        while not docker_up():
            time.sleep(1)
        restart_s = time.perf_counter() - start
        print(f"   Docker answering again after {restart_s:.0f} s")

        print("\n3. what Docker has (label sandbox-lab):")
        view = docker_view()
        for sid, state, status in view:
            print(f"   {sid}  {state:8} {status}")
        running = sum(1 for _, state, _ in view if state == "running")
        print(f"   -> {len(view)} containers, {running} running")

        print("\n4. what the API says: GET /sandboxes")
        status, listed = request("GET", "/sandboxes")
        for sb in listed:
            print(f"   {sb['id']}  {sb['state']}")
        print(f"   -> {status}: {len(listed)} sandboxes listed")

        print(f"\n5. POST /sandboxes/{ids[0]}/exec  {{\"cmd\": [\"true\"]}}")
        exec_status, body = request("POST", f"/sandboxes/{ids[0]}/exec", {"cmd": ["true"]})
        print(f"   {exec_status} {json.dumps(body)}")

        print(f"\n6. DELETE /sandboxes/{ids[1]}")
        del_status, body = request("DELETE", f"/sandboxes/{ids[1]}")
        print(f"   {del_status} {json.dumps(body) if body else ''}")

        final = docker_view()
        print(f"\n7. containers still in Docker: {len(final)}  "
              f"({sum(1 for _, s, _ in final if s == 'running')} running)")
        print("   clean up: docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    finally:
        api.terminate()
        api.wait()

    new_file = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "machine", "created", "docker_restart_s", "in_docker_after", "running_after",
                        "api_listed", "exec_status", "delete_status", "in_docker_at_end"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), f"{platform.machine()} macOS {platform.mac_ver()[0]}",
                    len(ids), f"{restart_s:.0f}", len(view), running, len(listed), exec_status, del_status, len(final)])


if __name__ == "__main__":
    main()
