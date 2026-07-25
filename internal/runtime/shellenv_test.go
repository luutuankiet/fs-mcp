package runtime

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func resetSnap() {
	envMu.Lock()
	curSnap = nil
	envMu.Unlock()
}

// TestParseEnvCapture_NulSeparated: markers surrounded by rc noise, NUL
// separators, multiline value preserved, volatile keys stripped.
func TestParseEnvCapture_NulSeparated(t *testing.T) {
	raw := "p10k instant prompt noise\n" + envMarkerStart +
		"PATH=/usr/bin:/opt\x00HOME=/home/u\x00MULTI=line1\nline2\x00PWD=/somewhere\x00SHLVL=3\x00_=/usr/bin/env\x00" +
		envMarkerEnd + "trailing junk"
	env, ok := parseEnvCapture(raw)
	if !ok {
		t.Fatalf("parse failed")
	}
	want := map[string]bool{"PATH=/usr/bin:/opt": false, "HOME=/home/u": false, "MULTI=line1\nline2": false}
	for _, kv := range env {
		if strings.HasPrefix(kv, "PWD=") || strings.HasPrefix(kv, "SHLVL=") || strings.HasPrefix(kv, "_=") {
			t.Errorf("volatile key leaked: %q", kv)
		}
		if _, exists := want[kv]; exists {
			want[kv] = true
		}
	}
	for kv, seen := range want {
		if !seen {
			t.Errorf("missing %q in parsed env %v", kv, env)
		}
	}
}

// TestParseEnvCapture_NewlineFallback: env without -0 support produces
// newline separation; continuation lines that aren't assignments are dropped.
func TestParseEnvCapture_NewlineFallback(t *testing.T) {
	raw := envMarkerStart + "PATH=/bin\nHOME=/h\nnot an assignment line\n2BADKEY=x\n" + envMarkerEnd
	env, ok := parseEnvCapture(raw)
	if !ok {
		t.Fatalf("parse failed")
	}
	for _, kv := range env {
		if kv == "2BADKEY=x" || strings.Contains(kv, "not an assignment") {
			t.Errorf("invalid entry kept: %q", kv)
		}
	}
	if len(env) != 2 {
		t.Errorf("env=%v, want exactly PATH and HOME", env)
	}
}

// TestParseEnvCapture_Failures: missing markers or missing PATH = failed
// capture, so the caller falls back to the server env.
func TestParseEnvCapture_Failures(t *testing.T) {
	if _, ok := parseEnvCapture("no markers at all PATH=/bin"); ok {
		t.Error("parse without markers must fail")
	}
	if _, ok := parseEnvCapture(envMarkerStart + "HOME=/h\x00" + envMarkerEnd); ok {
		t.Error("parse without PATH must fail")
	}
	if _, ok := parseEnvCapture(envMarkerStart + "PATH=\x00" + envMarkerEnd); ok {
		t.Error("empty PATH must count as failed capture")
	}
}

// TestSnapshotStale_RcMtimeChange: touching a tracked rc file invalidates the
// snapshot — this is the zero-restart reload path.
func TestSnapshotStale_RcMtimeChange(t *testing.T) {
	dir := t.TempDir()
	rc := filepath.Join(dir, ".zshrc")
	if err := os.WriteFile(rc, []byte("export X=1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	s := &envSnapshot{taken: time.Now(), ok: true, rcMtimes: map[string]int64{rc: rcMtime(rc)}}
	if s.stale() {
		t.Fatal("fresh snapshot must not be stale")
	}
	future := time.Now().Add(2 * time.Second)
	if err := os.Chtimes(rc, future, future); err != nil {
		t.Fatal(err)
	}
	if !s.stale() {
		t.Fatal("rc mtime change must mark snapshot stale")
	}
}

// TestSnapshotStale_RcCreated: an rc file that did not exist at capture time
// but appears later must also invalidate.
func TestSnapshotStale_RcCreated(t *testing.T) {
	dir := t.TempDir()
	rc := filepath.Join(dir, ".zshenv")
	s := &envSnapshot{taken: time.Now(), ok: true, rcMtimes: map[string]int64{rc: rcMtime(rc)}}
	if s.stale() {
		t.Fatal("absent rc, fresh snapshot: not stale")
	}
	if err := os.WriteFile(rc, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if !s.stale() {
		t.Fatal("rc creation must mark snapshot stale")
	}
}

// TestSnapshotStale_TTL: healthy snapshots expire at snapshotTTL, failed ones
// retry at failRetryTTL.
func TestSnapshotStale_TTL(t *testing.T) {
	s := &envSnapshot{taken: time.Now().Add(-snapshotTTL - time.Minute), ok: true}
	if !s.stale() {
		t.Error("healthy snapshot past TTL must be stale")
	}
	f := &envSnapshot{taken: time.Now().Add(-2 * failRetryTTL), ok: false}
	if !f.stale() {
		t.Error("failed snapshot past retry TTL must be stale")
	}
	fresh := &envSnapshot{taken: time.Now(), ok: true}
	if fresh.stale() {
		t.Error("fresh snapshot must not be stale")
	}
}

// TestResolveShell_Override: FS_MCP_SHELL wins over everything.
func TestResolveShell_Override(t *testing.T) {
	t.Setenv("FS_MCP_SHELL", "sh")
	got := resolveShell()
	if filepath.Base(got) != "sh" {
		t.Errorf("resolveShell=%q, want sh via FS_MCP_SHELL", got)
	}
}

// TestShellEnv_ProvidesPath: integration — whatever shell the host resolves,
// the returned env must carry a non-empty PATH.
func TestShellEnv_ProvidesPath(t *testing.T) {
	resetSnap()
	t.Cleanup(resetSnap)
	shell, env := ShellEnv()
	if shell == "" {
		t.Fatal("empty shell")
	}
	for _, kv := range env {
		if strings.HasPrefix(kv, "PATH=") && len(kv) > len("PATH=") {
			return
		}
	}
	t.Fatalf("no PATH in snapshot env (shell=%s)", shell)
}

// TestRunShell_UsesResolvedShell: integration — $0 inside the command must be
// the resolved user shell, not hardcoded sh.
func TestRunShell_UsesResolvedShell(t *testing.T) {
	resetSnap()
	t.Cleanup(resetSnap)
	shell, _ := ShellEnv()
	res := RunShell(context.Background(), 10*time.Second, "", "echo $0")
	got := strings.TrimSpace(res.Stdout)
	if got == "" {
		t.Fatalf("empty $0; stderr=%q", res.Stderr)
	}
	if !strings.Contains(got, filepath.Base(shell)) && !strings.Contains(shell, got) {
		t.Errorf("$0=%q, want it to reference resolved shell %q", got, shell)
	}
}
