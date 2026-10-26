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
