TITLE = "2a. A fork bomb with no process limit takes down every sandbox"
LANES = [("THE AGENT", 230), ("OUR SANDBOX API", 290), ("DOCKER", 290), ("INSIDE THE SANDBOX", 350)]
ROWS = [
    ("start", {
        0: ("Run: a fork bomb\nsh -c 'bomb() { bomb | bomb & }; bomb'\nwith a 3 s timeout", ""),
        3: ("sh starts the first bomb in the background and exits at once\nbombs copy themselves without limit and keep the output pipe open", "bad"),
    }),
    ("2 s", {
        2: ("sh has exited: Docker waits 2 s for the output to close, then cuts it", ""),
        1: ("The command 'finished' before the timeout, so our stop never runs", ""),
    }),
    ("next", {
        1: ("Count leftover processes: start ps inside the sandbox. It never answers, and our code has no deadline for it", "bad"),
        3: ("The bomb keeps growing. On a Mac all containers, and Docker itself, share one Linux VM", "bad"),
    }),
    ("60 s", {
        0: ("No answer for the bomb call, for echo hi, or for deleting the sandbox", "bad"),
        2: ("docker ps: no answer", "bad"),
    }),
    ("8 min", {
        2: ("Still no answer. The VM is busy at 664% CPU (8 CPUs)", "bad"),
    }),
    ("fix", {
        2: ("Restart Docker Desktop: Docker answers again after 131 s. Until then Docker could not serve any sandbox", ""),
    }),
]
ARROWS = [
    ((2, 3), (2, 1), ""),
    ((2, 3), (3, 2), ""),
]
NOTE = "One run. Docker Desktop on a Mac (VM: 8 CPUs, about 3.9 GB)."
