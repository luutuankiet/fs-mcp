package runtime

import (
	"bytes"
	"context"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

type Result struct {
	Stdout    string `json:"stdout"`
	Stderr    string `json:"stderr"`
	ExitCode  int    `json:"exit_code"`
	TimedOut  bool   `json:"timed_out"`
	ElapsedMs int64  `json:"elapsed_ms"`
}

// pgidAttr puts the child in its own process group so we can kill the entire
// subtree on timeout instead of leaking grandchildren. Without this, a `sleep
// 999 &` inside a timed-out command would survive forever; with it, the post-
// timeout `kill(-pgid, SIGKILL)` reaps every descendant.
var pgidAttr = &syscall.SysProcAttr{Setpgid: true}

// reapGroupOnTimeout wraps the standard timeout-detection branch and SIGKILLs
// the entire process group when the deadline fired. Safe to call after
// cmd.Run() returns — the kernel keeps the group ID alive until the last
// member exits, and signaling already-dead PIDs is a no-op.
func reapGroupOnTimeout(cmd *exec.Cmd, runCtx context.Context, res *Result) bool {
	if runCtx.Err() != context.DeadlineExceeded {
		return false
	}
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	res.TimedOut = true
	res.ExitCode = -1
	return true
}

func Run(ctx context.Context, timeout time.Duration, name string, args ...string) Result {
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, name, args...)
	cmd.SysProcAttr = pgidAttr
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	start := time.Now()
	err := cmd.Run()
	res := Result{
		Stdout:    stdout.String(),
		Stderr:    stderr.String(),
		ElapsedMs: time.Since(start).Milliseconds(),
	}
	if reapGroupOnTimeout(cmd, runCtx, &res) {
		return res
	}
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			res.ExitCode = ee.ExitCode()
		} else {
			res.ExitCode = -1
			if res.Stderr == "" {
				res.Stderr = err.Error()
			}
		}
	}
	return res
}

func RunWithStdin(ctx context.Context, timeout time.Duration, stdin, name string, args ...string) Result {
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, name, args...)
	cmd.SysProcAttr = pgidAttr
	cmd.Stdin = strings.NewReader(stdin)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	start := time.Now()
	err := cmd.Run()
	res := Result{
		Stdout:    stdout.String(),
		Stderr:    stderr.String(),
		ElapsedMs: time.Since(start).Milliseconds(),
	}
	if reapGroupOnTimeout(cmd, runCtx, &res) {
		return res
	}
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			res.ExitCode = ee.ExitCode()
		} else {
			res.ExitCode = -1
			if res.Stderr == "" {
				res.Stderr = err.Error()
			}
		}
	}
	return res
}

func RunShell(ctx context.Context, timeout time.Duration, cwd, command string) Result {
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, "sh", "-c", command)
	cmd.SysProcAttr = pgidAttr
	if cwd != "" {
		cmd.Dir = cwd
	}
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	start := time.Now()
	err := cmd.Run()
	res := Result{
		Stdout:    stdout.String(),
		Stderr:    stderr.String(),
		ElapsedMs: time.Since(start).Milliseconds(),
	}
	if reapGroupOnTimeout(cmd, runCtx, &res) {
		return res
	}
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			res.ExitCode = ee.ExitCode()
		} else {
			res.ExitCode = -1
			if res.Stderr == "" {
				res.Stderr = err.Error()
			}
		}
	}
	return res
}
