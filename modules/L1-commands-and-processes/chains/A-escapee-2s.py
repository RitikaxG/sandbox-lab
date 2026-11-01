TITLE = "Chain A: a setsid escapee makes the stop take 2 s (Break 3, #39; 3 runs)"
LANES = [("AGENT", 230), ("OUR API", 300), ("DOCKER", 300), ("SANDBOX PROCESSES", 330)]
ROWS = [
    ("0 ms", {
        0: ("POST /exec  timeout_s=1\nsh -c 'sleep 3600 & setsid sleep 3601 & wait'", ""),
        1: ("docker exec (output = one pipe)", ""),
        3: ("sh: leader of its own group + session\nsleep 3600: in sh's group\nsetsid sleep 3601: NEW group + session\nall three hold the output pipe", ""),
    }),
    ("1,002 ms", {
        1: ("timeout fires\nkill helper exec: SIGTERM to sh's group", "key"),
        3: ("sh dies (SIGTERM, 143)\nsleep 3600 dies\nsleep 3601 missed: other group", "bad"),
    }),
    ("~1,0xx ms", {
        2: ("sees the exec's main process (sh) exit\n-> waits up to 2 s for the output to close", "key"),
        3: ("sleep 3601 runs on, parent -> PID 1 (tini)\nstill holds the output pipe", "bad"),
    }),
    ("waiting", {
        1: ("still inside the SIGTERM step (normally ~40 ms)", ""),
        2: ("helper exec's exit event queued behind sh's (one event at a time per container) [INFERENCE]", "inf"),
    }),
    ("~3,030 ms", {
        2: ("2 s up: Docker cuts the output itself\nthen handles the helper's exit", "key"),
    }),
    ("~3,050 ms", {
        1: ("helper returns after ~2,045 ms\nSIGKILL the group: 35-41 ms, group already empty\nno extra wait: output already closed", ""),
    }),
    ("~3,120 ms", {
        0: ("200  exit 143 (sh's: 128+15)\nstopped_by timeout\nstop_ms ~2,087\nleaks: [sleep 3601]", "bad"),
        1: ("leak count: ps vs the create-time baseline -> sleep 3601", ""),
    }),
    ("then", {
        0: ("POST /exec echo hi\n-> exit 0, leaks: [sleep 3601] again", "bad"),
        1: ("same count vs the create-time baseline: blames echo for an old leak (postmortem 002 G3)", ""),
        3: ("echo runs and exits 0\nsleep 3601 still running", ""),
    }),
]
ARROWS = [
    ((1, 1), (1, 3), "causes"),
    ((1, 3), (2, 2), "sh's exit starts the clock"),
    ((2, 3), (4, 2), "keeps it open the full 2 s"),
    ((4, 2), (5, 1), "unblocks"),
]
NOTE = ("Measured: timeout 1,002 ms; SIGTERM helper 2,049 / 2,045 / 2,046 ms; stop_ms 2,091 / 2,081 / 2,087. "
        "Docker's 2 s: SOURCE-VERIFIED (moby v29.0.0 daemon/monitor.go ProcessEvent EventExit, WithTimeout 2 s, StreamConfig.Wait). "
        "No-wait control: sh exits on its own at ~0 ms, Docker's cut at ~2.0 s, not 1,002 + 2,000: the clock follows sh's exit, not the timeout. "
        "Source: sandbox-lab results/l1-setsid.csv.")
