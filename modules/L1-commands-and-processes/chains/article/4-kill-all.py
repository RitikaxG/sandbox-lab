TITLE = "4. 'Kill every process' cleans up the leak, and the sandbox with it"
LANES = [("THE AGENT", 230), ("OUR SANDBOX API", 290), ("DOCKER", 290), ("INSIDE THE SANDBOX", 350)]
ROWS = [
    ("setup", {
        3: ("PID 1 is tini. Its one child is the sandbox's main program (sleep 86400). The container lives as long as PID 1", ""),
    }),
    ("call 1", {
        0: ("Start a dev server in the background:\nsetsid sleep 900 > /dev/null 2>&1 &\nResult in 62 ms", ""),
        3: ("sleep 900 keeps running on its own, as intended", "ok"),
    }),
    ("call 2", {
        0: ("Run the escape command from figure 1, with 'sweep' on", ""),
        1: ("Stop the group, as before. Then sweep: run kill -KILL -1 (kill everything I am allowed to)", "key"),
        3: ("The escaped sleep 3601 dies. So do the dev server and the main program", "bad"),
    }),
    ("next", {
        3: ("tini's only child is gone, so tini exits with 137 (128 + SIGKILL)", "bad"),
        2: ("PID 1 exited: the container has stopped", "bad"),
    }),
    ("3.3 s", {
        1: ("Count leftovers: Docker refuses (409), there is no running container to look into", ""),
        0: ("Result: stopped by timeout, exit 143, no leftover count", "bad"),
    }),
    ("next call", {
        0: ("Run: echo hi\nResult: error 500, container not running", "bad"),
        1: ("Still believes the sandbox is running: it never asked Docker", "bad"),
    }),
]
ARROWS = [
    ((2, 1), (2, 3), "SIGKILL to all"),
    ((2, 3), (3, 3), ""),
    ((3, 3), (3, 2), ""),
]
NOTE = "The sweep removed the leak, but also the agent's dev server and the whole sandbox. One run."
