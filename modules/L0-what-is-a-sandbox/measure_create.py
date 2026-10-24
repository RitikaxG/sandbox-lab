#!/usr/bin/env python3
"""Time `POST /sandboxes` on the lab's sandbox API (L0, decision 001: Docker SDK).

Usage: python3 measure_create.py [runs]        (default 50)

Starts the API (building it first) unless one already answers on localhost:8080.
One warm-up create (not counted), then N timed creates; each sandbox is deleted
right after its create, outside the timing. For every run it records the time seen
by the client and `create_ms`, the time the API spent in Docker create + start, so
the difference is the API's own overhead (HTTP, JSON, bookkeeping).

p50 = median; p99 by nearest rank (with 50 runs, the slowest run).
Raw numbers: ../../results/l0-create-latency.csv
"""
import csv
import json
import math
import platform
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

API = "http://localhost:8080"
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "l0-create-latency.csv"


def request(method, path):
    req = urllib.request.Request(API + path, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def api_up():
    try:
        request("GET", "/sandboxes")
        return True
    except OSError:
        return False


def start_api():
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    log = open(REPO / "bin" / "sandbox-api.log", "a")
    proc = subprocess.Popen([str(REPO / "bin" / "sandbox-api")], cwd=REPO, stdout=log, stderr=log)
    for _ in range(50):
        if api_up():
            return proc
        time.sleep(0.1)
    sys.exit("sandbox-api did not start; see bin/sandbox-api.log")


def create_once():
    start = time.perf_counter()
    sb = request("POST", "/sandboxes")
    client_ms = (time.perf_counter() - start) * 1000
    request("DELETE", f"/sandboxes/{sb['id']}")
    return client_ms, sb["create_ms"]


def pct(sorted_vals, p):
    return sorted_vals[max(0, math.ceil(p / 100 * len(sorted_vals)) - 1)]


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    proc = None if api_up() else start_api()
    try:
        stamp = datetime.now().isoformat(timespec="seconds")
        machine = f"{platform.machine()} macOS {platform.mac_ver()[0]}"
        print(f"warm-up: {create_once()[0]:.0f} ms (not counted)")
        clients, servers = [], []
        new_file = not OUT.exists()
        with OUT.open("a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["timestamp", "machine", "run", "client_ms", "api_create_ms"])
            for i in range(1, runs + 1):
                c, s = create_once()
                clients.append(c)
                servers.append(s)
                w.writerow([stamp, machine, i, f"{c:.1f}", s])
                print(f"  run {i:2}: {c:5.0f} ms   (Docker create+start {s} ms)")
        cs = sorted(clients)
        print(f"\nclient: min {cs[0]:.0f} · p50 {statistics.median(cs):.0f} · p99 {pct(cs, 99):.0f} ms"
              f"   p99/p50 = {pct(cs, 99) / statistics.median(cs):.2f}")
        print(f"Docker create+start inside the API: p50 {statistics.median(servers):.0f} ms")
        print(f"API's own overhead at p50: {statistics.median(c - s for c, s in zip(clients, servers)):.1f} ms")
        left = subprocess.run(["docker", "ps", "-aq", "--filter", "label=sandbox-lab"],
                              capture_output=True, text=True).stdout.split()
        print(f"containers left with label sandbox-lab: {len(left)}")
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
