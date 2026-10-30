package runtime

import (
	"bytes"
	"context"
	"io"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/client"
	"github.com/docker/docker/errdefs"
	"github.com/docker/docker/pkg/stdcopy"
)

// Label put on every container this API creates, so leftovers (orphans) can be found with
// `docker ps -a --filter label=sandbox-lab`.
const (
	LabelOwner     = "sandbox-lab"
	LabelSandboxID = "sandbox-lab.id"
)

// Docker talks to dockerd through Docker's Go library (the Engine SDK, decision 001):
// every method below is one or more HTTP requests on the Docker socket, no `docker` program involved.
type Docker struct {
	cli *client.Client
}

// NewDocker connects to dockerd. It uses DOCKER_HOST when set; otherwise, if the library's default socket
// (/var/run/docker.sock) is missing, it uses Docker Desktop's per-user socket (~/.docker/run/docker.sock).
func NewDocker() (*Docker, error) {
	if os.Getenv("DOCKER_HOST") == "" {
		if _, err := os.Stat("/var/run/docker.sock"); err != nil {
			home, _ := os.UserHomeDir()
			sock := filepath.Join(home, ".docker", "run", "docker.sock")
			if _, err := os.Stat(sock); err == nil {
				os.Setenv("DOCKER_HOST", "unix://"+sock)
			}
		}
	}
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, err
	}
	log.Printf("docker: using %s", cli.DaemonHost())
	return &Docker{cli: cli}, nil
}

// call logs one Docker call: what was asked, how long it took, and the error if any.
// This is the debugging trail decision 001 asks for, since there is no command to paste.
func call(what string, start time.Time, err error) {
	if err != nil {
		log.Printf("docker: %-28s %6d ms  error: %v", what, time.Since(start).Milliseconds(), err)
		return
	}
	log.Printf("docker: %-28s %6d ms", what, time.Since(start).Milliseconds())
}

func (d *Docker) Create(ctx context.Context, spec Spec) (string, error) {
	cfg := &container.Config{
		Image:  spec.Image,
		Cmd:    spec.Cmd,
		Labels: map[string]string{LabelOwner: "1", LabelSandboxID: spec.SandboxID},
	}
	name := "sandbox-" + spec.SandboxID

	// 1. POST /containers/create
	start := time.Now()
	// Decision 002, init line: tini (Docker's --init) runs as PID 1, so SIGTERM to the sandbox isn't dropped
	// and every orphan a command leaves is reaped instead of piling up as a zombie.
	init := true
	hc := &container.HostConfig{Init: &init}
	resp, err := d.cli.ContainerCreate(ctx, cfg, hc, nil, nil, name)
	if errdefs.IsNotFound(err) {
		// The image isn't on this machine yet: pull it once, then retry.
		call("create "+name+" (no image)", start, err)
		if err := d.pull(ctx, spec.Image); err != nil {
			return "", err
		}
		start = time.Now()
		resp, err = d.cli.ContainerCreate(ctx, cfg, hc, nil, nil, name)
	}
	call("create "+name, start, err)
	if err != nil {
		return "", err
	}

	// 2. POST /containers/{id}/start
	start = time.Now()
	err = d.cli.ContainerStart(ctx, resp.ID, container.StartOptions{})
	call("start "+short(resp.ID), start, err)
	if err != nil {
		return resp.ID, err // created but not started: the caller still gets the ID so it can clean up
	}
	return resp.ID, nil
}

func (d *Docker) pull(ctx context.Context, ref string) error {
	start := time.Now()
	rc, err := d.cli.ImagePull(ctx, ref, image.PullOptions{})
	if err == nil {
		_, err = io.Copy(io.Discard, rc) // the pull finishes only when its progress stream is read to the end
		rc.Close()
	}
	call("pull "+ref, start, err)
	return err
}

