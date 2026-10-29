# L1 topic looks: how each repo runs and stops a command

Week of 2026-10-26. Question per repo from `agent-infra/lab/CURRENT.md` "This week's topic". Reading only.

## Mon 2026-10-26 · smolvm: a `machine exec` command that ignores SIGTERM, or whose client disconnects

Source: smolvm main `907c2334`, guest agent `crates/smolvm-agent/src/main.rs` (VM exec handler ~8095–8290),
`crates/smolvm-agent/src/process.rs` (`is_peer_closed` ~220). SOURCE-VERIFIED unless marked.

1. **Each command gets its own process group.** The agent starts the command with `setsid()` in `pre_exec`: a new
   session and process group whose leader is the command. Everything it starts (`sh -c 'sleep 30'` → `sleep`) joins
   that group unless it leaves on purpose.
2. **The agent watches two things while the command runs** (a loop that wakes on exit or every poll tick):
   - **Client gone:** it peeks at the client's socket (`recv` with `MSG_PEEK | MSG_DONTWAIT`); a closed socket means
     the host `machine exec` died or was Ctrl-C'd. Then: `killpg(group, SIGKILL)`, exit code **129**.
   - **Timeout:** past the deadline (the setup script on Oct 25 had 120 s): `killpg(group, SIGKILL)`, exit **124**.
     That is the "VM exec command timed out, killing process group" line in the Oct 25 branch-hang log.
3. **SIGTERM is never sent.** Both paths go straight to SIGKILL, which a process cannot catch or ignore. So "ignores
   SIGTERM" cannot keep a command alive here. The cost: the command gets no chance to clean up (flush files, remove
   temp data, stop its own children gracefully).
4. **Why the whole group:** the code comment: killing only `sh` leaves `sleep` holding the output pipe, so the agent's
   output readers never see end-of-file and the agent hangs. This is the opposite of CUA #5588, where only the parent
   was killed and the children (serve daemons) survived.
5. **What escapes (INFERENCE, to test in the lab):** a child that calls `setsid` itself, i.e. daemonizes, leaves the
   group, so `killpg` misses it and it survives the timeout or disconnect. Same for anything started with `nohup … &`
   plus `setsid`. The killpg call is `#[cfg(target_os = "linux")]`; the guest is Linux, so it always runs there.

Lab use (Thu): the experiment is "start `sh -c 'sleep 300 & setsid sleep 300 & wait'` with a short timeout, then count
what survives inside the guest". Prediction first.

Ritika's explain-back (2026-10-26): SIGKILL to the whole group can't be ignored, so a command that ignores SIGTERM
still stops (the advantage: a guaranteed stop, the agent never hangs on it); the trade-off is that it gets no time to
clean up temp data or save files it was working on. Exit codes: 124 = killed by the timeout, 129 = killed because the
client disconnected.

## Tue 2026-10-27 · CUA: how does CUA run and stop work in a sandbox? (hands-on, Ritika at the keyboard)

cua 0.9.0, cua-sandbox 0.9.1, macOS 26.6.2, Docker Desktop (runc). OBSERVED unless marked.

