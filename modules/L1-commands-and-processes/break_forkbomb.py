#!/usr/bin/env python3
"""Break 4 (L1 day 2, 2026-10-31): a fork bomb through the API. Time to kill, leaks, and does the sandbox (and the
rest of Docker) stay usable?

Usage: python3 break_forkbomb.py --pids-limit N   (N = 0: no limit; needs nothing else on localhost:8080 and no
       sandbox-lab containers)

The Docker Desktop VM (checked 2026-10-31): 8 CPUs, ~3.9 GB, kernel threads-max 31,617 for the WHOLE VM, and a
sandbox's pids.max is "max" (no limit). With --pids-limit 0 the bomb can use up the VM's tasks or memory and stall
Docker itself (then: quit and reopen Docker Desktop). --pids-limit N sets the sandbox's limit from outside
(`docker update --pids-limit`), not through the API: the limit is decided after this break.

1. Build and start the API; create one sandbox; apply the limit if N > 0.
2. Watch the sandbox's process count from outside: a privileged watcher container reads the sandbox's cgroup file
   `pids.current` every 0.2 s using shell builtins only (no new process per sample, so it keeps counting when nothing
   can fork) and appends to bin/pidwatch.log on the Mac (file sharing, not dockerd). The 2026-10-31 no-limit run used
   `docker stats` instead and got no sample: its lines end in terminal codes the parser missed, and it needs dockerd.
3. exec the bomb with timeout_s 3: `sh -c 'bomb() { bomb | bomb & }; bomb'` (named `bomb`, not `:`: in busybox
   sh the builtin `:` wins over a function of that name). Result or error, call time, the API's timeline.
4. 3 s later: process count. Then `echo hi` through the API (timeout_s 5): does the sandbox still work?
5. `docker ps` time: does the rest of Docker still work?
6. Guard: delete through the API (60 s limit), else `docker rm -f` (60 s limit). Report which one worked.

Appends one row per run to ../../results/l1-forkbomb.csv.
"""
import argparse
import csv
import json
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from break_disconnect import API, LOG, REPO, api_up, docker_view, log_lines, start_api

OUT = REPO / "results" / "l1-forkbomb.csv"
BOMB = "bomb() { bomb | bomb & }; bomb"


def call(method, path, body=None, timeout=60):
    """(status, JSON or error text, ms); status 0 = no answer within timeout."""
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(API + path, method=method, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), round(1000 * (time.time() - t0))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300], round(1000 * (time.time() - t0))
    except OSError as e:
        return 0, str(e), round(1000 * (time.time() - t0))


class PidWatch:
    """Counts the sandbox's processes from its cgroup file, in a watcher container that never forks after it starts.
    Keeps (seconds since the watcher's first sample, count)."""

    LOGFILE = REPO / "bin" / "pidwatch.log"
    NAME = "l1-pidwatch"

    def __init__(self, container):
        self.LOGFILE.unlink(missing_ok=True)
        loop = (f"p=/sys/fs/cgroup/docker/{container}/pids.current; mkfifo /f; exec 3<>/f; "
                'while :; do read up _ < /proc/uptime; n=; read n < $p; echo "$up $n" >> /out/pidwatch.log; '
                "read -t 0.2 -u 3 x; done")
        subprocess.run(["docker", "run", "-d", "--name", self.NAME, "--privileged", "--cgroupns=host",
                        "-v", f"{REPO / 'bin'}:/out", "alpine", "sh", "-c", loop], check=True, capture_output=True)
        for _ in range(50):
            if self.LOGFILE.exists() and self.LOGFILE.stat().st_size:
                return
            time.sleep(0.1)
        sys.exit("process watcher wrote nothing in 5 s")

    @property
    def samples(self):
        rows = []
        for line in self.LOGFILE.read_text().splitlines():
            f = line.split()
            if len(f) == 2:
                rows.append((float(f[0]), int(f[1])))
        return [(round(up - rows[0][0], 1), n) for up, n in rows] if rows else []

    def now(self):
        s = self.samples
        return s[-1][1] if s else None

    def stop(self):
        timed(["docker", "rm", "-f", self.NAME])