// pidMarker is the first line the exec wrapper writes to stderr: the command's PID inside the sandbox.
// Docker has no endpoint to signal an exec'd command (POST /exec/{id}/kill, /stop, /signal: 404, decision 002),
// so the API must send signals itself, from a second exec, and needs this number. `docker exec` makes every
// command the leader of its own session and process group, so the PID is also the group to signal.
const pidMarker = "SANDBOX_LAB_PID="

func (d *Docker) Exec(ctx context.Context, runtimeID string, cmd []string, opts ExecOpts) (ExecResult, error) {
	// Docker calls get their own context: when the client goes away (ctx ends), the API still has to
	// talk to Docker to stop the command.
	bg := context.Background()
	res := ExecResult{StoppedBy: StoppedNone, Leaks: []Proc{}}

	// The wrapper prints its PID, then `exec` replaces it with the command: same PID, same group, and the
	// command's own exit code (no shell left in between to change it).
	wrapped := append([]string{"sh", "-c", `printf '` + pidMarker + `%s\n' $$ >&2; exec "$@"`, "sh"}, cmd...)

	// 1. POST /containers/{id}/exec: register the command
	start := time.Now()
	ex, err := d.cli.ContainerExecCreate(bg, runtimeID, container.ExecOptions{
		Cmd: wrapped, AttachStdout: true, AttachStderr: true,
	})
	call("exec-create "+short(runtimeID), start, err)
	if err != nil {
		return res, err
	}

	// 2. POST /exec/{id}/start: run it; stdout and stderr come back mixed on one connection
	start = time.Now()
	att, err := d.cli.ContainerExecAttach(bg, ex.ID, container.ExecAttachOptions{})
	if err != nil {
		call("exec-attach "+short(runtimeID), start, err)
		return res, err
	}
	var stdout, stderr bytes.Buffer
	emit := func(stream string, p []byte) {
		switch {
		case opts.Output != nil:
			opts.Output(stream, p)
		case stream == "stdout":
			stdout.Write(p)
		default:
			stderr.Write(p)
		}
	}
	pidCh := make(chan int, 1)
	done := make(chan error, 1) // the output stream ended: nothing holds the command's stdout/stderr any more
	go func() {
		_, err := stdcopy.StdCopy(
			writerFunc(func(p []byte) { emit("stdout", p) }),
			&pidReader{pid: pidCh, next: func(p []byte) { emit("stderr", p) }},
			att.Reader) // split the mixed stream back into two
		done <- err
	}()

	var timeout <-chan time.Time
	if opts.Timeout > 0 {
		t := time.NewTimer(opts.Timeout)
		defer t.Stop()
		timeout = t.C
	}
	select {
	case err = <-done:
		att.Close()
		call("exec-run "+short(runtimeID), start, err)
		if err != nil {
			return res, err
		}
	case <-timeout:
		res.StoppedBy = StoppedTimeout
	case <-ctx.Done():
		res.StoppedBy = StoppedDisconnect
	}

	if res.StoppedBy != StoppedNone {
		call("exec-run "+short(runtimeID)+" ("+res.StoppedBy+")", start, nil)
		stopStart := time.Now()
		d.stop(bg, runtimeID, pidCh, done, att, opts.Grace)
		res.StopMS = time.Since(stopStart).Milliseconds()
	}

	// Decision 002 step 4, after every exec (Ritika's review): count what is left; report it, don't kill it.
	// A command that ends on its own can leave a child too (`sleep 600 &`).
	procs, err := d.Processes(bg, runtimeID)
	if err != nil {
		return res, err
	}
	for _, p := range procs {
		if !opts.Baseline[p.PID] && !strings.HasPrefix(p.Args, psCmdLine) {
			res.Leaks = append(res.Leaks, p)
		}
	}
	res.Stdout, res.Stderr = stdout.String(), stderr.String()

	// 3. GET /exec/{id}/json: the exit code is only known once the command's own process has ended
	start = time.Now()
	info, err := d.cli.ContainerExecInspect(bg, ex.ID)
	for err == nil && info.Running && time.Since(start) < time.Second {
		time.Sleep(20 * time.Millisecond)
		info, err = d.cli.ContainerExecInspect(bg, ex.ID)
	}
	call("exec-inspect "+short(runtimeID), start, err)
	if err != nil {
		return res, err
	}
	res.ExitCode = info.ExitCode
	return res, nil
}

