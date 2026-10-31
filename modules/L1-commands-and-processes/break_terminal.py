#!/usr/bin/env python3
"""Terminal breaks (L1 day 2, 2026-10-31): the API's WebSocket terminal (Ritika's choice: one connection for keys,
output and resize) against a prompt nobody answers, Ctrl-C, a resize, and a client that drops the connection.

Usage: python3 break_terminal.py [--only C2 ...]   (needs nothing else on localhost:8080 and no sandbox-lab containers)

Each scenario gets a fresh sandbox. The agent's side is termclient (Go, same WebSocket library as the API); its
lines show ms since it connected. After each scenario: the API's own exec line from its log, and `ps` inside.
  A  prompt answered (control): `printf "Continue? [y/n] "; read a; echo "got [$a]"`, keys y + Enter after 1 s
  B0 the same prompt through plain exec (no terminal), for contrast
  B  the same prompt, nobody answers, timeout_s 3
  C  Ctrl-C: `sleep 601 & sleep 602`, Ctrl-C after 1.5 s (no timeout until 15 s)
  D  resize: `stty size; sleep 2; stty size`, first size 24x80, resize to 40x120 after 1 s
  D0 no first size: `stty size`
  E  client drops the connection: `sleep 600`, connection closed after 1 s
  C2 (only with --only C2) Ctrl-C again, but `trap "" HUP` first: does `sleep 601` survive once SIGHUP is ignored too?

Appends one row per scenario to ../../results/l1-terminal.csv.
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

OUT = REPO / "results" / "l1-terminal.csv"
CLIENT = REPO / "bin" / "termclient"
PROMPT = 'printf "Continue? [y/n] "; read a; echo "got [$a]"'

SCENARIOS = [
    ("A", "prompt answered", ["sh", "-c", PROMPT], ["-timeout", "10"], ["sleep:1", r"keys:y\r"]),
    ("B0", "prompt, plain exec", ["sh", "-c", PROMPT], None, None),
    ("B", "prompt, nobody answers", ["sh", "-c", PROMPT], ["-timeout", "3"], []),
    ("C", "Ctrl-C", ["sh", "-c", "sleep 601 & sleep 602"], ["-timeout", "15", "-wait", "25"], ["sleep:1.5", "ctrlc"]),
    ("D", "resize", ["sh", "-c", "stty size; sleep 2; stty size"], ["-timeout", "10", "-rows", "24", "-cols", "80"],
     ["sleep:1", "resize:40x120"]),
    ("D0", "no first size", ["sh", "-c", "stty size"], ["-timeout", "10"], []),
    ("E", "client drops the connection", ["sh", "-c", "sleep 600"], [], ["sleep:1", "close"]),
]
EXTRA = [
    ("C2", "Ctrl-C, SIGHUP ignored", ["sh", "-c", 'trap "" HUP; sleep 601 & sleep 602'],
     ["-timeout", "15", "-wait", "25"], ["sleep:1.5", "ctrlc"]),
]


def plain_exec(sb_id, cmd):
    body = json.dumps({"cmd": cmd, "timeout_s": 10}).encode()
    req = urllib.request.Request(f"{API}/sandboxes/{sb_id}/exec", method="POST", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read())
    ms = round(1000 * (time.time() - t0))
    print(f"   plain exec -> {ms} ms: stdout {res.get('stdout', '')!r}, exit {res['exit_code']}, "
          f"stopped_by {res['stopped_by']}")
    return "RESULT " + json.dumps({k: res[k] for k in ("exit_code", "stopped_by", "stop_ms")} |
                                  {"stdout": res.get("stdout", ""), "leaks": len(res["leaks"])})


def run(key, name, cmd, flags, steps):
    status, sb = request("POST", "/sandboxes")
    print(f"\n{key}. {name}: sandbox {sb['id']} ({status}), cmd {cmd}, steps {steps}")
    offset = LOG.stat().st_size
    if flags is None:
        last = plain_exec(sb["id"], cmd)
    else:
        out = subprocess.run([str(CLIENT), "-sandbox", sb["id"], "-cmd", json.dumps(cmd), *flags, *steps],
                             capture_output=True, text=True, timeout=120).stdout.rstrip()
        print("   " + out.replace("\n", "\n   "))
        last = out.splitlines()[-1] if out else ""
    api_line = ""
    for _ in range(100):  # the API's own line, also when the client has left (E)
        api_line = next((t for _, t in log_lines(offset) if t.startswith(f"api: exec {sb['id']} ")), "")
        if api_line:
            break
        time.sleep(0.1)
    print(f"   API log: {api_line or 'no exec line within 10 s'}")
    after = ps(sb["runtime_id"])
    print("   ps inside the sandbox:\n      " + after.replace("\n", "\n      "))
    request("DELETE", f"/sandboxes/{sb['id']}")
    return dict(date=datetime.now().isoformat(timespec="seconds"), scenario=key, name=name, client_last=last,
                api_line=api_line, ps_after=after)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", help="scenario keys to run, e.g. C2")
    a = p.parse_args()
    chosen = [s for s in SCENARIOS + EXTRA if s[0] in a.only] if a.only else SCENARIOS
    if api_up():
        sys.exit("something already answers on localhost:8080; stop it first")
    if docker_view():
        sys.exit("sandbox-lab containers already exist; clean up first:\n"
                 "  docker rm -f $(docker ps -aq --filter label=sandbox-lab)")
    subprocess.run(["go", "build", "-o", "bin/sandbox-api", "./cmd/sandbox-api"], cwd=REPO, check=True)
    subprocess.run(["go", "build", "-o", "bin/termclient", "./modules/L1-commands-and-processes/termclient"],
                   cwd=REPO, check=True)
    api = start_api()
    rows = []
    try:
        for s in chosen:
            rows.append(run(*s))
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