def timed(cmd, limit=60):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
        return r.returncode, round(1000 * (time.time() - t0))
    except subprocess.TimeoutExpired:
        return "timeout", round(1000 * (time.time() - t0))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pids-limit", type=int, required=True, help="0 = no limit")
    a = p.parse_args()

    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    api = start_api()
    row = dict(date=datetime.now().isoformat(timespec="seconds"), pids_limit=a.pids_limit)
    watch = None
    try:
        status, sb, _ = call("POST", "/sandboxes")
        cid = sb["runtime_id"]
        if a.pids_limit:
            subprocess.run(["docker", "update", "--pids-limit", str(a.pids_limit), cid], check=True,
                           capture_output=True)
        print(f"sandbox {sb['id']} ({status}, container {cid[:12]}), pids limit {a.pids_limit or 'none'}")

        watch = PidWatch(cid)
        time.sleep(1)
        print(f"processes before: {watch.now()}")

        offset = LOG.stat().st_size
        t_exec = time.time()
        status, res, call_ms = call("POST", f"/sandboxes/{sb['id']}/exec", {"cmd": ["sh", "-c", BOMB], "timeout_s": 3})
        for ts, text in log_lines(offset):
            if not text.startswith("docker: processes"):
                print(f"   {1000 * (ts - t_exec):+8.1f} ms  {text}")
        if status == 200:
            print(f"bomb exec -> {status} in {call_ms} ms: exit {res['exit_code']}, stopped_by {res['stopped_by']}, "
                  f"stop_ms {res['stop_ms']}, {len(res['leaks'])} leaks, stderr {len(res.get('stderr', ''))} bytes")
            row.update(bomb_status=status, bomb_call_ms=call_ms, exit_code=res["exit_code"],
                       stopped_by=res["stopped_by"], stop_ms=res["stop_ms"], leaks=len(res["leaks"]))
        else:
            print(f"bomb exec -> {status} in {call_ms} ms: {res}")
            row.update(bomb_status=status, bomb_call_ms=call_ms, bomb_error=str(res)[:200])

        peak = max((n for _, n in watch.samples), default=None)
        time.sleep(3)
        row.update(peak_pids=peak, pids_3s_after=watch.now())
        print(f"processes: peak {peak}, 3 s after the call returned {watch.now()}")

        status, res, ms = call("POST", f"/sandboxes/{sb['id']}/exec", {"cmd": ["echo", "hi"], "timeout_s": 5})
        ok = status == 200 and res.get("stdout") == "hi\n"
        print(f"echo hi -> {status} in {ms} ms: " + (f"exit {res['exit_code']}, stopped_by {res['stopped_by']}, "
              f"{len(res['leaks'])} leaks" if status == 200 else str(res)))
        row.update(echo_ok=ok, echo_ms=ms)

        code, ms = timed(["docker", "ps", "-q"])
        print(f"docker ps -> {code} in {ms} ms")
        row.update(docker_ps_ms=ms if code == 0 else f"{code} after {ms}")

        status, _, ms = call("DELETE", f"/sandboxes/{sb['id']}")
        if status == 204:
            print(f"delete through the API -> 204 in {ms} ms")
            row.update(cleanup=f"api {ms} ms")
        else:
            code, ms2 = timed(["docker", "rm", "-f", cid])
            print(f"delete through the API -> {status} after {ms} ms; docker rm -f -> {code} in {ms2} ms")
            row.update(cleanup=f"api {status}; docker rm -f {code} {ms2} ms")
        row.update(pids_timeline=" ".join(f"{t}s:{n}" for t, n in watch.samples[::5]))
        print("process count, 1 per second (s since watch start: count; every 0.2 s in bin/pidwatch.log): " + row["pids_timeline"])
    finally:
        if watch:
            watch.stop()
        api.send_signal(signal.SIGTERM)
        api.wait()

    new = not OUT.exists()
    fields = ["date", "pids_limit", "bomb_status", "bomb_call_ms", "exit_code", "stopped_by", "stop_ms", "leaks",
              "bomb_error", "peak_pids", "pids_3s_after", "echo_ok", "echo_ms", "docker_ps_ms", "cleanup",
              "pids_timeline"]
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\n1 row appended to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
