#!/usr/bin/env python3
"""The D flip (L1 day 2, 2026-10-31; decision 002, module loop step 8): rerun break 3's escapee with option D's
sweep (`kill -KILL -1` from a fresh exec after the command) and count leaks against collateral kills.

Usage: python3 break_dflip.py   (needs nothing else on localhost:8080 and no sandbox-lab containers)

One fresh sandbox (alpine, `tini` as PID 1, main program `sleep 86400`):
0. "dev server" the agent starts on purpose: `sh -c 'setsid sleep 900 > /dev/null 2>&1 &'`, no sweep. Its output
   goes to /dev/null, so it holds nothing of the exec's (break 3) and the call returns at once.
1. Break 3's command with the sweep: `sh -c 'sleep 3600 & setsid sleep 3601 & wait'`, timeout_s 1, sweep true.
   Result: exit code, stopped_by, stop_ms, leaks, swept (what the sweep killed), sweep_note, call time.
2. Independent check: `ps` inside, and Docker's view of the container (running or not, exit code).
3. `echo hi`: does the sandbox still work?
4. Delete the sandbox through the API.

Appends one row to ../../results/l1-dflip.csv.
"""
import csv
import signal
import subprocess
import sys
from datetime import datetime

from break_disconnect import LOG, REPO, api_up, docker_view, log_lines, ps, request, start_api
from break_setsid import ESCAPEE, leak_names
import break_setsid

OUT = REPO / "results" / "l1-dflip.csv"
SERVER = "setsid sleep 900 > /dev/null 2>&1 &"


def exec_(sb_id, cmd, timeout_s=0, sweep=False):
    """POST /exec with optional sweep; returns (t0, call ms, status, JSON or error text)."""
    import json
    import time
    import urllib.error
    import urllib.request
    body = json.dumps({"cmd": cmd, "timeout_s": timeout_s, "sweep": sweep}).encode()
    req = urllib.request.Request(f"{break_setsid.API}/sandboxes/{sb_id}/exec", method="POST", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return t0, round(1000 * (time.time() - t0)), resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return t0, round(1000 * (time.time() - t0)), e.code, e.read().decode(errors="replace")


def docker_state(cid):
    out = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}} exit {{.State.ExitCode}}", cid],
                         capture_output=True, text=True).stdout.strip()
    return out or "gone"


def main():
    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    try:
        status, sb = request("POST", "/sandboxes")
        cid = sb["runtime_id"]
        print(f"sandbox {sb['id']} ({status}, container {cid[:12]})")

        _, ms, st, r0 = exec_(sb["id"], ["sh", "-c", SERVER], timeout_s=5)
        print(f"0. dev server `{SERVER}` -> {st} in {ms} ms: exit {r0['exit_code']}, "
              f"leaks: {leak_names(r0) or 'none'}")

        offset = LOG.stat().st_size
        t0, ms, st, r1 = exec_(sb["id"], ["sh", "-c", ESCAPEE], timeout_s=1, sweep=True)
        for ts, text in log_lines(offset):
            if not text.startswith("docker: processes"):
                print(f"   {1000 * (ts - t0):+8.1f} ms  {text}")
        if st == 200:
            print(f"1. escapee + sweep -> {st} in {ms} ms: exit {r1['exit_code']}, stopped_by {r1['stopped_by']}, "
                  f"stop_ms {r1['stop_ms']}")
            print(f"   leaks: {leak_names(r1) or 'none'}")
            print(f"   swept: {leak_names({'leaks': r1.get('swept', [])}) or 'none'}")
            print(f"   sweep_note: {r1.get('sweep_note') or '-'}")
        else:
            print(f"1. escapee + sweep -> {st} in {ms} ms: {r1}")
        state = docker_state(cid)
        after = ps(cid)
        print(f"2. Docker says the container is: {state}")
        print("   ps inside the sandbox:\n      " + (after.replace("\n", "\n      ") or "(no answer)"))

        _, ms2, st2, r2 = exec_(sb["id"], ["echo", "hi"], timeout_s=5)
        echo = (f"{st2} in {ms2} ms: exit {r2['exit_code']}, stdout {r2.get('stdout', '')!r}" if st2 == 200
                else f"{st2} in {ms2} ms: {str(r2)[:200]}")
        print(f"3. echo hi -> {echo}")
        request("DELETE", f"/sandboxes/{sb['id']}")

        row = dict(date=datetime.now().isoformat(timespec="seconds"), server_leaks=leak_names(r0),
                   status=st, call_ms=ms, exit_code=r1.get("exit_code") if st == 200 else "",
                   stopped_by=r1.get("stopped_by") if st == 200 else "",
                   leaks=leak_names(r1) if st == 200 else "",
                   swept=leak_names({"leaks": r1.get("swept", [])}) if st == 200 else "",
                   sweep_note=r1.get("sweep_note", "") if st == 200 else str(r1)[:200],
                   container_after=state, ps_after=after, echo=echo)
    finally:
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\n1 row appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
