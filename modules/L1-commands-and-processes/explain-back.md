# L1 explain-back (2026-10-31, end of L1 day 2)

Ritika explained without notes; Claude checked and cross-questioned the weakest answer (OPERATING §2).

## Her answers, with the checks

1. **The stop path (timeout).** Right: SIGTERM to the command's group, wait up to 2 s, SIGKILL always (to an empty
   group if SIGTERM worked), then the leftover count, where a `setsid` escapee shows up as a leak. Fixed: the exit
   code is 143 when SIGTERM ended `sh` (breaks 2, 3), 137 only when SIGTERM was ignored (break 1); the 2 s wait ends
   early when the output closes.
2. **"Looks finished, isn't" (no-`wait` run).** First answer said SIGKILL ended `sh`; wrong. After the
   cross-question: exit 0 means `sh` ended on its own, normally, at about 1 ms, before any signal; what kept the call
   open was its children still holding copies of the output (`sleep 3601`, and `sleep 3600` too), so our 1 s timeout
   fired before Docker's 2 s cut. (Claude's question said the stop took "about 2 s"; it was 1,057 ms, the call 2.1 s.)
3. **Fork bomb.** Right: with no limit it used up the VM's process slots and memory; `pids.max` 1,000 keeps it inside
   one cgroup so other sandboxes and Docker work. Fixed: `docker rm -f` asks Docker to kill the container (no exec
   inside); Docker itself couldn't work, so Docker Desktop (the VM) was restarted, not a container. Missed: what the
   limit doesn't fix (the bomb runs on inside, the stop never runs, our helpers there can't start: #41).
4. **G4 and `kill -KILL -1`.** Right on D: the main program dies, `tini` exits, the sandbox ends, no exec is possible
   (fix: the kernel, not Docker, kills the rest when PID 1 exits). Missed at first, then asked: what happens to
   `npm run dev &` in `sh -c 'npm run dev & npm test'`. Answer worked through: when `npm test` ends normally, no
   timeout fires, so no group signal is sent at all; `npm run dev` holds the output until Docker's 2 s cut, then the
   leftover count finds it as created by this exec, and G4 kills it unless `keep_leftovers: true`.

## Weak spot for next time

Chains of two or three mechanisms ("who ended it, when, and what kept the call open"), not single mechanisms. Same
spot as the prediction misses on #39 Q1/Q5, #40 Q1, #41 Q1, #42 Q6.
