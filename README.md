# sandbox-lab

A small, E2B-shaped sandbox control plane, built to learn agent infrastructure by deciding, breaking and
measuring: an API that gives AI agents their own isolated computer (Docker first, then smolvm and Firecracker microVMs, on Kubernetes and AWS),
keeps working when things crash, and knows its own limits.

**Focus:** sandbox lifecycle failures: what happens to an agent's processes, its leftovers and its state when
things crash, hang or restart.

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
| L0 | What is a sandbox? | in progress (notes: `modules/L0-what-is-a-sandbox/`) |
| L1 | Commands and processes | — |
| L2 | State that survives | — |
| L3 | Reconciler, leases, cleanup | — |
| L4 | Kubernetes: the reconciler becomes a controller | — |
| L5 | Observability, load, alerts, on-call | — |
| L6 | Warm pools, cold start, snapshots | — |
| L7 | MicroVM isolation: smolvm and Firecracker | — |
| L8 | Desktop sandbox, an agent, evals, transcripts | — |
| L9 | Tenants and auth | — |
| L10 | Nodes and scheduling at scale | — |
| L11 | Real cloud: Terraform, autoscaling, drain | — |
| L12 | Durable runs and deploys | — |

Every experiment reruns from a clean checkout with one command and writes its numbers to `results/`.

## Results

Measured numbers live in `results/`, one file per experiment, with the machine they ran on.
