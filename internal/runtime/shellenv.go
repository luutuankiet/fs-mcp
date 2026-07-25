package runtime

import (
	"bufio"
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Shell environment snapshot.
//
// run_command historically spawned `sh -c` with the server's own (often
// impoverished) environment: launched from systemd or a supervisor, children
// saw a bare PATH with no version-manager shims (nvm, pyenv, cargo) and even
// $SHELL unset — so `npx` resolved at the user's terminal but not for agents.
//
// Fix: execute commands via the user's login shell with the environment an
// interactive login session of that shell would see. The env is captured once
// by running `<shell> -ilc` with a marker-delimited `env -0` (markers so
// rc-file noise on stdout cannot corrupt parsing) and cached. Every call
// revalidates cheaply — stat the shell's rc files (~µs) — and re-captures only
// when an rc file changed or a TTL expired. Editing ~/.zshrc therefore takes
// effect on the very next command, with no server restart.
//
// Failure is never fatal: when capture times out or parses badly, the
// server's own environment is used and the capture retried on a shorter TTL.
// In-flight commands are unaffected by a refresh — the env is copied into the
// child at exec time, so swapping the cache is always safe.

const (
	envMarkerStart = "__FSMCP_ENV_START__"
	envMarkerEnd   = "__FSMCP_ENV_END__"

	// snapshotTTL bounds staleness from files we cannot track: rc files
	// source arbitrary others (nvm.sh, plugin managers), so a change invisible
	// to the mtime check still converges within this window.
	snapshotTTL = 15 * time.Minute
	// failRetryTTL retries a failed capture sooner than a healthy one expires,
	// without hammering a broken shell on every single call.
	failRetryTTL = time.Minute
	// captureTimeout bounds the one-off interactive shell startup. Generous
	// vs any sane rc file; a hung plugin degrades to the server env.
	captureTimeout = 5 * time.Second
)

type envSnapshot struct {
	shell    string
	env      []string
	rcMtimes map[string]int64 // rc path -> mtime unixnano; 0 = absent
	taken    time.Time
	ok       bool // last capture parsed successfully
}

var (
	envMu   sync.Mutex // guards curSnap; also serializes refresh (singleflight)
	curSnap *envSnapshot
)

// ShellEnv returns the user's login shell and the cached interactive-login
// environment, refreshing first when the snapshot has gone stale. Callers
// should invoke this BEFORE starting any command timeout clock — a refresh
// can block up to captureTimeout.
func ShellEnv() (shell string, env []string) {
	envMu.Lock()
	defer envMu.Unlock()
	if curSnap == nil || curSnap.stale() {
		curSnap = captureSnapshot(resolveShell())
	}
	return curSnap.shell, curSnap.env
}

// ShellEnvInfo reports the active snapshot for diagnostics: resolved shell,
// snapshot age, and whether the last capture succeeded. Zero values mean no
// snapshot has been taken yet.
func ShellEnvInfo() (shell string, age time.Duration, ok bool) {
	envMu.Lock()
	defer envMu.Unlock()
	if curSnap == nil {
		return "", 0, false
	}
	return curSnap.shell, time.Since(curSnap.taken), curSnap.ok
}

func (s *envSnapshot) stale() bool {
	ttl := snapshotTTL
	if !s.ok {
		ttl = failRetryTTL
	}
	if time.Since(s.taken) > ttl {
		return true
	}
	for p, m := range s.rcMtimes {
		if rcMtime(p) != m {
			return true
		}
	}
	return false
}

func rcMtime(p string) int64 {
	fi, err := os.Stat(p)
	if err != nil {
		return 0
	}
	return fi.ModTime().UnixNano()
}

// resolveShell picks the user's shell: explicit FS_MCP_SHELL override, then
// $SHELL, then the /etc/passwd login shell, then plain sh. Each candidate
// must actually exist to win.
func resolveShell() string {
	if s := os.Getenv("FS_MCP_SHELL"); s != "" {
		if p, err := exec.LookPath(s); err == nil {
			return p
		}
	}
	if s := os.Getenv("SHELL"); s != "" {
		if p, err := exec.LookPath(s); err == nil {
			return p
		}
	}
	if s := passwdShell(); s != "" {
		if _, err := os.Stat(s); err == nil {
			return s
		}
	}
	return "sh"
}

// passwdShell reads the current uid's login shell from /etc/passwd. os/user
// does not expose the shell field, so we parse the line ourselves.
func passwdShell() string {
	uid := strconv.Itoa(os.Getuid())
	f, err := os.Open("/etc/passwd")
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		parts := strings.Split(sc.Text(), ":")
		if len(parts) >= 7 && parts[2] == uid {
			return parts[6]
		}
	}
	return ""
}

