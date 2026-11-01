TITLE = "Chain B1: fork bomb, NO PID limit (Break 4, #40; 1 run)"
LANES = [("AGENT", 230), ("OUR API", 300), ("DOCKER + ITS ONE VM", 300), ("SANDBOX PROCESSES", 330)]
ROWS = [
    ("0 ms", {
        0: ("POST /exec  timeout_s=3\nsh -c 'bomb() { bomb | bomb & }; bomb'", ""),
        1: ("docker exec (output = one pipe)", ""),
        3: ("sh starts bomb | bomb & and exits 0 at once\nbomb children inherit the output pipe and multiply", "bad"),
    }),
    ("~0 ms", {
        2: ("sees the exec's main process (sh) exit\n-> waits up to 2 s for the output to close", "key"),
    }),
    ("2,056 ms", {
        1: ("exec-run returns (timeout never fired: stop step never runs)", ""),
        2: ("2 s up: Docker cuts the output itself", "key"),
    }),
    ("next", {
        1: ("leak count: ps helper exec, NO deadline in our code (postmortem 002 G2)", "bad"),
        2: ("helper never answers: VM starved [peak count UNKNOWN; PIDs or memory: INFERENCE]", "inf"),
        3: ("bomb keeps growing: one kernel, one VM shared by every container and by dockerd", "bad"),
    }),
    ("60 s", {
        0: ("bomb call: no answer\necho hi: no answer", "bad"),
        1: ("delete: no answer", "bad"),
        2: ("docker ps, docker rm -f: no answer", "bad"),
    }),
    ("8 min", {
        2: ("docker ps still no answer\nVM process at 664% CPU (8 CPUs)", "bad"),
    }),
    ("+131 s", {
        2: ("docker desktop restart (with Ritika's OK): docker ps answers after 131 s\ncontainer left Exited (255) = 'died unseen' (L0 #12)", ""),
    }),
]
ARROWS = [
    ((0, 3), (1, 2), "sh's exit starts the clock"),
    ((1, 2), (2, 2), "bombs hold the pipe"),
    ((2, 2), (2, 1), "unblocks"),
    ((3, 3), (3, 2), ""),
    ((3, 2), (3, 1), ""),
]
NOTE = ("Measured: exec-run 2,056 ms; no answers within 60 s; VM 664% CPU at 8 min; restart 129 s, docker ps after 131 s. "
        "Process count UNKNOWN (the docker stats watcher returned no sample; instrument untested). Source: results/l1-forkbomb.csv.")
