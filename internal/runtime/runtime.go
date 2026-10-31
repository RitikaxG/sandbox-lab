// Package runtime is the part of the sandbox API that makes real sandboxes.
// Docker is the first runtime (decision 001); smolvm joins behind the same interface in L7.
package runtime

import (
	"context"
	"io"
	"time"
)

// Spec is what a caller asks for when creating a sandbox.
type Spec struct {
	SandboxID string   // our ID, also stored on the container as a label
	Image     string   // e.g. "alpine"
	Cmd       []string // the sandbox's main program; tini (PID 1, decision 002) starts it as its child
}

// Proc is one process inside a sandbox, as `ps` shows it there.
type Proc struct {
	PID  int    `json:"pid"`
	PPID int    `json:"ppid"`
	PGID int    `json:"pgid"`
	SID  int    `json:"sid"`
	Stat string `json:"stat"` // Z = zombie: dead, not reaped yet
	Args string `json:"args"`
}

// ExecOpts says how long a command may run and where its output goes.
type ExecOpts struct {
	Timeout  time.Duration                 // 0 = no time limit; the command is still stopped if ctx ends
	Grace    time.Duration                 // decision 002 step 2: time between SIGTERM and SIGKILL
	Output   func(stream string, p []byte) // called as output arrives ("stdout" or "stderr"); nil = keep it in the result
	Baseline map[int]bool                  // the sandbox's own processes (PIDs seen right after create); never counted as leaks

	// Terminal mode (L1 day 2): the command gets a terminal (a pty) instead of plain pipes. Its stdout and stderr
	// then arrive as one stream, "tty"; keys go in through Input; Resize changes the window size while it runs.
	Sweep bool // decision 002 option D, for the flip: after the command, SIGKILL everything but PID 1

	Tty    bool
	Input  io.Reader      // keys for the terminal; read until it ends
	Size   [2]uint        // the terminal's first [rows, cols]; zero = whatever Docker gives a new pty
	Resize <-chan [2]uint // new [rows, cols] while the command runs
}

// ExecResult is the outcome of running one command inside a sandbox.
type ExecResult struct {
	Stdout   string `json:"stdout,omitempty"` // only when ExecOpts.Output is nil
	Stderr   string `json:"stderr,omitempty"`
	ExitCode int    `json:"exit_code"`
	// Decision 002 step 5: why the command ended, set by the API, not read from the exit code
	// (a command that finishes on its own during the grace period exits 0 too).
	StoppedBy string `json:"stopped_by"` // none, timeout or disconnect
	StopMS    int64  `json:"stop_ms"`    // from the decision to stop until SIGKILL was sent and the command was gone
	// Decision 002 step 4: processes left in the sandbox after the command (every exec, not only a stop) that
	// aren't the sandbox's own
	// (e.g. a child that left the group with setsid). Reported, not killed.
	Leaks []Proc `json:"leaks"`
	// Option D's sweep (ExecOpts.Sweep, for the flip only): what the sweep killed, and a note if the sandbox
	// could not be read after it.
	Swept     []Proc `json:"swept,omitempty"`
	SweepNote string `json:"sweep_note,omitempty"`
}

const (
	StoppedNone       = "none"
	StoppedTimeout    = "timeout"
	StoppedDisconnect = "disconnect"
)

// Runtime creates, runs commands in, and deletes sandboxes.
type Runtime interface {
	// Create makes and starts a sandbox; it returns the runtime's own ID for it (the container ID).
	Create(ctx context.Context, spec Spec) (string, error)
	// Exec runs cmd inside the sandbox until it ends, its timeout passes, or ctx ends (the client went away).
	// On a timeout or ctx ending it stops the command as decision 002 says.
	Exec(ctx context.Context, runtimeID string, cmd []string, opts ExecOpts) (ExecResult, error)
	// Processes lists every process inside the sandbox.
	Processes(ctx context.Context, runtimeID string) ([]Proc, error)
	// Delete stops and removes the sandbox. Deleting one that is already gone is not an error.
	Delete(ctx context.Context, runtimeID string) error
}
