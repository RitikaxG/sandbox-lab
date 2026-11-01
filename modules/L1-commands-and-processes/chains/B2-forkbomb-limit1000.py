TITLE = "Chain B2: the same bomb, pids.max = 1,000 (Break 4 control, #41; 1 run)"
LANES = [("AGENT", 230), ("OUR API", 300), ("DOCKER + ITS ONE VM", 300), ("SANDBOX PROCESSES", 330)]
ROWS = [
    ("0 ms", {
        0: ("POST /exec  timeout_s=3 (same bomb)", ""),
        3: ("sh starts bomb | bomb & and exits 0 at once\nbombs inherit the output pipe", "bad"),
    }),
    ("~0 ms", {
        2: ("sees sh exit -> waits up to 2 s for the output to close", "key"),
    }),
    ("0.2 s", {
        3: ("count 2 -> 986 in one sample; then 889-1,000: bombs exit and refill freed slots; peak 1,000\nlimit contains it: rest of the VM untouched", "ok"),
    }),
    ("2,039 ms", {
        1: ("exec-run returns: exit 0 (sh's own); timeout never fired, stop step never runs", ""),
        2: ("2 s up: Docker cuts the output itself", "key"),
    }),
    ("~2,570 ms", {
        1: ("leak count: ps helper got a freed slot (~530 ms) -> 1,007 rows, more than the limit [INFERENCE: a moving set]", ""),
    }),
    ("2,599 ms", {
        0: ("200  exit 0\nstopped_by none, stop 0\nleaks: 1,007\nstderr 596 KB of fork failures", "bad"),
    }),
    ("then", {
        0: ("echo hi: 200 in 65 ms\nexit 128, no output, leaks 0", "bad"),
        1: ("returns 200 for a command that never ran; its ps helper can't start either and our run helper ignores the failure -> 'leaks 0' (G2)", "bad"),
        3: ("no free slot: echo can't start [128 meaning: INFERENCE, source check Thu Nov 5]\n999 still running", "bad"),
    }),
    ("after", {
        0: ("delete: 204 in 445 ms", "ok"),
        2: ("docker ps: 129 ms", "ok"),
    }),
]
ARROWS = [
    ((0, 3), (1, 2), "sh's exit starts the clock"),
    ((1, 2), (3, 2), "bombs hold the pipe"),
    ((3, 2), (3, 1), "unblocks"),
    ((6, 3), (6, 1), "no slot for echo or ps"),
]
NOTE = ("Measured: pids.current read every 0.2 s by a watcher that never forks (bin/pidwatch.log); 999 alive 3 s after the call. "
        "With the limit the damage stays in one sandbox: Docker and delete still work, but the sandbox can't start anything and our API reports it as success. "
        "Source: results/l1-forkbomb.csv.")
