# sandbox-lab

A small, E2B-shaped sandbox control plane, built to learn agent infrastructure by deciding, breaking and
measuring: an API that gives AI agents their own isolated computer (Docker first, then smolvm microVMs),
keeps working when things crash, and knows its own limits.

**Who did what:** design decisions, predictions, experiments and analysis by Ritika Gupta; code written by
Claude (Anthropic) to her decision records in `decisions/`.

## How each module works

1. See it: look inside a real system first.
2. Question: the failure this module is about.
3. Learn the options from the best sources (`modules/*/sources.md`).
4. Decide: a decision record in `decisions/`.
5. Build (Claude), then a decision review (Ritika).
6. Predict, then break: predictions are written before every experiment (`modules/*/predictions.md`).
7. Measure, then scale it on a simulated runtime.
8. Flip the decision and measure the option that was rejected.
9. Postmortem in `postmortems/`.

## Modules

| # | Module | Status |
| --- | --- | --- |
| L0 | What is a sandbox? | in progress |
| L1 | Commands and processes | — |
| L2 | State that survives | — |
| L3 | Reconciler, leases, cleanup | — |
| L4 | Desktop sandbox and an agent | — |
| L5 | Observability and load | — |
| L6 | Warm pools and cold start | — |
| L7 | Isolation: smolvm | — |
| L8 | Nodes, scheduling, quotas | — |
| L9 | Durable runs and deploys | — |
| L10 | Defend it | — |

## Results

Measured numbers live in `results/`, one file per experiment, with the machine they ran on.
