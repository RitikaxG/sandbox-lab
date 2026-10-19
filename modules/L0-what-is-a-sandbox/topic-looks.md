# L0 topic looks: what is a sandbox?

Reading/hands-on notes from the contributor days (OPERATING §2). The lab uses these as real examples.

## smolvm (Mon 2026-10-19, hands-on, smolvm 1.30.1 on macOS arm64)

Question: what does `machine run`/`start` create on the host, and what isolates it?

- **Processes:** one host process per machine, `smolvm-bin _boot-vm <data-dir>/boot-config.json` (PID 70000, ~14 MB RSS).
  The guest's processes (init as PID 1, nginx master and workers) are invisible to the Mac's `ps` (OBSERVED).
- **Disk:** a per-machine folder `~/Library/Caches/smolvm/vms/<id>/`, owned by the user: sparse disk images
  `storage.raw` (20 GiB apparent) and `overlay.raw` (10 GiB), 78 MB actually used; logs; Unix sockets
  `agent.sock`, `control.sock`, `ports.sock` for host↔guest control (OBSERVED; roles of the sockets from names, INFERENCE).
- **Network:** the guest has its own stack (`eth0` 100.96.0.2/30, own `lo`). `-p 8080:80` → the VM process itself listens
  on host 127.0.0.1:8080 and [::1]:8080 and relays into guest port 80 (OBSERVED). Outbound `--net` goes through virtio-net
  with the VM process opening host sockets (INFERENCE from #1833; not traced).
- **Isolation:** a separate Linux kernel behind hardware virtualization (Hypervisor.framework via libkrun); the workload
  runs in a container inside that guest (PID 1 `container-init`). Deliberate openings: forwarded ports, mounts, `exec`.
- Ritika, in her words: "a process is the vm (smolvm machine) running on mac that has PID 70000 · disk is a folder in
  Mac which has logs, sockets that guest needs for talking to Mac · the vm machine starts a container inside where nginx
  runs. VM uses its own Linux kernel."
- For Thursday: compare with a Docker container (shared kernel; on a Mac, inside Docker Desktop's own VM).
- **Afternoon, pack and branch** (MAP Use log has the numbers): a sandbox is also an *object*. `pack create --from-vm`
  turns a machine into one 37 MB `.smolmachine` (its disk: image layers + changes) plus a 44 MB stub that runs it; a new
  machine starts from it in 0.6 s with no pull. Host-side settings (port 8080) do not travel; the host re-adds them.
  `machine branch` clones a running `--branchable` machine in 0.38 s; the child starts with the parent's state, and its
  writes stay private (copy-on-write) (all OBSERVED). For the lab: "create a sandbox" can mean boot from an image, start
  from a packed file, or branch a live one; each has a different cost to measure.
- Ritika, in her words (pack/branch explain-back, after a 4-piece re-walk): "smolvm sandbox is a vm ( guest machine ) that
  can be copied into another server, it can be branched so that agent can try out different things , it can be a running
  process on your own mac, it gets transferred as a file." Follow-up, on the Mac: "the folder ( the disk ) that contains
  settings , socket , for the process running". What each way carries (her table, corrected together):
  | Way | Disk | RAM | Host settings (ports) |
  | `create --image` | fresh, from the image | no | only what you pass (`-p`) |
  | `create --from` `.smolmachine` | yes, the packed disk | no | no |
  | `branch --from` | yes, shared by CoW | yes, shared by CoW | UNKNOWN (source had no ports; not tested) |
- Mind map of the whole afternoon (Ritika's draft, corrected together): ![pack and branch map](pack-branch-map.png)
  Editable: [pack-branch-map.excalidraw](pack-branch-map.excalidraw) (Excalidraw → menu → Open; it replaces the open canvas).
