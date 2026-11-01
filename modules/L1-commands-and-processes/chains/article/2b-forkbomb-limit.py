TITLE = "2b. The same bomb with a limit of 1,000 processes: contained, but reported as success"
LANES = [("THE AGENT", 230), ("OUR SANDBOX API", 290), ("DOCKER", 290), ("INSIDE THE SANDBOX", 350)]
ROWS = [
    ("start", {
        0: ("Same fork bomb, 3 s timeout\nprocess limit set to 1,000 (pids.max)", ""),
        3: ("sh starts the bomb and exits at once", ""),
    }),
    ("0.2 s", {
        3: ("986 processes, then a steady 1,000: the limit holds. The rest of the machine is fine", "ok"),
    }),
    ("2 to 2.6 s", {
        2: ("Cuts the output after 2 s, as before", ""),
        0: ("Result: success, exit 0, not stopped\nabout 1,000 leftovers", "bad"),
    }),
    ("next call", {
        0: ("Run: echo hi\nResult: success (HTTP 200), exit 128, no output, 0 leftovers", "bad"),
        1: ("Its leftover count could not start a process either. Our code ignored that failure and reported 0", "bad"),
        3: ("999 bombs still running, 1 short of the limit\necho never prints 'hi'", "bad"),
    }),
    ("after", {
        0: ("Delete the sandbox: done in 0.4 s", "ok"),
        2: ("docker ps: answers in 0.1 s", "ok"),
    }),
]
ARROWS = []
NOTE = "The limit kept the damage inside one sandbox. But the API reported a command that printed nothing as a success. One run."
