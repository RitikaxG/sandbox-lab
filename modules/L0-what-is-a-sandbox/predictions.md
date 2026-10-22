# L0 predictions

Written before each experiment. Result and "right?" filled in after.

| # | Date | Experiment | Prediction (choice + one-line reason) | Result | Right? |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-22 | Docker: median of 10 `docker run --rm alpine true` (image cached, 1 warm-up) | (b) 100–500 ms: "docker container has a shared kernel, it doesn't have to start a kernel every time, containers may share the same image which is already downloaded" | median 203 ms (min 179, max 240; warm-up 2,304) → (b) | yes |
| 2 | 2026-10-22 | smolvm 1.30.1: median of 10 `smolvm machine run --image alpine -- true` (1 warm-up; default per-run registry check) | (c) 0.5–2 s: "smolvm starts a vm with its own kernel, it also checks the image with the registry over the internet, so this one might take longer" | median 4,022 ms (min 3,295, max 4,515; warm-up 6,579) → (d) | no |
| 3 | 2026-10-22 | smolvm 1.30.1: median of 10 `smolvm machine run --seed-digest-ttl 3600 --image alpine -- true` (registry check skipped after the warm-up) | (b) 0.5–2 s: "we saw earlier that kernel boot fits in 0.6 s, so if the image registry check is skipped and that was increasing latency, skipping it will reduce the latency" | median 1,754 ms (min 1,339, max 4,102; run 1 = 4,102 still looks like a full check, cause UNKNOWN; warm-up 6,037) → (b) | yes |
