package runtime

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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

// BackgroundJob is the handle returned when a command is launched in the
// background. The process runs in its own session (Setsid), detached from the
// tool's controlling terminal, so it survives the tool call naturally. Output
// streams to LogPath — the caller reads it back via read_files or greps the
// live file with grep_content.
type BackgroundJob struct {
	JobID   string `json:"job_id"`
	PID     int    `json:"pid"`
	LogPath string `json:"log_path"`
}

// pgidAttr puts the child in its own process group so we can kill the entire
// subtree on timeout instead of leaking grandchildren. Without this, a `sleep
// 999 &` inside a timed-out command would survive forever; with it, the post-
// timeout `kill(-pgid, SIGKILL)` reaps every descendant.
var pgidAttr = &syscall.SysProcAttr{Setpgid: true}

// sidAttr creates a NEW session (new pgid + detach from controlling terminal).
// Used for background jobs so they are never reaped by the foreground
// timeout path and outlive the parent mcp call.
var sidAttr = &syscall.SysProcAttr{Setsid: true}

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

// jobDir is the root for background job logs. Each job writes one log file
// named `<job_id>.log`; nothing cleans these up automatically — they are the
// only record of what the detached process produced.
func jobDir() (string, error) {
	d := filepath.Join(os.TempDir(), "fs-mcp-jobs")
	if err := os.MkdirAll(d, 0o755); err != nil {
		return "", err
	}
	return d, nil
}

func newJobID() string {
	b := make([]byte, 4)
	_, _ = rand.Read(b)
	return "fsmcp-" + hex.EncodeToString(b)
}

// RunShellBackground spawns `command` in a fresh session so it outlives the
// current mcp call, streams stdout+stderr into a per-job log file, and returns
// immediately with the handle. The caller polls progress by reading LogPath.
//
// Failure modes: log file can't be created, or the shell can't start. A
// command that fails at runtime (non-zero exit, segfault) is not a launch
// failure — it's visible in the log file and via `ps`.
func RunShellBackground(cwd, command string) (BackgroundJob, error) {
	dir, err := jobDir()
	if err != nil {
		return BackgroundJob{}, fmt.Errorf("job dir: %w", err)
	}
	id := newJobID()
	logPath := filepath.Join(dir, id+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return BackgroundJob{}, fmt.Errorf("open log: %w", err)
	}

	cmd := exec.Command("sh", "-c", command)
	cmd.SysProcAttr = sidAttr
	if cwd != "" {
		cmd.Dir = cwd
	}
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Stdin = nil

	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		_ = os.Remove(logPath)
		return BackgroundJob{}, fmt.Errorf("start: %w", err)
	}

	pid := cmd.Process.Pid
	// Reap in a goroutine so the exited child doesn't become a zombie while
	// fs-mcp stays up. Long-lived server + Release() = zombie accumulation; a
	// blocking Wait() in a goroutine collects the exit status when the job
	// finishes. The goroutine also pins `cmd` in memory so the *os.Process is
	// not GC'd before Wait returns.
	go func() { _ = cmd.Wait() }()
	// logFile stays open for the child — it inherited the fd via Start. Closing
	// our handle does not close the child's copy.
	_ = logFile.Close()

	return BackgroundJob{JobID: id, PID: pid, LogPath: logPath}, nil
}
