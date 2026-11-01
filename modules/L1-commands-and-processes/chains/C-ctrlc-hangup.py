TITLE = "Chain C: Ctrl-C in a terminal, and the hang-up that follows (#42 C, #43 C2; 1 run each)"
LANES = [("AGENT", 220), ("OUR API", 220), ("DOCKER + TERMINAL", 330), ("SANDBOX PROCESSES", 390)]
ROWS = [
    ("0 ms", {
        0: ("terminal mode (WebSocket)\nC: sh -c 'sleep 601 & sleep 602'\nC2: same + trap \"\" HUP", ""),
        2: ("exec with a terminal; sh is the session leader that controls it", ""),
        3: ("sh: leader of its own group + session\nsleep 601 (&): sh's group; non-interactive sh sets SIGINT + SIGQUIT ignored (SigIgn 6, #21)\nsleep 602: sh's group, in the foreground\nC2 only: SIGHUP ignored in sh, inherited by both sleeps", ""),
    }),
    ("1,500 ms", {
        0: ("sends the Ctrl-C byte", ""),
        1: ("writes it into the terminal", ""),
        2: ("terminal driver turns ^C into SIGINT (signal 2) for the foreground group = sh's group", "key"),
    }),
    ("+ few ms", {
        3: ("sleep 602 dies (SIGINT)\nsh exits 130 = 128 + 2 [by SIGINT itself or passing on sleep 602's status: not checked; same number]\nsleep 601 survives: SIGINT ignored", "bad"),
    }),
    ("next", {
        2: ("the controlling process (sh) died -> SIGHUP to the terminal's foreground group [that the kernel sends it on sh's exit: INFERENCE; the pair proves only that SIGHUP did it]", "inf"),
        3: ("C: sleep 601 dies of SIGHUP (not ignored) -> 0 leaks\nC2: sleep 601 ignores SIGHUP -> runs on, parent -> PID 1", "bad"),
    }),
    ("+53-55 ms", {
        0: ("C: exit 130, stopped_by none, 0 leaks\nC2: exit 130, stopped_by none, 1 leak: sleep 601", "bad"),
        2: ("no 2 s wait, although in C2 sleep 601 still has the terminal open: WHY = UNKNOWN (record's 'hang-up cuts every holder' doubted for ptys; check Thu Nov 5)", "inf"),
    }),
]
ARROWS = [
    ((1, 2), (2, 3), "SIGINT"),
    ((2, 3), (3, 2), "sh's exit"),
    ((3, 2), (3, 3), ""),
]
NOTE = ("Controlled pair: C and C2 differ only by trap \"\" HUP, so SIGHUP from the hang-up is what killed sleep 601 in C (OBSERVED by the pair). "
        "A '&' child of a non-interactive sh ignores SIGINT and SIGQUIT only, not every signal: that is why SIGHUP still reaches it. "
        "Source: results/l1-terminal.csv (rows C, C2).")
