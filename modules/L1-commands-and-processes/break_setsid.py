#!/usr/bin/env python3
"""Break 3 (L1 day 2, 2026-10-31): a `setsid` escapee through the API. Decision 002 (C') kills the command's group;
a child that ran `setsid` is in a group of its own (#36). Does the stop miss it, and does `leaks` list it (and
nothing else)?

Usage: python3 break_setsid.py [--runs 3]   (needs nothing else on localhost:8080 and no sandbox-lab containers)

Each run uses a fresh sandbox (alpine, `tini` as PID 1), so leftovers from one run never count in the next:
1. exec 1: `sh -c 'sleep 3600 & setsid sleep 3601 & wait'` with timeout_s 1 -> exit code, stopped_by, stop_ms,
   leaks, how long the call took, and the API's own timeline from its log (ms after the request was sent).
2. Independent check: `docker exec <container> ps` right after.
3. exec 2: `echo hi`, no timeout: an unrelated command that ends on its own. What is its leaks list?
4. Delete the sandbox through the API.
5. No-`wait` control, in a second fresh sandbox: `sh -c 'sleep 3600 & setsid sleep 3601 &'`, timeout_s 1. `sh` exits
   at once while both sleeps still hold copies of its output. Does the exec end when `sh` exits (stopped_by none) or
   when the output closes (the timeout fires)? Same measures as step 1.

Appends one row per run to ../../results/l1-setsid.csv.
"""
import argparse
import csv
import json
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

from break_disconnect import API, LOG, REPO, api_up, docker_view, log_lines, ps, request, start_api

OUT = REPO / "results" / "l1-setsid.csv"
ESCAPEE = "sleep 3600 & setsid sleep 3601 & wait"
NO_WAIT = "sleep 3600 & setsid sleep 3601 &"


def exec_(sb_id, cmd, timeout_s=0):
    body = json.dumps({"cmd": cmd, "timeout_s": timeout_s}).encode()
    req = urllib.request.Request(f"{API}/sandboxes/{sb_id}/exec", method="POST", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        return t0, round(1000 * (time.time() - t0)), json.loads(resp.read())


def leak_names(res):
    return "; ".join(f"{p['pid']} {p['args']} (parent {p['ppid']}, group {p['pgid']}, {p['stat']})"
                     for p in res["leaks"])


def stop_run(label, sb, script):
    """One exec of `sh -c script` with timeout_s 1: the API's timeline, its result, and ps right after."""
    offset = LOG.stat().st_size
    t0, call_ms, r = exec_(sb["id"], ["sh", "-c", script], timeout_s=1)
    for ts, text in log_lines(offset):
        if not text.startswith("docker: processes"):
            print(f"   {1000 * (ts - t0):+8.1f} ms  {text}")
    print(f"   {label} -> exit {r['exit_code']}, stopped_by {r['stopped_by']}, stop_ms {r['stop_ms']}, "
          f"call {call_ms} ms")
    print(f"   {label} leaks: {leak_names(r) or 'none'}")
    after = ps(sb["runtime_id"])
    print("   ps inside the sandbox:\n      " + after.replace("\n", "\n      "))
    return r, call_ms, after


def new_sandbox(n, label):
    status, sb = request("POST", "/sandboxes")
    print(f"run {n} {label}: sandbox {sb['id']} ({status}, container {sb['runtime_id'][:12]})")
    return sb


def one_run(n):
    sb = new_sandbox(n, f"with wait: sh -c '{ESCAPEE}'")
    r1, call_ms, after = stop_run("exec 1", sb, ESCAPEE)
    _, _, r2 = exec_(sb["id"], ["echo", "hi"])
    print(f"   exec 2 `echo hi` -> exit {r2['exit_code']}, stdout {r2['stdout']!r}, leaks: {leak_names(r2) or 'none'}")
    request("DELETE", f"/sandboxes/{sb['id']}")

    sb = new_sandbox(n, f"no wait: sh -c '{NO_WAIT}'")
    r3, call3_ms, after3 = stop_run("no-wait exec", sb, NO_WAIT)
    request("DELETE", f"/sandboxes/{sb['id']}")
    return dict(exit_code=r1["exit_code"], stopped_by=r1["stopped_by"], stop_ms=r1["stop_ms"], call_ms=call_ms,
                leaks_exec1=leak_names(r1), leaks_exec2=leak_names(r2), ps_after=after,
                nowait_exit_code=r3["exit_code"], nowait_stopped_by=r3["stopped_by"], nowait_stop_ms=r3["stop_ms"],
                nowait_call_ms=call3_ms, nowait_leaks=leak_names(r3), nowait_ps_after=after3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    rows = []
    try:
        for n in range(1, a.runs + 1):
            rows.append(dict(date=datetime.now().isoformat(timespec="seconds"), run=n, **one_run(n)))
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
