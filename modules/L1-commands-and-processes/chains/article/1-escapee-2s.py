TITLE = "1. One escaped process makes a 1-second timeout take 3 seconds"
LANES = [("THE AGENT", 230), ("OUR SANDBOX API", 290), ("DOCKER", 290), ("INSIDE THE SANDBOX", 350)]
ROWS = [
    ("start", {
        0: ("Run: sh -c 'sleep 3600 & setsid sleep 3601 & wait'\nwith a 1 s timeout", ""),
        3: ("sh and sleep 3600 share one process group\nsetsid moves sleep 3601 into its own group\nall three share the command's output pipe", ""),
    }),
    ("1 s", {
        1: ("Timeout. Send SIGTERM to the command's process group", "key"),
        3: ("sh and sleep 3600 stop\nsleep 3601 is in another group: never gets the signal, keeps running, keeps the output pipe open", "bad"),
    }),
    ("1 s to 3 s", {
        1: ("Our stop is waiting on Docker", ""),
        2: ("sh has exited, so Docker waits for the output to close. It never closes. Docker gives up after 2 s and cuts it", "key"),
    }),
    ("3.1 s", {
        0: ("Result: stopped by timeout, exit 143\nleftover: sleep 3601 still running", "bad"),
        1: ("Count leftover processes in the sandbox", ""),
    }),
    ("next call", {
        0: ("Run: echo hi\nResult: exit 0, leftover: sleep 3601 (again)", "bad"),
        1: ("The leftover count looks at the whole sandbox, so an innocent command is blamed for an old leak", ""),
    }),
]
ARROWS = [
    ((1, 1), (1, 3), "SIGTERM"),
    ((1, 3), (2, 2), "pipe still open"),
    ((2, 2), (3, 1), "gives up after 2 s"),
]
NOTE = "Same result in 3 of 3 runs: stop took 2.08 to 2.09 s instead of under 0.1 s."
