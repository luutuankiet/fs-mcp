package runtime

import (
	"bytes"
	"context"
	"os/exec"
	"time"
)

type Result struct {
	Stdout    string `json:"stdout"`
	Stderr    string `json:"stderr"`
	ExitCode  int    `json:"exit_code"`
	TimedOut  bool   `json:"timed_out"`
	ElapsedMs int64  `json:"elapsed_ms"`
}

func Run(ctx context.Context, timeout time.Duration, name string, args ...string) Result {
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, name, args...)
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
	if runCtx.Err() == context.DeadlineExceeded {
		res.TimedOut = true
		res.ExitCode = -1
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
	if runCtx.Err() == context.DeadlineExceeded {
		res.TimedOut = true
		res.ExitCode = -1
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
