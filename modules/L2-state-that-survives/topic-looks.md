# L2 topic looks: where each repo writes down its sandboxes, and what it trusts

Week of 2026-11-02. Question per repo from `agent-infra/lab/CURRENT.md` "This week's topic". Reading only.

## Mon 2026-11-02 · smolvm: where are machine records kept, and what does a record say if the CLI dies mid-start?

Source: smolvm main `ab74dfe7` (v1.33.0). SOURCE-VERIFIED unless marked. Plus one read-only look at the real database
(`sqlite3 -readonly`) and `ps` of the stuck `l1s` VM.

1. **One SQLite file holds every record:** `~/Library/Application Support/smolvm/server/smolvm.db` (WAL mode, 5 s
   busy timeout so several CLIs can share it; `src/db.rs:1–30`). Table `vms`: one row per machine, `name` plus the
   whole record as JSON (`src/db.rs:292`). Table `vm_create_reservations` (`name`, `owner_token`, `owner_pid`,
   `created_at`): "a create of this name is in progress" (empty when looked at).
2. **A record stores a state word and the VM process's identity:** state `created / running / stopped / paused /
   pausing / failed / unreachable` (`src/config.rs:39`; `frozen` is computed, never stored), plus `pid` and
   `pid_start_time` (the start time catches a reused PID). Real rows, 2026-11-02 afternoon:

   | name | state | pid | pid_start_time |
   | --- | --- | --- | --- |
   | `l1s` | running | 66608 | 1793601789573093 |
   | `l0` | stopped | – | – |
   | `drop-safe-44673` | created | – | – |

3. **`running` is written last.** `machine start`: start the VM process → wait for the agent to answer → run the
   workload → only then write `state = running`, `pid`, `pid_start_time` (`src/cli/vm_common.rs` ~2150, "Persist
   running state"). Until that write the record still says `created`.
4. **`running` is re-checked; every other state is trusted.** `machine ls` / `status` resolve each row with
   `resolve_state` (`src/agent/state_probe.rs:41`): stored state not `running` → shown as stored, nothing checked.
   Stored `running` → PID alive with the same start time *and* agent answers a ping → `running`; PID alive, no answer
   → `unreachable`; PID gone (and no answer on the agent socket) → `stopped`.
5. **"running" means "the agent answers a ping", not "it can run commands".** `l1s` (VM started on 1.30.1, its
   install folder deleted by `brew upgrade` to 1.33.0) is listed `running`, while every exec fails with
   `Stale file handle (os error 116)` and `machine stop` refuses (OBSERVED 2026-11-02; Watch lead in
   `agent-infra/repos/smolvm/CURRENT.md`).
6. **The VM process leads its own session.** smolvm starts it and has it call `setsid()` "to become a session leader"
   (`src/process.rs:3979`), so it outlives the CLI. `l1s` now: PID 66608, parent 1, process group 66608 (OBSERVED
   with `ps`). Same mechanism as the exec escapee (#2046), used on purpose here. Pattern card P16.

**What this means for L2 (INFERENCE, to test on the lab day):** if the CLI is killed after the VM process started and
before the `running` write (Ctrl-C, a closed terminal, an agent harness's time limit, SIGKILL), the record stays
`created` with no PID, while the VM process, in its own session, keeps running. `ls` trusts `created` and never
checks, so a live VM is shown as not started. Earlier report of the same shape for `machine run`: smolvm #1193
"Ctrl-C leaves a run's VM alive and invisible to machine list" (closed 2026-09-29; how it was fixed, and whether
`machine start` is covered: UNKNOWN, read the fix).

Ritika's prediction (2026-11-02, before any run): (c) the record says `created` and the VM process is still alive.
Her first reason ("the VM process is PID 1, which ignores Ctrl-C") was corrected: PID 1 is inside the guest
(`init.krun`); the host VM process is an ordinary process, and the likely reason is that it called `setsid()` and is
outside the terminal's process group.

**Lab experiment (Thu):** `machine start` a fresh machine and kill the CLI between "VM process started" and the
`running` write: once with Ctrl-C, once with SIGKILL. Then: `machine ls` state, `ps` for the `_boot-vm` process, the
`vms` row and `vm_create_reservations`, and a second `machine start` of the same name. Two VMs, one, or an error?
(L2's question: two sandboxes, or zero?)

**Open:** what `vm_create_reservations` does when its `owner_pid` is dead (stale reservation cleanup); whether `start`
checks for a live `_boot-vm` before booting another; #1193's fix.
