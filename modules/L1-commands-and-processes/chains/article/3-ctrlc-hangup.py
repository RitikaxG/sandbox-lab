TITLE = "3. Ctrl-C in a terminal: the hang-up, not Ctrl-C, cleans up the background job"
LANES = [("THE AGENT", 230), ("OUR SANDBOX API", 290), ("DOCKER", 290), ("INSIDE THE SANDBOX", 350)]
ROWS = [
    ("start", {
        0: ("Open a terminal. Run:\nsh -c 'sleep 601 & sleep 602'", ""),
        3: ("all three in one process group, the terminal's foreground group\nsh runs sleep 601 in the background with Ctrl-C (SIGINT) ignored", ""),
    }),
    ("1.5 s", {
        0: ("Press Ctrl-C", ""),
        2: ("The terminal turns Ctrl-C into SIGINT for the foreground group", "key"),
        3: ("sleep 602 stops, sh exits with 130 (128 + SIGINT)\nsleep 601 ignores SIGINT and keeps running", "bad"),
    }),
    ("next", {
        2: ("sh, the program the terminal was opened for, is gone", "key"),
        3: ("A hang-up signal (SIGHUP) reaches sleep 601. It does not ignore SIGHUP: it stops", "ok"),
    }),
    ("+55 ms", {
        0: ("Result: exit 130, no leftovers", "ok"),
    }),
    ("same run with trap \"\" HUP", {
        0: ("Result: exit 130, leftover: sleep 601", "bad"),
        3: ("sleep 601 ignores SIGHUP too: it survives both signals", "bad"),
    }),
]
ARROWS = [
    ((1, 2), (1, 3), "SIGINT"),
    ((2, 2), (2, 3), "SIGHUP"),
]
NOTE = "The two runs differ only in the trap line, so the hang-up is what cleaned up sleep 601."
