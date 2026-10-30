# 002: How the sandbox API stops a command

- Date: 2026-10-30 (L1 day 1)
- Decided by: Ritika Gupta (Stage A: options and recommendation by Claude, challenged and decided by Ritika)
- Status: accepted

## Context

`POST /sandboxes/{id}/exec` today (`internal/runtime/docker.go` `Exec`) starts the command with `docker exec`, waits
until its output ends, then reads the exit code. It has no timeout and no way to stop the command. If the command
hangs, the request hangs. If the client goes away, the command keeps running inside the sandbox (INFERENCE: nothing in
`Exec` stops it; to test on Saturday).

L1 adds a timeout and a stop, triggered by the timeout or by the client disconnecting. This record decides **what
"stop" does**.

What we saw this morning (`modules/L1-commands-and-processes/predictions.md` #30–#36, cards P13–P16):

- SIGTERM can be ignored, and children inherit the ignore (#30, #31, #32). Only SIGKILL is certain.
- A plain program as PID 1 drops SIGTERM: `docker stop` waits, then SIGKILL, exit 137 (#34). With `tini` it ends at
  once, exit 143 (#35).
- `docker exec` starts every command in **its own session and process group** (OBSERVED: the exec'd `sh` had
  PGID = SID = its PID every time). So a group kill reaches the command's whole family without touching PID 1.
- A child that runs `setsid` leaves that group, and a group SIGKILL misses it (#36).

One limit applies to every option: **Docker has no endpoint to stop an exec'd command.**
`POST /exec/{id}/kill`, `/stop` and `/signal` all return 404 on Docker 29.9.2 (OBSERVED 2026-10-30). The API has to send the
signal itself, through a second `docker exec … kill`, so it must know the command's PID **inside** the container.
(`GET /exec/{id}/json` gives a `Pid`, but in the Docker VM's numbering, not the container's.)

## Options

| | What "stop" does | Seen in |
| --- | --- | --- |
| **A. Kill the parent** | SIGKILL the command's own PID only | Composio (kills `bash`, both sleeps orphaned, #24); CUA Ctrl-C kills nothing (#20) |
| **B. SIGKILL the group** | SIGKILL the command's process group at once | smolvm's agent: `killpg(SIGKILL)`, exit 124 timeout / 129 disconnect |
| **C. SIGTERM the group, wait, SIGKILL the group** | SIGTERM to the group; if anything is left after a grace period (e.g. 2 s), SIGKILL to the group | `docker stop` (for one container, not one command) |
| **D. Sweep the sandbox** | after the command, SIGKILL every process in the sandbox except PID 1 (`kill -KILL -1` from a fresh exec) | none of the three repos; it uses the container as the boundary (#36 discussion) |

(D's variant, a PID namespace per command with `unshare --pid --fork --kill-child`, needs a privileged container.
That widens what a command could do to the host, so it is listed but not proposed.)

`kill -1` sends to every process the sender may signal, except PID 1 and itself (SOURCE: `kill(2)`). Not yet run in
the lab: INFERENCE until the spike.

## The five questions

| Question | A. parent | B. group SIGKILL | C. TERM, wait, KILL | D. sweep |
| --- | --- | --- | --- | --- |
| **Crash or failure:** what is left behind? | every child (P2) | `setsid` escapees (#36) | `setsid` escapees (#36) | nothing in the sandbox, but also kills anything else running there: a dev server the agent started on purpose, a second command |
| **Promise:** does the command get to clean up? | no | no (SIGKILL) | yes, for the grace period, if it handles SIGTERM | no |
| **Speed:** time to kill | at once | at once | up to the grace period for a command that ignores SIGTERM (P13); at once for one that doesn't | at once, plus one more exec |
| **Cost:** what the API must track or forbid | the command's PID | the command's PID (= its group, since `docker exec` makes it a leader) | the same, plus a timer | nothing to track; must forbid two commands at once in one sandbox, or accept killing both |
| **Already in the stack?** | `docker exec` | `docker exec` | `docker exec` | `docker exec` |

All four share the same gap: if the **API** crashes mid-command, nobody sends any signal and the command runs on.
That is L3's job (reconciler, orphan cleanup), not this decision's.

## Recommendation (Claude, for Ritika to challenge)

**C, with a 2 s grace period.** B and C catch the same processes, and C costs at most 2 s more for a command that
ignores SIGTERM. In exchange, an agent's command that handles SIGTERM (a test runner, a build) gets to clean up. That
is the trade-off you named for smolvm on Oct 26: SIGKILL only means a guaranteed stop, but no time to clean up temp
data or save files. A misses children, which is the
exact bug in Composio and CUA #5588. D catches `setsid` escapees, but it kills anything else the agent left running on
purpose. That is a real cost for an agent that starts a server and then tests it.

`setsid` escapees stay a known leak under C. Saturday measures it, and **D is the flip** (module loop step 8): rerun
the same break with D and count leaks and collateral kills.

## Decision: C′ (C, changed by Ritika's challenge), plus an init in every sandbox

Ritika's challenge to C, which changed it:

- **Zombies pile up under a PID 1 that doesn't reap.** The lab's sandboxes run `sleep 86400` as PID 1 with no init
  (`internal/api/server.go:60`, `HostConfig{}` in `internal/runtime/docker.go:72`), exactly like `l1`. Every stop that
  kills a parent before it reaps its child leaves a `Z` line, under any option.
- **"SIGTERM worked" doesn't mean everything is gone.** The group can be empty while a `setsid` escapee runs on (#36),
  so the API must not assume the stop was clean.
- **The exit code doesn't say why a command ended.** In #31 SIGTERM was ignored, `sleep 600` ran out, and `sh`
  ended normally with 0. A command that finishes on its own during the grace period looks the same as one that was
  never stopped.

What the API does to stop a command (on timeout or client disconnect):

1. SIGTERM to the command's process group.
2. Wait 2 s.
3. **Always** SIGKILL the group, whether or not anything seems left. A command can ignore SIGTERM (P13); a SIGKILL
   to an empty group is a harmless no-op.
4. **Count what is left:** every process in the sandbox other than PID 1 (the init), the sandbox's own main program,
   and the counting command itself. Anything else is reported as a leak in the response (e.g. a `setsid` escapee,
   P16). It is reported, not killed: the sandbox stays up. Never SIGKILL PID 1 to stop a command; that destroys the
   sandbox, which is `delete`'s job.
5. Report **`stopped_by`** (`timeout`, `disconnect` or `none`), set by the API, next to the exit code.

**Init line:** every sandbox runs with an init (`Init: true`, Docker's `--init`, `tini` as PID 1). Ritika's reasons:
`tini` has a handler, so SIGTERM to the sandbox isn't dropped (#35: stop in 0.227 s, exit 143, vs 3.19 s and 137);
and it reaps every orphan handed to it, so a group kill leaves no `Z` lines (#33).

**Decision review (Ritika, 2026-10-30): count leftovers after every exec,** not only after a stop. A command that
ends on its own can leave a child behind too (`sh -c 'sleep 20 & echo started'`: `docker exec` returned in 2.08 s,
`sleep 20` still running under PID 1, OBSERVED). Cost: one more `ps` per exec.

**Decision review (Ritika, 2026-10-30): step 2 waits *up to* 2 s,** and ends early once the command's output closes,
because then every process holding it has died and there is nothing left to wait for. A command that dies on SIGTERM
is stopped in milliseconds, not 2 s (`sleep 30`, timeout 1 s: `stop_ms` 65). SIGKILL still follows every time.

Limit accepted for now: the leak count can't tell an escapee from a second command running at the same time, so one
command at a time per sandbox until a later module needs more.

## What would change this decision

Both confirmed by Ritika (2026-10-30, after the decision review).

- The Saturday break shows escapees are common in real agent commands (dev servers, `nohup`, daemons), so reporting
  them is not enough: switch the leak step from "report" to "kill" (option D's sweep). The flip measures this.
- The 2 s grace period turns out too short for a real cleanup (a test runner removing temp files), or too long for an
  agent waiting on a hung command: change the number, not the steps.
