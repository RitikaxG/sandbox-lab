package runtime

import (
	"bytes"
	"context"
	"errors"
	"log"
	"os/exec"
	"strings"
	"time"
)

// DockerCLI is option A of decision 001, kept for the flip (module loop step 8): every method starts the real
// `docker` program, as if typed in a terminal, and reads what it prints. Same behaviour as Docker (the SDK one).
type DockerCLI struct{}

func NewDockerCLI() (*DockerCLI, error) {
	if _, err := exec.LookPath("docker"); err != nil {
		return nil, err
	}
	log.Printf("docker-cli: using the docker program on PATH")
	return &DockerCLI{}, nil
}

// run starts `docker args...`, waits for it, and logs the call like the SDK runtime does.
func (d *DockerCLI) run(ctx context.Context, args ...string) (stdout, stderr string, err error) {
	var out, errOut bytes.Buffer
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdout, cmd.Stderr = &out, &errOut
	start := time.Now()
	err = cmd.Run()
	call("cli docker "+args[0], start, err)
	return out.String(), errOut.String(), err
}

func (d *DockerCLI) Create(ctx context.Context, spec Spec) (string, error) {
	// `docker run -d` = create + start in one program run; it prints the new container's ID.
	args := []string{"run", "-d", "--init", // decision 002, init line
		"--name", "sandbox-" + spec.SandboxID,
		"--label", LabelOwner + "=1",
		"--label", LabelSandboxID + "=" + spec.SandboxID,
		spec.Image}
	args = append(args, spec.Cmd...)
	out, errOut, err := d.run(ctx, args...)
	if err != nil {
		return "", errors.New(strings.TrimSpace(errOut))
	}
	return strings.TrimSpace(out), nil // the ID is the printed text, cut out of stdout
}

// Exec runs the command with no stop: decision 002's stop is built on the SDK runtime only. This runtime stays
// for decision 001's flip, which needs create and delete.
func (d *DockerCLI) Exec(ctx context.Context, runtimeID string, cmd []string, opts ExecOpts) (ExecResult, error) {
	if opts.Timeout > 0 {
		return ExecResult{}, errors.New("timeout and stop (decision 002) need -runtime docker")
	}
	out, errOut, err := d.run(ctx, append([]string{"exec", runtimeID}, cmd...)...)
	res := ExecResult{Stdout: out, Stderr: errOut, StoppedBy: StoppedNone, Leaks: []Proc{}}
	if opts.Output != nil {
		opts.Output("stdout", []byte(out))
		opts.Output("stderr", []byte(errOut))
		res.Stdout, res.Stderr = "", ""
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		// docker passes the command's exit code on as its own; 125-127 mean docker itself failed.
		res.ExitCode = exitErr.ExitCode()
		return res, nil
	}
	return res, err
}

func (d *DockerCLI) Processes(ctx context.Context, runtimeID string) ([]Proc, error) {
	out, errOut, err := d.run(ctx, append([]string{"exec", runtimeID}, strings.Fields(psCmdLine)...)...)
	if err != nil {
		return nil, errors.New(strings.TrimSpace(errOut))
	}
	return parsePS(out), nil
}

func (d *DockerCLI) Delete(ctx context.Context, runtimeID string) error {
	_, errOut, err := d.run(ctx, "rm", "-f", runtimeID)
	if err != nil && strings.Contains(errOut, "No such container") {
		return nil // already gone: recognised only by matching the printed message
	}
	if err != nil {
		return errors.New(strings.TrimSpace(errOut))
	}
	return nil
}

var _ Runtime = (*DockerCLI)(nil)
