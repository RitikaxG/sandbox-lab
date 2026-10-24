package runtime

import (
	"bytes"
	"context"
	"io"
	"log"
	"os"
	"path/filepath"
	"time"

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
	resp, err := d.cli.ContainerCreate(ctx, cfg, &container.HostConfig{}, nil, nil, name)
	if errdefs.IsNotFound(err) {
		// The image isn't on this machine yet: pull it once, then retry.
		call("create "+name+" (no image)", start, err)
		if err := d.pull(ctx, spec.Image); err != nil {
			return "", err
		}
		start = time.Now()
		resp, err = d.cli.ContainerCreate(ctx, cfg, &container.HostConfig{}, nil, nil, name)
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

func (d *Docker) Exec(ctx context.Context, runtimeID string, cmd []string) (ExecResult, error) {
	// 1. POST /containers/{id}/exec: register the command
	start := time.Now()
	ex, err := d.cli.ContainerExecCreate(ctx, runtimeID, container.ExecOptions{
		Cmd: cmd, AttachStdout: true, AttachStderr: true,
	})
	call("exec-create "+short(runtimeID), start, err)
	if err != nil {
		return ExecResult{}, err
	}

	// 2. POST /exec/{id}/start: run it; stdout and stderr come back mixed on one connection
	start = time.Now()
	att, err := d.cli.ContainerExecAttach(ctx, ex.ID, container.ExecAttachOptions{})
	if err != nil {
		call("exec-attach "+short(runtimeID), start, err)
		return ExecResult{}, err
	}
	var stdout, stderr bytes.Buffer
	_, err = stdcopy.StdCopy(&stdout, &stderr, att.Reader) // split the mixed stream back into two
	att.Close()
	call("exec-run "+short(runtimeID), start, err)
	if err != nil {
		return ExecResult{}, err
	}

	// 3. GET /exec/{id}/json: the exit code is only known after the output ends
	start = time.Now()
	info, err := d.cli.ContainerExecInspect(ctx, ex.ID)
	call("exec-inspect "+short(runtimeID), start, err)
	if err != nil {
		return ExecResult{}, err
	}
	return ExecResult{Stdout: stdout.String(), Stderr: stderr.String(), ExitCode: info.ExitCode}, nil
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
