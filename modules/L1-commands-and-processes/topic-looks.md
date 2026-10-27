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
