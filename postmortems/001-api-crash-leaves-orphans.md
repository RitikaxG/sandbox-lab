# Postmortem 001: the sandbox API crashes and leaves 5 sandboxes nobody can delete

- Date: 2026-10-24 (L0 day 2, break experiment)
- Written by Ritika Gupta; checked by Claude for wrong claims
- Rerun: `python3 modules/L0-what-is-a-sandbox/break_kill_api.py` · raw: `results/l0-kill-api-orphans.csv`
- System: the L0 sandbox API (Docker Engine SDK, decision 001; sandbox list in memory)

## What happened

The sandbox API was killed abruptly (SIGKILL) after it had created and started 5 sandboxes. The containers kept
running, but once the API was back up, it listed no sandboxes and answered `404 no such sandbox` when asked to delete
one by its correct ID. The 5 sandboxes became **orphans**: still running, with nothing that manages them.

## Impact (OBSERVED)

- 5 containers left running, each with PID 1 `sleep 86400`. `sleep` does no work; it only keeps the container alive
  so commands can be `exec`'d into it.
- Each orphan keeps what a container holds: its process and memory, its cgroup and namespaces, its top filesystem
  layer (day 1). How much memory each used was not measured (UNKNOWN).
- Left alone, each `sleep` ends after 24 h; the container then **stops but is not removed** (our create passes an
  empty `HostConfig{}`, so no `AutoRemove`) and still shows in `docker ps -a`. OBSERVED 2026-10-29 with `sleep 30`:
  5 containers `Exited (0)`, all still listed (`break_stop_api.py`, `results/l0-stop-api-orphans.csv`).
- A caller that kept its sandbox ID had no way to delete it through the API.

## Timeline (one run, about 10 s)

| Step | What the API's list said | What Docker had |
| --- | --- | --- |
| 1. create 5 through the API | 5 entries, `running` | 5 containers, running |
| 2. kill the API (SIGKILL) | gone with the process | 5 containers, running |
| 3. restart the API, `GET /sandboxes` | 0 entries | 5 containers, running |
| 4. `DELETE /sandboxes/dee5ac04` | 0 entries → `404`, Docker never asked | 5 containers, running |

## Root cause

There are **two lists** of sandboxes, and only one survives a crash:

- the **API's sandbox list**: entries of our sandbox ID → Docker's container ID, kept **in the API's memory**. It
  dies with the API process.
- **Docker's list of containers**, kept by `dockerd` in Docker Desktop's VM. It has nothing to do with our API's
  process, so it survives, with each container's labels `sandbox-lab=1` and `sandbox-lab.id=<our ID>`.

After the restart, the API answers every request from its own (now empty) list only. `DELETE` looks up the ID there,
finds nothing, and replies 404 without ever asking Docker.

Contributing: the API has no cleanup on exit at all. A gentler stop leaves the same 5 orphans. OBSERVED 2026-10-29:
SIGTERM ended the API at once (exit -15: `main.go` sets no signal handler, so the default action applies) and all 5
containers kept running. The containers are Docker's, not the API's children, so no signal to the API reaches them.
Rerun: `python3 modules/L0-what-is-a-sandbox/break_stop_api.py` (`--signal KILL` for the original).

## How to find and clean them by hand (works without the API)

```bash
docker ps -a --filter label=sandbox-lab                 # every sandbox this API ever made
docker ps -a --filter label=sandbox-lab.id=dee5ac04     # one sandbox, by our ID
docker rm -f $(docker ps -aq --filter label=sandbox-lab)   # remove them all
```

This works after the crash because the labels live on the containers in `dockerd`, not in the API.

## The real fix (coming modules)

- **L2, state that survives:** keep the sandbox list in **Postgres** instead of memory, so a restarted API still has
  every entry and `DELETE` reaches Docker.
- **L3, reconciler and cleanup:** a database alone isn't enough: the API can still die between Docker creating a
  container and the database recording it. A **reconciler** regularly compares Docker's list (found by the
  `sandbox-lab` label) with the database and removes containers nobody owns.

## What we learned

A sandbox's life is held in two places. Whatever is only in the control plane's memory is lost on a crash; whatever
the runtime (Docker) holds outlives it. Labels on the containers are what let anyone find them again.
