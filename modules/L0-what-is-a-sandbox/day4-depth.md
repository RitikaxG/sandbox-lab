# L0 day 4 (Thu 2026-10-29): depth

L0 was done by its checklist but light. This day checks the L0 records' untested claims, chosen by what helps the
contribution days' lifecycle bugs (Ritika, 2026-10-29): 14 + 13, 12, 11, 4 (numbers from `agent-infra/lab/CURRENT.md`).
The rest moved to the depth list. Predictions #25 onward: `predictions.md`. Pattern cards:
`agent-infra/fundamentals/PATTERNS.md` (private workspace).

## Items 14 + 13: a gentle stop, and what is left when the work ends

Claims checked (postmortem 001): "a gentler stop than SIGKILL would most likely leave the same 5 orphans" and "when
`sleep` ends, the container stops but is not removed". Both now OBSERVED; postmortem updated.

Run (`break_stop_api.py`, defaults: SIGTERM, `sleep 30`; raw `results/l0-stop-api-orphans.csv`):

| Step | Result |
| --- | --- |
| create 5 sandboxes running `sleep 30` | 201 each, 81–194 ms |
| SIGTERM to the API | exit -15 (ended by signal 15); `main.go` sets no handler, so the default action ends it at once |
| Docker right after | 5 containers, all `running` |
| Docker after 35 s | 5 containers, all `exited`, exit code 0, still in `docker ps -a` |

For today: Docker shows exit code 0 for a running container too; only an exited container's code means something.

Patterns: P3 (SIGTERM cleans up only through a handler), P11 (a container lives as long as its PID 1; stopped is not
removed: the API passes an empty `HostConfig{}`, no `AutoRemove`), and the work belongs to Docker, not the API, so the
API's death reaches none of it (the shape of CUA run 1 the same day).

Ritika's explain-back (2026-10-29): we stopped the API, and Docker has nothing to do with it, so the processes inside
the containers were not affected by the SIGTERM sent to the API. When their `sleep` ended after 30 s, each container
stopped on its own; it was not removed, because the API never asked Docker to auto-remove it. Exit code 0, because no
signal ended the process; it completed.

## Item 12: what exit code 255 means after a Docker restart

Claim checked (day 3): "255 = unknown; not checked in Docker's code". Now SOURCE-VERIFIED (Docker 29.9.2,
containerd v2.4.2 here; source read on `master` / `main`):

- containerd `client/task.go`: `const UnknownExitStatus = 255`, "returned when containerd is unable to determine the
  exit status of a process".
- moby `daemon/daemon.go`, `restore()` (runs when `dockerd` starts): for a container Docker's saved record calls
  running, it asks containerd; if the task is not alive and there is no exit status, it sets `ExitCode = 255`, marks
  the container stopped and saves that.
- So `Exited (255)` = "it died and nobody saw how": Docker's record (running) outlived the process (P8). INFERENCE: the
  Docker Desktop restart took the VM down without `dockerd`'s clean stop of each container, which would have left 143
  (SIGTERM) or 137 (SIGKILL).

Reading exit codes (P3 card): 0 normal; 1–127 the program's own choice; 128 + n ended by signal n (130 SIGINT, 137
SIGKILL, 143 SIGTERM); 255 from Docker after a restart = unknown.

Ritika's explain-back (2026-10-29): 255 because we restarted Docker and the containers did not die on their own: nobody
recorded how they died. `Exited (137)` would mean the container was ended by SIGKILL (128 + 9).

## Item 11: does a smolvm branch child carry its parent's host ports?

smolvm 1.30.1. Dup check first: `machine branch --help` documents "Without [`-p`], the source's forwards are remapped
to freshly-allocated host ports"; maintainers worked on pinned branch ports in #1589 and #1725. So the plain case was
a check of the docs; the new part was a pinned conflict.

| Step | Result (OBSERVED) |
| --- | --- |
| source `l11-src`: nginx:alpine, `-p 8080:80`, started `--branchable` | `curl :8080` → nginx's welcome page |
| plain `machine branch --from l11-src --name l11-a` | "port 8080->80 (source) remapped to 23357->80 (child)" |
| write `CHILD` into the child's `index.html`, then `curl` both | `:8080` → nginx's page (source), `:23357` → `CHILD` (child) |
| who listens on the Mac (`lsof`) | smolvm PID 67204 on 8080, smolvm PID 67216 on 23357: one listener per port |
| pinned `machine branch … --name l11-b -p 8080:80` | rc=1: "host port 8080 is already in use by running machine 'l11-src'; source 'l11-src' continues running with retained checkpoint …/s/32bc5819 so the fork can be retried safely" |
| what is left | no `l11-b` in `machine ls`; VM folders 12 → 12; in the source's folder two checkpoints, `141120fd` 291 MB (used by `l11-a`) and `32bc5819` 292 MB (the failed attempt, kept by design) |

The child was booted from the checkpoint, failed on the port, and was removed: error then cleanup. Patterns: P12
(inside is copied, the host port is reassigned; a pinned copy of an owned port is refused), P7 (this cleanup path
works). Open for Monday's smolvm day (`repos/smolvm/CURRENT.md` item 5): is a retained checkpoint reused on retry, or
does each failed attempt add ~290 MB; is it removed with the source?

Ritika's explain-back (2026-10-29): the child got a new free port; `:8080` still showed nginx's page because the
parent's smolvm listens there and relays to the parent's nginx, and `CHILD` was written only in the child. The failed
pinned branch left no child and no folder, only a snapshot of the running source, kept on purpose so the fork can be
retried from it (her guess: a retry reuses it).
