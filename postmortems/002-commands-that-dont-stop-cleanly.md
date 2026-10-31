# Postmortem 002: commands that don't stop cleanly, and an API that doesn't say so

- Date: 2026-10-31 (L1 day 2, breaks 2–4, the terminal breaks and the D flip)
- Drafted by Claude from the day's records; reviewed and decided by Ritika Gupta (G1–G6, 2026-10-31)
- System: the L1 sandbox API (Docker Engine SDK; decision 002's stop C′: SIGTERM the command's group, wait up to
  2 s, always SIGKILL the group, count leftovers after every exec and report them; `tini` as PID 1)
- Rerun: `modules/L1-commands-and-processes/break_*.py` · raw: `results/l1-*.csv` · predictions #38–#44

## What happened

Six ways an agent's command can go wrong were run through the API. The stop itself held up: a dropped client was
noticed in about 1 ms, a SIGTERM-obeying command was gone in under 90 ms, and no zombies were left. What broke was
everything around the stop: commands that exit early but leave children are never stopped, one sandbox could freeze
Docker for everyone, and in several cases the API answered with something that wasn't true.

## Impact (OBSERVED)

| Break | What it did | Result |
| --- | --- | --- |
| 2. client disconnects mid-stream (#38) | ticker, curl killed | noticed in 1.0–1.3 ms, stopped in 67–86 ms, exit 143, no leaks. The result went nowhere: only the API log knows |
| 3. `setsid` escapee (#39) | `sleep 3600 & setsid sleep 3601 & wait`, timeout 1 s | escapee left running and reported; a later unrelated `echo hi` reported it again; the next helper exec in that sandbox waited 2 s behind Docker |
| 3 control, no `wait` (#39 Q5) | `sh` exits at once, children keep the output | the call did not end with `sh`: the 1 s timeout fired, `stopped_by` said `timeout` for a command that had already ended by itself |
| 4. fork bomb, no PID limit (#40) | `bomb() { bomb \| bomb & }; bomb` | no answer from the API, `docker ps`, delete or `docker rm -f` for ~12 min; Docker restart 131 s; container `Exited (255)` |
| 4. fork bomb, `pids.max` 1,000 (#41) | same | contained: 1,000 processes, `docker ps` 129 ms, delete 445 ms. But `echo hi` came back **HTTP 200, exit 128, no output, 0 leaks** while 999 processes ran |
| terminal (#42, #43) | prompt, Ctrl-C, resize, drop | a prompt nobody answers waits until the timeout (forever with `timeout_s` 0); Ctrl-C + the terminal's hang-up clean up `&` children unless they ignore SIGHUP; no first size makes `stty` fail; a dropped WebSocket noticed at once |
| D flip (#44) | `kill -KILL -1` after the command | killed the escapee, the agent's own dev server and the sandbox's main program: the sandbox exited (137), the leak count could not look (409), the next exec got 500 |

## Root causes

1. **"The output closed" is not "the command is gone".** Children inherit copies of the command's output (P16).
   Docker waits up to 2 s after the command's own process exits, then cuts the output itself (moby
   `daemon/monitor.go`, SOURCE-VERIFIED). Our code treats "output closed" as "finished by itself", so the stop only
   runs on a timeout or a disconnect. A command that exits at once and leaves children (`server &`, the fork bomb)
   is never stopped.
2. **One kernel, no per-sandbox limits.** Sandboxes share the VM's process slots (`threads-max` 31,617) and memory
   (P20). With `pids.max` = max, one sandbox took the whole pool, including the slots Docker and our helpers need.
3. **Our helpers are execs, and their failures are silent.** `kill`, `ps` and the sweep each start a new process in
   the sandbox: they need a free slot, a healthy Docker and a running container. They have no time limit (the API
   hung for the full 60 s in #40), and when one fails the API reports the empty result as a fact: "0 leaks" (#41,
   #44's log line), HTTP 200 with exit 128 for a command that never started (#41).
4. **Leftovers are counted against the processes at create time**, so every later exec reports old leftovers
   again and blames commands that did nothing (#39 Q4).
5. **The API knows only what it asks.** Its sandbox list is in memory and never re-checked (#44: "running" after
   the container exited); a disconnected client's result is logged and lost (#38). Same root as postmortem 001.

## What worked

- Disconnect detection, over plain HTTP (Go's background read, P18) and over WebSocket (our read loop).
- The group stop and its timing; `tini` reaped everything; no zombie in any run.
- The `setsid` escapee was reported correctly, and only it (#39 Q2, #43).
- With a PID limit, deleting a full sandbox still works (445 ms).

## The D flip: option D as written is rejected by its own numbers

`kill -KILL -1` spares only PID 1. It also kills the sandbox's main program (`tini`'s child), and `tini` then
exits, ending the sandbox. It kills processes the agent wants (the dev server). So "kill everything after every
command" can't be the leak step. Decision 002's trigger ("switch report to kill if escapees are common") still needs
an answer, but not this one.

## Gaps and fix options (decisions: Ritika)

| # | Gap | Options | Claude's recommendation | Decision |
| --- | --- | --- | --- | --- |
| G1 | No PID limit (#40) | (a) `pids.max` at create, e.g. 1,024; (b) leave to L7's VMs | (a) now: one line at create, measured to contain the bomb | yes: sandboxes share one kernel, so one must not stop other sandboxes or Docker itself `pids.max` 1,024 at create |
| G2 | Helpers can hang and fail silently (#40, #41, #44) | (a) a deadline on every helper (e.g. 5 s) and "unknown" instead of empty: `leaks: null` + `leak_error`, a `start_error` when the command never started; (b) leave | (a): an API that says "0 leaks" when it couldn't look is worse than one that says "couldn't look" | yes, but not a bare "couldn't look": the result must carry the **reason** the check failed (the helper's error: no free process slot / exit 128, Docker refused because the container stopped (409), helper timed out) |
| G3 | Leaks blamed on the wrong command (#39 Q4) | (a) a process snapshot before each exec, count only new ones (+1 `ps`, ~20–40 ms); (b) keep the create-time baseline | (a) | yes: then the leak list says which command really left each process (`echo hi` was blamed for `sleep 3601`) |
| G4 | Escapees (#39, #43, #44) | (a) report only (today); (b) kill only this exec's new processes after it (needs G3; spares earlier servers and the sandbox, but kills a server started in *this* command on purpose); (c) report, plus an opt-in `kill_leftovers: true` on exec | (c): agents start servers on purpose; the caller knows which leftovers it wants | report and kill: after each exec, kill only the processes **this** exec created (G3's snapshot), never the sandbox's own or earlier commands'; opt-out `keep_leftovers: true` for a server started on purpose |
| G5 | `stopped_by` says `timeout` for a command that had already exited (#39 Q5) | (a) add `exited_before_stop: true/false` from Docker's exec state; (b) leave | (a) | yes: it shows the command's own process had already exited, so what kept the call open was its children holding the output until Docker cut it |
| G6 | Terminal: no first size, no time limit (#42) | (a) default 24×80 when none is sent; (b) a default time limit for terminals, or keep 0 = none | (a) yes; time limit: your call (an idle limit fits L5 better) | default first size: yes (no size made `stty` fail, #42 D0). Time limit: not decided; stays 0 = none for now |
| G7 | Result of a disconnect lost; stale sandbox list (#38, #44) | L2 (exec records in Postgres), L3 (reconciler) | no change now; they are those modules' first test cases | no change now (Claude's recommendation; not discussed) |

**Decision 002 follows:** C′ stays the stop. Its step 4 changes from "report" to "report the leftovers this exec
created and kill them, unless `keep_leftovers`" (G3 + G4), with G1, G2, G5 and G6 added. Option D (`kill -KILL -1`)
is rejected by the flip (#44). Built on the next lab day, predictions first.

## UNKNOWN, scheduled for the next lab day (Thu Nov 5)

- #40's peak process count with no limit (needs another ~14 min Docker outage; the new counter needs no Docker).
- What exit code 128 means for an exec that could not start (#41): Docker and runc source.
- Why busybox `stty size` prints `stty: standard input` on a 0×0 terminal (#42 D0): busybox source.
- Where `docker stop`'s 3 s grace comes from on this Mac (#34): docs/source, then one run with `-t 10`.

## What we learned

Stopping a command is a small part of the problem. The hard part is knowing what is really left and saying so
honestly: output can outlive the process that made it, a cleanup can kill what you wanted, and every check the
control plane runs needs the same scarce things (a process slot, a healthy runtime) that the failure is using up.
