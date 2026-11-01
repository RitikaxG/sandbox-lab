TITLE = "Chain D: the D flip, 'kill everything' ends the sandbox (#44; 1 run)"
LANES = [("AGENT", 230), ("OUR API", 290), ("DOCKER", 280), ("SANDBOX PROCESSES", 360)]
ROWS = [
    ("before", {
        3: ("PID 1 tini -> its one child, the container's MAIN command (sleep 86400)\nthe container lives exactly as long as PID 1", ""),
    }),
    ("call 1", {
        0: ("dev server: setsid sleep 900 > /dev/null 2>&1 &", ""),
        3: ("exec'd sh starts sleep 900 (new group + session, output to /dev/null) and exits 0\nsleep 900: parent -> PID 1, group 20\nan exec'd sh is NOT the main command: its exit never ends the container", ""),
    }),
    ("+62 ms", {
        0: ("200 in 62 ms\nleaks: [sleep 900]", ""),
        2: ("sh exited and nothing holds the output pipe -> no 2 s wait", "ok"),
    }),
    ("call 2", {
        0: ("Chain A's command, timeout_s=1, sweep: true", ""),
        1: ("1,004 ms timeout; SIGTERM step 2,122 ms (Docker's 2 s, as in A); SIGKILL group 42 ms", ""),
    }),
    ("~3,150 ms", {
        1: ("sweep: fresh exec runs kill -KILL -1 (19 ms)", "key"),
        3: ("kill -1 = every process it may signal except itself and PID 1:\nsleep 86400 (main), sleep 900 (dev server), sleep 3601 (escapee) all die", "bad"),
    }),
    ("next", {
        3: ("tini's child is gone -> tini exits with 128 + 9 = 137 -> PID 1 gone", "bad"),
        2: ("container Exited (137)", "bad"),
    }),
    ("next", {
        1: ("leak count: exec into the container", ""),
        2: ("409: no exec into a container that is not running", "bad"),
    }),
    ("3,289 ms", {
        0: ("200, exit 143, timeout\nno swept, sweep_note 'unable to upgrade to tcp, received 409'", "bad"),
    }),
    ("then", {
        0: ("echo hi: 500 in 3 ms 'container is not running'", "bad"),
        1: ("its in-memory list still says running: it never asked Docker", "bad"),
    }),
]
ARROWS = [
    ((4, 1), (4, 3), "SIGKILL to all"),
    ((4, 3), (5, 3), ""),
    ((5, 3), (5, 2), ""),
    ((6, 2), (7, 0), "refused"),
]
NOTE = ("D's collateral vs C': it killed the escapee, but also the agent's dev server and the sandbox itself. That is why decision 002 keeps C' "
        "(group stop + count leftovers) and postmortem 002 G4 kills only this exec's leftovers. Exit 137 of the container = tini passing on its child's SIGKILL. "
        "Source: results/l1-dflip.csv.")
