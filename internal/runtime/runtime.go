// Package runtime is the part of the sandbox API that makes real sandboxes.
// Docker is the first runtime (decision 001); smolvm joins behind the same interface in L7.
package runtime

import "context"

// Spec is what a caller asks for when creating a sandbox.
type Spec struct {
	SandboxID string   // our ID, also stored on the container as a label
	Image     string   // e.g. "alpine"
	Cmd       []string // the sandbox's main process (PID 1); it lives as long as this runs
}

// ExecResult is the outcome of running one command inside a sandbox.
type ExecResult struct {
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	ExitCode int    `json:"exit_code"`
}

// Runtime creates, runs commands in, and deletes sandboxes.
type Runtime interface {
	// Create makes and starts a sandbox; it returns the runtime's own ID for it (the container ID).
	Create(ctx context.Context, spec Spec) (string, error)
	// Exec runs cmd inside the sandbox and waits for it to finish.
	Exec(ctx context.Context, runtimeID string, cmd []string) (ExecResult, error)
	// Delete stops and removes the sandbox. Deleting one that is already gone is not an error.
	Delete(ctx context.Context, runtimeID string) error
}
