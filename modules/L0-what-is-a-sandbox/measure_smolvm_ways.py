#!/usr/bin/env python3
"""Time the three ways to get a smolvm sandbox, next to Docker, over the same full trip:
make a sandbox, run `true` in it, get rid of it.

Usage: python3 measure_smolvm_ways.py [runs] [way ...]     (default: 10 runs, all four ways)

Ways:
  docker  docker run --rm alpine true                                   (reference)
  image   smolvm machine run --seed-digest-ttl 3600 --image alpine -- true   (boot from the image, registry check skipped)
  pack    smolvm machine run --from alpine.smolmachine -- true          (start from a packed file)
  branch  smolvm machine branch --from <running source> → exec true → delete   (clone a running machine)

Setup (done here if missing, in ../../bin/smolvm-ways/, which git ignores): the alpine pack, and a running
`--branchable` source machine `l0b-src` (alpine, `sleep 86400`), deleted again at the end.
One warm-up per way (not counted), then N runs. Raw numbers: ../../results/l0-smolvm-three-ways.csv
"""
import csv
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / "bin" / "smolvm-ways"
PACK = WORK / "alpine.smolmachine"
SOURCE = "l0b-src"
OUT = REPO / "results" / "l0-smolvm-three-ways.csv"


def sh(*cmd):
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed (exit {r.returncode}):\n{r.stderr[-800:]}")


def setup(names):
    if "pack" in names and not PACK.exists():
        WORK.mkdir(parents=True, exist_ok=True)
        print("setup: packing alpine into a .smolmachine (needs the internet once)")
        sh("smolvm", "pack", "create", "--image", "alpine", "-o", str(WORK / "alpine"))
    if "branch" in names:
        ls = subprocess.run(["smolvm", "machine", "ls"], capture_output=True, text=True).stdout
        line = next((l for l in ls.splitlines() if l.split()[:1] == [SOURCE]), "")
        if "running" not in line:
            if not line:
                sh("smolvm", "machine", "create", "--name", SOURCE, "--image", "alpine", "--", "sleep", "86400")
            print(f"setup: starting branchable source {SOURCE}")
            sh("smolvm", "machine", "start", "--name", SOURCE, "--branchable")
            sh("smolvm", "machine", "exec", "--name", SOURCE, "--", "true")
            time.sleep(10)  # a branch ~1 s after start hung on 2026-10-25; let the source settle


counter = 0


def trip(way):
    """One full trip; returns ms."""
    global counter
    start = time.perf_counter()
    if way == "docker":
        sh("docker", "run", "--rm", "alpine", "true")
    elif way == "image":
        sh("smolvm", "machine", "run", "--seed-digest-ttl", "3600", "--image", "alpine", "--", "true")
    elif way == "pack":
        sh("smolvm", "machine", "run", "--from", str(PACK), "--", "true")
    elif way == "branch":
        counter += 1
        child = f"l0b-child-{counter}"
        sh("smolvm", "machine", "branch", "--from", SOURCE, "--name", child)
        sh("smolvm", "machine", "exec", "--name", child, "--", "true")
        sh("smolvm", "machine", "delete", "-f", "--name", child)
    return (time.perf_counter() - start) * 1000


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    names = sys.argv[2:] or ["docker", "image", "pack", "branch"]
    setup(names)
    stamp = datetime.now().isoformat(timespec="seconds")
    machine = f"{platform.machine()} macOS {platform.mac_ver()[0]}"
    new_file = not OUT.exists()
    summary = []
    try:
        with OUT.open("a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["timestamp", "machine", "way", "run", "ms"])
            for way in names:
                print(f"\n{way}: warm-up {trip(way):.0f} ms (not counted)")
                times = []
                for i in range(1, runs + 1):
                    ms = trip(way)
                    times.append(ms)
                    w.writerow([stamp, machine, way, i, f"{ms:.1f}"])
                    print(f"  run {i:2}: {ms:6.0f} ms")
                summary.append((way, min(times), statistics.median(times), max(times)))
    finally:
        if "branch" in names:
            subprocess.run(["smolvm", "machine", "delete", "-f", "--name", SOURCE], capture_output=True)
    print("\nway       min    median     max   (ms, full trip)")
    for way, lo, med, hi in summary:
        print(f"{way:7} {lo:6.0f}  {med:7.0f}  {hi:6.0f}")
    left = [l.split()[0] for l in subprocess.run(["smolvm", "machine", "ls"], capture_output=True,
                                                 text=True).stdout.splitlines() if l.startswith("l0b-")]
    print(f"smolvm machines left from this script: {len(left)} {left}")


if __name__ == "__main__":
    main()
