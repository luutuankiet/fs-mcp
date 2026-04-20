package tools

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

// rtkAvailable reports whether the rtk binary is reachable on PATH. Tests that
// need real rtk behavior skip themselves when rtk is missing, so the suite
// still passes on CI images without rtk installed.
func rtkAvailable(t *testing.T) bool {
	t.Helper()
	_, err := exec.LookPath("rtk")
	return err == nil
}

// TestWrapWithRtk_CompressFalse verifies the explicit opt-out path — agent
// sets compress=false and gets raw passthrough without invoking rtk.
func TestWrapWithRtk_CompressFalse(t *testing.T) {
	in := "git status"
	cmd, rewrote, reason := wrapWithRtk(in, false)
	if cmd != in {
		t.Errorf("cmd=%q, want %q", cmd, in)
	}
	if rewrote {
		t.Error("rewrote=true, want false when compress=false")
	}
	if reason != "compress-false" {
		t.Errorf("reason=%q, want compress-false", reason)
	}
}

// TestWrapWithRtk_Empty verifies an empty string does not hit rtk and returns
// a clean no-skip reason.
func TestWrapWithRtk_Empty(t *testing.T) {
	cmd, rewrote, reason := wrapWithRtk("   ", true)
	if cmd != "   " {
		t.Errorf("cmd=%q, want unchanged", cmd)
	}
	if rewrote || reason != "" {
		t.Errorf("rewrote=%v reason=%q, want false and empty", rewrote, reason)
	}
}

// TestWrapWithRtk_AlreadyRtk verifies the fast-path skip — commands that start
// with `rtk ` or are exactly `rtk` are passed through without invoking the
// subprocess.
func TestWrapWithRtk_AlreadyRtk(t *testing.T) {
	for _, in := range []string{"rtk git status", "  rtk git status  ", "rtk"} {
		cmd, rewrote, reason := wrapWithRtk(in, true)
		if cmd != in {
			t.Errorf("for %q: cmd=%q, want unchanged", in, cmd)
		}
		if rewrote {
			t.Errorf("for %q: rewrote=true, want false", in)
		}
		if reason != "already-rtk" {
			t.Errorf("for %q: reason=%q, want already-rtk", in, reason)
		}
	}
}

// TestWrapWithRtk_SimpleRewrite verifies a basic command gets rtk-wrapped via
// the rtk rewrite subprocess. Skipped when rtk is not installed.
func TestWrapWithRtk_SimpleRewrite(t *testing.T) {
	if !rtkAvailable(t) {
		t.Skip("rtk not on PATH")
	}
	in := "git status"
	cmd, rewrote, reason := wrapWithRtk(in, true)
	if !rewrote {
		t.Errorf("rewrote=false for %q (reason=%q), want true", in, reason)
	}
	if !strings.Contains(cmd, "rtk") {
		t.Errorf("cmd=%q does not contain rtk", cmd)
	}
	if reason != "" {
		t.Errorf("reason=%q, want empty on successful rewrite", reason)
	}
}

// TestWrapWithRtk_CompoundWithBuiltin verifies the bug-fix: commands starting
// with a shell builtin followed by `&&` no longer break. rtk rewrite must
// either rewrite the post-builtin segment or skip (no-op). Either is correct;
// the critical invariant is that we do NOT return `rtk cd /tmp && git status`,
// which is the old broken behavior that tried to exec `cd` as a binary.
func TestWrapWithRtk_CompoundWithBuiltin(t *testing.T) {
	if !rtkAvailable(t) {
		t.Skip("rtk not on PATH")
	}
	in := "cd /tmp && ls"
	cmd, _, _ := wrapWithRtk(in, true)
	if strings.HasPrefix(strings.TrimSpace(cmd), "rtk cd ") {
		t.Errorf("cmd=%q wraps the cd builtin — regression of the old bug", cmd)
	}
}

// TestWrapWithRtk_Unsupported verifies a command rtk cannot rewrite (heredoc,
// arithmetic expansion) returns the original with a no-op skip reason.
// Skipped when rtk is not installed.
func TestWrapWithRtk_Unsupported(t *testing.T) {
	if !rtkAvailable(t) {
		t.Skip("rtk not on PATH")
	}
	in := "echo $((1 + 2))"
	cmd, rewrote, reason := wrapWithRtk(in, true)
	if rewrote {
		t.Errorf("rewrote=true for %q, want false (rtk bails on arithmetic expansion)", in)
	}
	if cmd != in {
		t.Errorf("cmd=%q, want %q", cmd, in)
	}
	if reason != "no-op" {
		t.Errorf("reason=%q, want no-op", reason)
	}
}

// TestWrapWithRtk_Unavailable verifies graceful fallback when rtk is absent.
// We simulate absence by prepending a PATH override to a non-existent dir,
// then restoring. Critical: fs-mcp must never crash or break the command when
// rtk is missing — it must fall back to raw execution with a clear skip code.
func TestWrapWithRtk_Unavailable(t *testing.T) {
	// Point PATH at an empty dir so LookPath("rtk") fails.
	orig := os.Getenv("PATH")
	tmpDir := t.TempDir()
	if err := os.Setenv("PATH", tmpDir); err != nil {
		t.Fatalf("setenv: %v", err)
	}
	t.Cleanup(func() { _ = os.Setenv("PATH", orig) })

	in := "git status"
	cmd, rewrote, reason := wrapWithRtk(in, true)
	if rewrote {
		t.Error("rewrote=true without rtk on PATH, want false")
	}
	if cmd != in {
		t.Errorf("cmd=%q, want %q (should passthrough)", cmd, in)
	}
	if reason != "rtk-unavailable" {
		t.Errorf("reason=%q, want rtk-unavailable", reason)
	}
}
