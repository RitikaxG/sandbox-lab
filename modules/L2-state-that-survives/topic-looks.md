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

## Tue 2026-11-03 · CUA: when CUA restarts, how does it rebuild its list of sandboxes, and what does it do with a container it has no record of?

Source: trycua/cua main `4715a723a` (= `cua` 0.10.1 era). SOURCE-VERIFIED unless marked. Plus `ps` and `ls ~/.cua` on
this Mac, and `cua daemon --help` from `cua` 0.10.1.

1. **No daemon runs for `cua sb` on this Mac.** No `cua daemon` process, no `~/.cua/daemon.json` or `cua.sock`, no
   Cua Spaces app (only `CuaDriver.app`) (OBSERVED). Every `cua sb ...` command is a fresh program: it reads disk,
   asks Docker, answers, exits. Nothing lives in memory between commands, so the lab API's L0 failure (in-memory list
   lost on restart) can't happen here; every command already rebuilds from scratch. A daemon exists only when
   started: `cua daemon start` (background by default, `--foreground` for a service manager; socket `~/.cua/cua.sock`);
   with one running, `cua sb` goes through it unless `--embedded` (help text, `cua` 0.10.1).
2. **Two sources of truth.** CUA's record: one file per sandbox in `~/.cua/sandboxes/` (`cua-sandbox-core/src/state.rs:175`;
   runtime chosen, saved ports, size, status). Docker's containers carrying CUA's labels `ai.cua.managed=true` and
   `cua.sandbox.name=<name>` (`cua-vmm/src/container/mod.rs:44`, `:61`). A create starts the container first and
   writes the record last, so a create that stops in between leaves a container with no record (#6086: readiness
   check failed, early return before the record write). A fresh-program design loses data by a write that never
   happened, not by lost memory.
3. **`cua sb list` merges both** (`sandbox.rs:1671`): (1) a row per record, with the recorded status; (2) a record
   with no container in Docker's list → ask Docker by name; definite not-found → `missing` (kept "so `ls` shows the
   stale record and `rm` clears it"); Docker unreachable → recorded status stays; (3) every labelled container → a row
   with Docker's live status, overwriting the record's, and added even with no record. Docker wins on status.
4. **Other commands trust one source.** `exec` / `get`: the record only → a container without a record is `not
   found`, exit 3 (OBSERVED #6086). `delete`: record first; no record → asks the runtime to delete by name
   (`sandbox.rs:2196`, "an orphan the local runtime still lists"; OBSERVED `delete -f t2` rc=0). `cua daemon reap`:
   "End the VMs nobody uses: … a VM nothing records" (help text only; code UNREAD, check Thu).
   **Answer to the question:** an unrecorded container is shown, refused, and left to `delete` or `reap`; never
   adopted back into a record. Pattern card P8 (two records of one thing drift apart).

Compared with smolvm (Mon): smolvm has one database and re-checks only `running`; CUA has no database of its own for
what is running, takes the live status from Docker for every labelled container, and keeps the stale record as `missing`.

Ritika's explain-back (2026-11-03, corrected):
- "Our API lost its sandboxes because it stores everything in memory, lost when the API crashes. On our Mac no such
  daemon runs for `cua sb`, so every `cua sb` is a fresh program: it starts, reads what's on disk, asks Docker and
  answers." (Correction: an in-memory list, not a database; and fresh programs can still lose a record written last.)
- "Docker's list of containers had t2, while the CUA record was not written because the create failed."
- `docker rm -f t3` with the record left: "list shows the stale record; CUA asks Docker about it; if Docker says it
  definitely doesn't exist the row shows missing; rm clears it later; if Docker can't be reached the old status stays."
- Agent after `list` shows `t2 ready`: "exec says not found: sandbox t2, exit 3, since `cua sb exec` only reads the
  CUA record; even though the container was running it couldn't find it. That would confuse the agent: list shows it
  ready, exec finds nothing."

**Lab experiment (Thu, Ritika 2026-11-03):** `cua daemon start --foreground` with `cua` 0.10.1, kill it mid-create
(Ctrl-C and SIGKILL): container, record, `cua sb list`, a second create of the same name; then `cua daemon reap` on
the leftover. Two sandboxes, or zero? Predictions after teaching.

**Open:** does the daemon keep its own in-memory list or re-read records and Docker per call (code UNREAD); `reap`'s
code; whether any command adopts an unrecorded labelled container.
