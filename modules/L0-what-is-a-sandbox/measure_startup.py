#!/usr/bin/env python3
"""Time how long one throwaway sandbox takes to start, run `true`, and go away.

Usage: python3 measure_startup.py [runs] [runtime ...]   (default: 10 runs, docker and smolvm)
Runtimes: docker, smolvm, smolvm-no-registry (reuses the image digest for an hour,
skipping smolvm's per-run registry check).

For each runtime: one warm-up run (not counted, so an image download doesn't
skew the numbers), then N timed runs. Prints every run, then min / median / max,
and appends the raw numbers to startup_results.csv next to this script.
"""
import csv
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RUNTIMES = {
    "docker": ["docker", "run", "--rm", "alpine", "true"],
    "smolvm": ["smolvm", "machine", "run", "--image", "alpine", "--", "true"],
    "smolvm-no-registry": ["smolvm", "machine", "run", "--seed-digest-ttl", "3600",
                           "--image", "alpine", "--", "true"],
}
DEFAULT = ["docker", "smolvm"]


def time_once(cmd):
    start = time.perf_counter()
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed (exit {result.returncode}):\n{result.stderr}")
    return elapsed_ms


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    names = sys.argv[2:] or DEFAULT
    out = Path(__file__).with_name("startup_results.csv")
    stamp = datetime.now().isoformat(timespec="seconds")
    new_file = not out.exists()

    with out.open("a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "runtime", "run", "ms"])
        for name in names:
            cmd = RUNTIMES[name]
            print(f"\n{name}: {' '.join(cmd)}")
            print(f"  warm-up: {time_once(cmd):.0f} ms (not counted)")
            times = []
            for i in range(1, runs + 1):
                ms = time_once(cmd)
                times.append(ms)
                writer.writerow([stamp, name, i, f"{ms:.1f}"])
                print(f"  run {i:2}: {ms:.0f} ms")
            print(f"  min {min(times):.0f} ms · median {statistics.median(times):.0f} ms · max {max(times):.0f} ms")


if __name__ == "__main__":
    main()