// stop is decision 002, steps 1-3: SIGTERM the command's group, wait up to the grace period, then always
// SIGKILL the group. It returns once the output stream is closed.
func (d *Docker) stop(ctx context.Context, runtimeID string, pidCh <-chan int, done <-chan error, att types.HijackedResponse, grace time.Duration) {
	var pgid int
	select {
	case pgid = <-pidCh: // the wrapper prints it before anything else runs
	case <-time.After(2 * time.Second):
	}
	if pgid <= 1 {
		log.Printf("docker: stop %s: no PID from the command; closing its output only", short(runtimeID))
		att.Close()
		<-done
		return
	}

	// 1. SIGTERM to the group
	d.signal(ctx, runtimeID, "TERM", pgid)

	// 2. Wait up to the grace period. The stream ending early means every process holding the
	//    command's output is gone, so there is nothing left to wait for.
	streamDone := false
	select {
	case <-done:
		streamDone = true
	case <-time.After(grace):
	}

	// 3. Always SIGKILL the group: SIGTERM can be ignored, and children inherit the ignore (P13).
	//    On an empty group it does nothing.
	d.signal(ctx, runtimeID, "KILL", pgid)

	if !streamDone {
		// A process that left the group (setsid, P16) can still hold the output open; don't wait on it.
		select {
		case <-done:
		case <-time.After(500 * time.Millisecond):
			att.Close()
			<-done
		}
	}
	att.Close()
}

// signal sends sig to every process in group pgid, from a second exec inside the sandbox.
func (d *Docker) signal(ctx context.Context, runtimeID, sig string, pgid int) {
	start := time.Now()
	_, err := d.run(ctx, runtimeID, []string{"sh", "-c", "kill -" + sig + " -" + strconv.Itoa(pgid)})
	call("signal "+sig+" -"+strconv.Itoa(pgid)+" "+short(runtimeID), start, err)
}

// psCmdLine is how the process listing shows up in its own output; it is never a leak.
const psCmdLine = "ps -o pid,ppid,pgid,sid,stat,args"

func (d *Docker) Processes(ctx context.Context, runtimeID string) ([]Proc, error) {
	start := time.Now()
	out, err := d.run(ctx, runtimeID, strings.Fields(psCmdLine))
	call("processes "+short(runtimeID), start, err)
	if err != nil {
		return nil, err
	}
	return parsePS(out), nil
}

// run executes a short helper command (kill, ps) and returns its stdout once it has ended.
func (d *Docker) run(ctx context.Context, runtimeID string, cmd []string) (string, error) {
	ex, err := d.cli.ContainerExecCreate(ctx, runtimeID, container.ExecOptions{Cmd: cmd, AttachStdout: true, AttachStderr: true})
	if err != nil {
		return "", err
	}
	att, err := d.cli.ContainerExecAttach(ctx, ex.ID, container.ExecAttachOptions{})
	if err != nil {
		return "", err
	}
	defer att.Close()
	var out bytes.Buffer
	_, err = stdcopy.StdCopy(&out, io.Discard, att.Reader)
	return out.String(), err
}

func (d *Docker) Delete(ctx context.Context, runtimeID string) error {
	// DELETE /containers/{id}?force=true: kills it if running, then removes it
	start := time.Now()
	err := d.cli.ContainerRemove(ctx, runtimeID, container.RemoveOptions{Force: true})
	call("remove "+short(runtimeID), start, err)
	if errdefs.IsNotFound(err) {
		return nil // already gone: deleting twice is fine
	}
	return err
}

func short(id string) string {
	if len(id) > 12 {
		return id[:12]
	}
	return id
}

var _ Runtime = (*Docker)(nil)
