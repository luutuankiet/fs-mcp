package runtime

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// TestRunShellBackground_QuickCommand verifies the happy path: command
// launches, log file is created, PID is valid, and the log file captures
// stdout after the process exits.
func TestRunShellBackground_QuickCommand(t *testing.T) {
	job, err := RunShellBackground("", "echo hello-bg-mode")
	if err != nil {
		t.Fatalf("RunShellBackground: %v", err)
	}
	if job.JobID == "" || !strings.HasPrefix(job.JobID, "fsmcp-") {
		t.Errorf("JobID=%q, want fsmcp-<hex>", job.JobID)
	}
	if job.PID <= 0 {
		t.Errorf("PID=%d, want >0", job.PID)
	}
	if job.LogPath == "" {
		t.Fatalf("LogPath empty")
	}
	if _, err := os.Stat(job.LogPath); err != nil {
		t.Fatalf("log file missing: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(job.LogPath) })

	// Wait briefly for the echo to complete and flush.
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		data, _ := os.ReadFile(job.LogPath)
		if strings.Contains(string(data), "hello-bg-mode") {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	data, _ := os.ReadFile(job.LogPath)
	t.Fatalf("log never contained expected output; got %q", string(data))
}

// TestRunShellBackground_OutlivesParent verifies the job is in a fresh session
// (setsid) — the child's session id (/proc/<pid>/stat field 6) equals its own
// pid, which is the hallmark of a session leader. This is what makes the job
// survive the mcp call.
func TestRunShellBackground_FreshSession(t *testing.T) {
	// Sleep long enough that we can inspect it before it exits.
	job, err := RunShellBackground("", "sleep 2")
	if err != nil {
		t.Fatalf("RunShellBackground: %v", err)
	}
	t.Cleanup(func() {
		_ = syscall.Kill(job.PID, syscall.SIGKILL)
		_ = os.Remove(job.LogPath)
	})

	// Give the kernel a moment to register the process.
	time.Sleep(100 * time.Millisecond)

	stat, err := os.ReadFile(fmtStat(job.PID))
	if err != nil {
		t.Fatalf("read /proc stat: %v", err)
	}
	sid := parseSessionID(string(stat))
	if sid != job.PID {
		t.Errorf("sid=%d, want %d (process should be session leader after Setsid)", sid, job.PID)
	}
}

// fmtStat returns /proc/<pid>/stat — pulled out so the test reads tidily.
func fmtStat(pid int) string { return "/proc/" + itoa(pid) + "/stat" }

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	neg := false
	if i < 0 {
		neg = true
		i = -i
	}
	buf := make([]byte, 0, 12)
	for i > 0 {
		buf = append([]byte{byte('0' + i%10)}, buf...)
		i /= 10
	}
	if neg {
		buf = append([]byte{'-'}, buf...)
	}
	return string(buf)
}

// parseSessionID pulls field 6 (session id) out of /proc/<pid>/stat. Field 2
// (comm) is wrapped in parens and can contain spaces, so we anchor on the
// trailing `)` before splitting.
func parseSessionID(stat string) int {
	rp := strings.LastIndex(stat, ")")
	if rp == -1 || rp+2 > len(stat) {
		return -1
	}
	fields := strings.Fields(stat[rp+1:])
	// After the `)` the fields are: state(0) ppid(1) pgrp(2) session(3)
	if len(fields) < 4 {
		return -1
	}
	n := 0
	for _, c := range fields[3] {
		if c < '0' || c > '9' {
			return -1
		}
		n = n*10 + int(c-'0')
	}
	return n
}

// TestRunShellBackground_Cwd verifies the command runs in the requested cwd.
func TestRunShellBackground_Cwd(t *testing.T) {
	dir := t.TempDir()
	job, err := RunShellBackground(dir, "pwd")
	if err != nil {
		t.Fatalf("RunShellBackground: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(job.LogPath) })

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		data, _ := os.ReadFile(job.LogPath)
		got := strings.TrimSpace(string(data))
		if got != "" {
			// macOS adds /private prefix to /tmp; accept either.
			wantA, _ := filepath.EvalSymlinks(dir)
			if got == dir || got == wantA {
				return
			}
			t.Fatalf("pwd in log=%q, want %q or %q", got, dir, wantA)
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("log stayed empty")
}

// TestRunShellBackground_NoZombie verifies exited jobs are reaped. Without the
// waiter goroutine, the child lingers in <defunct> state and accumulates —
// over a long mcp session this exhausts PIDs. We check that a quick-exit job
// transitions from Running -> Reaped within ~1s.
func TestRunShellBackground_NoZombie(t *testing.T) {
	job, err := RunShellBackground("", "true")
	if err != nil {
		t.Fatalf("RunShellBackground: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(job.LogPath) })

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		stat, err := os.ReadFile(fmtStat(job.PID))
		if err != nil {
			// /proc/<pid>/stat gone = reaped, as desired.
			return
		}
		if !strings.Contains(string(stat), " Z ") && !strings.Contains(string(stat), " Zs ") {
			// Not zombie yet (still running) — wait.
			time.Sleep(50 * time.Millisecond)
			continue
		}
		// Zombie persisted — reap must not have happened. Give one more beat in
		// case we raced the goroutine.
		time.Sleep(200 * time.Millisecond)
		stat, err = os.ReadFile(fmtStat(job.PID))
		if err != nil {
			return // reaped
		}
		if strings.Contains(string(stat), " Z") {
			t.Fatalf("pid %d stuck in zombie: %s", job.PID, string(stat))
		}
		return
	}
	t.Fatalf("pid %d never exited", job.PID)
}

// TestRunShellBackground_LogCapturesStderr verifies stderr is merged into the
// log file alongside stdout. Important: the whole point of the log is
// "everything the command produced".
func TestRunShellBackground_LogCapturesStderr(t *testing.T) {
	job, err := RunShellBackground("", "echo on-stdout; echo on-stderr 1>&2")
	if err != nil {
		t.Fatalf("RunShellBackground: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(job.LogPath) })

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		data, _ := os.ReadFile(job.LogPath)
		s := string(data)
		if strings.Contains(s, "on-stdout") && strings.Contains(s, "on-stderr") {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	data, _ := os.ReadFile(job.LogPath)
	t.Fatalf("log missing merged streams; got %q", string(data))
}