The planned question (does `cua sb exec` kill the command's whole process group on Ctrl-C?) did not run: on Docker Desktop
4.41.2 every create failed. What we measured instead is the same question one level up: **what happens to a sandbox
when its create is stopped?**

1. **Ctrl-C during create cleans up.** `cua sb create … --wait tcp:web`, Ctrl-C while it waits: `Cancelling... cua:
   cancelled: removed t4`, exit code 130 (128 + SIGINT); the container is gone. The CLI catches Ctrl-C itself and asks
   to cancel the create and delete what it made (SOURCE: `cua-cli/src/sandbox.rs`, `cancel_create`).
2. **A timeout during create does not.** Same flags with `--ready-timeout 20`: exit code 1 after 25 s, and the container
   keeps running; `cua sb list` calls it `ready`, `cua sb exec` says `not found`. CUA's docs promise "a failed create
   deletes it" (`--keep-on-failure` reference). SOURCE (INFERENCE for the path taken): the readiness error from the
   Docker layer leaves the upper layer's create before its cleanup block.
3. **Two records of one sandbox.** Docker's container (with `cua.sandbox.name` labels) and CUA's own record
   (`~/.cua/sandboxes`, written last). A create that fails before the record leaves a container `list` shows and
   `exec` / `get` can't reach. `cua sb delete -f` removes it.
4. **Port timing on old Docker Desktop.** On 4.41.2 the published host port appears 5–16 ms after `start` returns
   (5/5, ~1 ms direct-socket looks); CUA reads it once right after start, so creates failed with "probe port 3211 is
   not published". On 4.97.0 it is there at the first look (5/5).

For the lab: a stop request handled by the program that started the work (Ctrl-C → cancel and delete) cleans up; a
failure detected deep inside (a timeout in the Docker layer) returns early and skips cleanup that lives higher up.
Still open: the exec-level kill (process group or not), on a working sandbox.

## Thu 2026-10-29 · CUA: does `cua sb exec` stop the whole command on Ctrl-C? (Ritika at the keyboard)

cua 0.9.0, sandbox `l4` (Docker Desktop 4.97.0; `/bin/sh` in the box = dash). OBSERVED unless marked. Closes Tuesday's
"still open". Predictions #19–#21: `predictions.md`.

**For today** (details; rerun below):
- Run 1, plain: `cua sb exec --timeout 0 l4 'sleep 601 & sleep 602'`, Ctrl-C after ~5 s. Before: `sh` 777 (parent 44 =
  `cua-spacesd`, group 777), `sleep 601` 778, `sleep 602` 779. `cua` exited 130 and printed nothing. 10 s later all
  three still ran, unchanged.
- Run 2, stream: `cua sb exec -i l4 -- sh -c 'sleep 601 & sleep 602'`, Ctrl-C after ~5 s. Before: `sh` 803 (group
  803), `sleep 601` 804, `sleep 602` 805. `cua` exited 130. After: `sh` and `sleep 602` gone; `sleep 601` alive, parent
  1, still group 803. `/proc/804/status` SigIgn `0000000001000006` = ignores SIGINT (2) and SIGQUIT (3); the
  foreground `sleep 602`-style process (779) ignores neither.

**Patterns** (cards in `agent-infra/fundamentals/PATTERNS.md`): P1 a command becomes a family (`sh` + two sleeps);
P4 the agent gives each command its own group, so a group kill was possible; P6 plain exec's Ctrl-C stops only the
client on the Mac; P5 a SIGINT leaves `&` jobs alive; P2 the survivor is adopted by PID 1.

**What it means for the lab:** a stop that reaches the box as a gentle signal and never escalates to SIGKILL on the
group leaves background children behind; plain exec leaves the whole command. Same family as CUA #5588 and the
opposite of smolvm's exec (group SIGKILL on timeout and on disconnect).

**Open (checks, not guesses):** does `-i` send SIGINT to the group or to `sh` only (INFERENCE: group, since the
foreground `sleep 602` died too)? What does "kill the command when this process ends" send, and to whom (UNKNOWN: if
SIGKILL to the group, `sleep 601` could not survive)? Read `cua-cli` exec / `cua-spacesd` source. Whether this is a bug
or intended: `issue-check` on the next CUA day (#5588 bug-family search, Tue Nov 3), dup search first.

Ritika's explain-back (2026-10-29): we tested whether Ctrl-C, a polite stop signal (SIGINT), reaches inside the box.
(1) With plain `cua sb exec`, Ctrl-C only stops the `cua` program on the Mac; nothing reaches the box, so the whole
family keeps running. (2) With `-i`, the stop reaches the box: it kills `sh` and `sleep 602`, while `sleep 601` becomes
an orphan whose parent becomes PID 1, because a program started with `&` in `sh -c` ignores SIGINT. (3) A SIGKILL
instead would stop all of them, since SIGKILL can't be ignored (reasoned, not run).

Rerun:
```bash
cd scratch/2026-10-27-cua-l1-handson   # needs a running sandbox (l4 removed 2026-10-29; create one first)
.venv/bin/cua sb exec -i <name> -- sh -c 'sleep 601 & sleep 602'   # Ctrl-C after ~5 s
docker exec <name> ps -eo pid,ppid,pgid,args | grep -E 'PID|sleep|sh -c'
```

## Thu 2026-10-29 · Composio: what does the remote bash tool do with a command that never ends? (Ritika at the keyboard)

SDK `composio` 0.28.0, `COMPOSIO_REMOTE_BASH_TOOL`, session `trs_w_2dJOcTcII_` (sandbox suffix `i7q3`); script
`scratch/2026-10-21-composio-layer1/step6_l1_bash.py`. OBSERVED unless marked. Predictions #22–#24: `predictions.md`.
Closes L0's Composio UNKNOWN (isolation technology).

**For today:**
- The tool's own description: "Hard 3-minute (180s) execution limit". The SDK's HTTP client gives up at 60 s by
  default (`composio_client` `DEFAULT_TIMEOUT`); the script raised it to 900 s to see Composio's limit, not ours.
- Probe (fresh session): `uname -r` `6.1.158+`; no `/.dockerenv`; PID 1 `/sbin/init` (systemd); PID 2 `[kthreadd]`
  and kernel worker threads in the list; every process 17 s old; 1 CPU, 976 MB, no swap.
- `sleep 601 & sleep 602`: returned at 181.0 s with `result_type=completed`, `error=None`, and stderr "Command did not
  finish within 180s. The workbench aborted the command to keep the sandbox responsive…". The timeout shows only as
  stderr text, not as an error.
- After (same session, ~334 s): `/bin/bash -l -c` gone; `sleep 601` 1701 and `sleep 602` 1702 alive, parent 1
  (`/sbin/init`), group 344 = the group of `envd` (PID 344, the box's agent). Commands run as `/bin/bash -l -c …`
  under `envd`, in `envd`'s own group. (The first look was cut off by the script's 3,000-character print limit; the
  re-read was one read-only `ps` in the same session.)
- Also running (for later, INFERENCE): `envd`, a Jupyter server started by `/root/.jupyter/start-up.sh`, a uvicorn app
  on port 49999, Python and JavaScript kernels, `/mnt/files` mounted from Cloudflare R2 by `s3fs`. `envd` and a Jupyter
  server on 49999 match E2B's code-interpreter sandbox (E2B runs Firecracker microVMs); not confirmed.

**Patterns** (cards in `agent-infra/fundamentals/PATTERNS.md`): P9 the timeout is enforced and something is sent;
P4 inverted: the command shares the agent's group, so a group kill would kill `envd`, and only the parent is stopped;
P2 both sleeps orphaned (`sleep 602` never got a signal); P10 the box has its own kernel (kernel threads, whole machine
17 s old at the first call): a VM (INFERENCE, every clue agrees).

**What it means for the lab:** three agents, three answers to "who kills what": smolvm gives each command its own
group and SIGKILLs it (nothing left); CUA gives its own group but sends only SIGINT, or nothing (`&` jobs or everything
left); Composio leaves the command in the agent's group and stops only the shell (every child left, until the
sandbox ends). A 180 s limit doesn't bound what the command started.

**Open:** which signal Composio sends to `bash` (UNKNOWN; not visible from inside after the fact). How long the
orphans live: until the sandbox is stopped (session lifetime UNKNOWN). Whether it's E2B (INFERENCE above).

Ritika's explain-back (2026-10-29): Composio stopped the command at 180 s by killing the parent `bash` only; `sleep 602`
received no signal at all, and both sleeps became orphans, which we can tell because their PPID became 1 (`/sbin/init`).
The box is a VM: `/sbin/init` is a full startup program as PID 1, there is no `/.dockerenv`, `uname -r` is not a
typical distro kernel name, and the process list shows the kernel's own worker threads, which a container can't see.