// rcFiles lists the top-level rc files whose mtimes gate a re-capture. Files
// they transitively source are covered by snapshotTTL instead.
func rcFiles(shell string) []string {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil
	}
	var names []string
	switch filepath.Base(shell) {
	case "zsh":
		names = []string{".zshenv", ".zprofile", ".zshrc", ".zlogin"}
	case "bash":
		names = []string{".bash_profile", ".bash_login", ".bashrc", ".profile"}
	default:
		names = []string{".profile"}
	}
	out := make([]string, 0, len(names))
	for _, n := range names {
		out = append(out, filepath.Join(home, n))
	}
	return out
}

func captureSnapshot(shell string) *envSnapshot {
	snap := &envSnapshot{shell: shell, taken: time.Now(), rcMtimes: map[string]int64{}}
	for _, p := range rcFiles(shell) {
		snap.rcMtimes[p] = rcMtime(p)
	}
	if filepath.Base(shell) == "sh" {
		// Plain sh has no user rc worth sourcing interactively; the server
		// env is as good as it gets.
		snap.env = os.Environ()
		snap.ok = true
		return snap
	}
	ctx, cancel := context.WithTimeout(context.Background(), captureTimeout)
	defer cancel()
	// `command env -0` degrades to plain `env` where -0 is unsupported (older
	// BSD userlands); parseEnvCapture handles both separators. `command`
	// bypasses any alias the rc files may have defined.
	capture := "printf '" + envMarkerStart + "'; command env -0 2>/dev/null || command env; printf '" + envMarkerEnd + "'"
	if filepath.Base(shell) == "bash" {
		// Login bash reads the .bash_profile/.profile chain but NOT ~/.bashrc
		// — yet that is where version managers (nvm et al) install their
		// loader. Distro-default profiles chain .bashrc; custom ones often
		// don't. Sourcing it explicitly is idempotent when already chained,
		// and the -i flag satisfies interactive guards inside it.
		capture = "[ -f \"$HOME/.bashrc\" ] && . \"$HOME/.bashrc\" >/dev/null 2>&1; " + capture
	}
	cmd := exec.CommandContext(ctx, shell, "-i", "-l", "-c", capture)
	cmd.SysProcAttr = pgidAttr
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	_ = cmd.Run() // exit code is irrelevant — the markers decide success
	if ctx.Err() == context.DeadlineExceeded && cmd.Process != nil {
		// Interactive shells spawn plugin subprocesses; reap the whole group.
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	if env, ok := parseEnvCapture(stdout.String()); ok {
		snap.env = setEnvVar(env, "SHELL", shell)
		snap.ok = true
	} else {
		snap.env = os.Environ()
		snap.ok = false
	}
	return snap
}

// parseEnvCapture extracts KEY=VALUE pairs from the marker-delimited region
// of the capture output. NUL-separated (env -0) is preferred — it survives
// multiline values; the newline fallback drops continuation lines that do not
// look like assignments. A capture without a non-empty PATH is considered
// failed — that is the one variable the whole feature exists to deliver.
func parseEnvCapture(out string) ([]string, bool) {
	i := strings.Index(out, envMarkerStart)
	j := strings.LastIndex(out, envMarkerEnd)
	if i < 0 || j < 0 || j <= i {
		return nil, false
	}
	body := out[i+len(envMarkerStart) : j]
	var entries []string
	if strings.Contains(body, "\x00") {
		entries = strings.Split(body, "\x00")
	} else {
		entries = strings.Split(body, "\n")
	}
	var env []string
	hasPath := false
	for _, kv := range entries {
		eq := strings.Index(kv, "=")
		if eq <= 0 || !validEnvKey(kv[:eq]) {
			continue
		}
		switch kv[:eq] {
		case "PWD", "OLDPWD", "SHLVL", "_":
			// Volatile per-session state — PWD from the capture shell would
			// contradict the cwd the actual command runs in.
			continue
		}
		if kv[:eq] == "PATH" && eq+1 < len(kv) {
			hasPath = true
		}
		env = append(env, kv)
	}
	if !hasPath {
		return nil, false
	}
	return env, true
}

func validEnvKey(k string) bool {
	if k == "" {
		return false
	}
	for i, c := range k {
		switch {
		case c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'):
		case c >= '0' && c <= '9':
			if i == 0 {
				return false
			}
		default:
			return false
		}
	}
	return true
}

func setEnvVar(env []string, key, val string) []string {
	prefix := key + "="
	for i, kv := range env {
		if strings.HasPrefix(kv, prefix) {
			env[i] = prefix + val
			return env
		}
	}
	return append(env, prefix+val)
}
