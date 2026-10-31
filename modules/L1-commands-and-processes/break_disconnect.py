#!/usr/bin/env python3
"""Break 2 (L1 day 2, 2026-10-31): the client disconnects mid-stream. Does the API notice, stop the command, and
leave nothing behind?

Usage: python3 break_disconnect.py [--runs 3] [--ticks 4] [--client-signal KILL|INT] [--ignore-term]
       (needs nothing else on localhost:8080 and no sandbox-lab containers)

1. Build and start the API; create one sandbox (alpine, `tini` as PID 1).
2. Each run: curl starts a streaming exec of a ticker (`echo tick N` every 0.5 s, forever). After curl has printed
   --ticks lines, the script kills curl (SIGKILL by default; INT = Ctrl-C). Nothing else ever stops the ticker:
   no timeout_s is sent.
3. From the API log (bin/sandbox-api.log, millisecond timestamps): when the API noticed (the `exec-run ...
   (disconnect)` line) minus when curl was killed = notice_ms; then exit code, stopped_by, stop_ms and the leak
   count from the API's own `api: exec` line.
4. Independent check, not trusting the API's count: `docker exec <container> ps` after each run.
5. Delete the sandbox through the API and stop the API.

Appends one row per run to ../../results/l1-disconnect.csv.
"""
import argparse
import csv
import json
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "L0-what-is-a-sandbox"))
from break_kill_api import API, REPO, api_up, docker_view, request, start_api  # noqa: E402

LOG = REPO / "bin" / "sandbox-api.log"
OUT = REPO / "results" / "l1-disconnect.csv"
TICKER = 'i=0; while :; do i=$((i+1)); echo "tick $i"; sleep 0.5; done'
STAMP = re.compile(r"^(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\.\d{6}) (.*)$")
API_EXEC = re.compile(r"exit (-?\d+), stopped_by (\w+), stop (\d+) ms, (\d+) leaks")


def log_lines(offset):
    """New API log lines since offset, as (unix time, text)."""
    with open(LOG) as f:
        f.seek(offset)
        out = []
        for line in f.read().splitlines():
            m = STAMP.match(line)
            if m:
                out.append((datetime.strptime(m[1], "%Y/%m/%d %H:%M:%S.%f").timestamp(), m[2]))
        return out


def wait_for_result(offset, sb_id, limit=15):
    """Wait for the API's `api: exec <id>` line; None if it never comes (the API did not stop the command)."""
    deadline = time.time() + limit
    while time.time() < deadline:
        lines = log_lines(offset)
        if any(text.startswith(f"api: exec {sb_id} ") for _, text in lines):
            return lines
        time.sleep(0.1)
    return None


def ps(container):
    return subprocess.run(["docker", "exec", container, "ps", "-o", "pid,ppid,pgid,sid,stat,args"],
                          capture_output=True, text=True).stdout.rstrip()


def one_run(n, sb, a):
    cmd = ["sh", "-c", ('trap "" TERM; ' if a.ignore_term else "") + TICKER]
    body = json.dumps({"cmd": cmd, "stream": True})
    offset = LOG.stat().st_size
    curl = subprocess.Popen(["curl", "-sN", "-X", "POST", f"{API}/sandboxes/{sb['id']}/exec", "-d", body],
                            stdout=subprocess.PIPE, text=True)
    ticks = 0
    while ticks < a.ticks:
        line = curl.stdout.readline()
        if not line:
            sys.exit(f"curl ended before {a.ticks} ticks (exit {curl.wait()})")
        if '"tick ' in line:
            ticks += 1
    t_kill = time.time()
    curl.send_signal(getattr(signal, "SIG" + a.client_signal))
    curl.wait()
    print(f"run {n}: curl killed with SIG{a.client_signal} after {ticks} ticks")

    lines = wait_for_result(offset, sb["id"])
    after = ps(sb["runtime_id"])
    if lines is None:
        print("   no result in the API log after 15 s: the API did not stop the command")
        print("   ps inside the sandbox:\n      " + after.replace("\n", "\n      "))
        return dict(notice_ms="", stopped_by="", exit_code="", stop_ms="", api_leaks="", ps_after=after)

    for ts, text in lines:
        if not text.startswith("docker: processes"):
            print(f"   {1000 * (ts - t_kill):+8.1f} ms  {text}")
    noticed = next((ts for ts, text in lines if "(disconnect)" in text or "(timeout)" in text), None)
    code, stopped_by, stop_ms, leaks = API_EXEC.search(
        next(text for _, text in lines if text.startswith(f"api: exec {sb['id']} "))).groups()
    notice_ms = round(1000 * (noticed - t_kill), 1) if noticed else ""
    print(f"   -> noticed {notice_ms} ms after the kill; exit {code}, stopped_by {stopped_by}, "
          f"stop_ms {stop_ms}, {leaks} leaks")
    print("   ps inside the sandbox:\n      " + after.replace("\n", "\n      "))
    return dict(notice_ms=notice_ms, stopped_by=stopped_by, exit_code=code, stop_ms=stop_ms, api_leaks=leaks,
                ps_after=after)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--ticks", type=int, default=4, help="ticks curl prints before it is killed (0.5 s each)")
    p.add_argument("--client-signal", default="KILL", choices=["KILL", "INT"])
    p.add_argument("--ignore-term", action="store_true", help="the ticker ignores SIGTERM (break 1's trap)")
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    try:
        status, sb = request("POST", "/sandboxes")
        print(f"sandbox {sb['id']} ({status}, container {sb['runtime_id'][:12]})")
        print("ps inside the sandbox before any run:\n   " + ps(sb["runtime_id"]).replace("\n", "\n   "))
        rows = []
        for n in range(1, a.runs + 1):
            r = one_run(n, sb, a)
            rows.append(dict(date=datetime.now().isoformat(timespec="seconds"), run=n,
                             client_signal=a.client_signal, ignore_term=a.ignore_term, ticks=a.ticks, **r))
        request("DELETE", f"/sandboxes/{sb['id']}")
    finally:
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} rows appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
