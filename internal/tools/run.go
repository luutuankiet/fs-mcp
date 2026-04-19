package tools

import (
	"context"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

type RunCommandInput struct {
	Command    string `json:"command" jsonschema:"Shell command to execute. Supports pipes, redirects, &&, ||, subshells. Output is auto-compressed via 'rtk' (60-90% token savings). Escape hatch: redirect to a file (e.g. 'cmd > /tmp/out') and the command runs verbatim — then read the file with read_files."`
	Cwd        string `json:"cwd,omitempty" jsonschema:"Working directory. Defaults to portal root."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 120."`
	Background bool   `json:"background,omitempty" jsonschema:"Run detached and return a job handle immediately. Use for commands that would exceed the tool timeout (docker build/compose, long test suites, migrations, dev servers). Output streams to log_path — poll progress with read_files on that path, or tail live via grep_content. Check PID liveness with 'ps -p <pid>'. RTK compression is skipped (raw log file semantics)."`
}

type RunCommandOutput struct {
	runtime.Result
	RtkRewrote   bool   `json:"rtk_rewrote"`
	RtkSkippedBy string `json:"rtk_skipped_by,omitempty"`
	Background   bool   `json:"background,omitempty"`
	JobID        string `json:"job_id,omitempty"`
	PID          int    `json:"pid,omitempty"`
	LogPath      string `json:"log_path,omitempty"`
}

func runCommand(cfg Config) func(context.Context, *mcp.CallToolRequest, RunCommandInput) (*mcp.CallToolResult, RunCommandOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in RunCommandInput) (*mcp.CallToolResult, RunCommandOutput, error) {
		cwd := in.Cwd
		if cwd == "" {
			cwd = cfg.Root
		} else {
			p, err := cfg.ResolvePath(cwd)
			if err != nil {
				return nil, RunCommandOutput{}, err
			}
			cwd = p
		}

		if in.Background {
			start := time.Now()
			job, err := runtime.RunShellBackground(cwd, in.Command)
			if err != nil {
				return nil, RunCommandOutput{
					Result: runtime.Result{
						ExitCode:  -1,
						Stderr:    err.Error(),
						ElapsedMs: time.Since(start).Milliseconds(),
					},
					Background:   true,
					RtkSkippedBy: "background",
				}, nil
			}
			return nil, RunCommandOutput{
				Result:       runtime.Result{ExitCode: 0, ElapsedMs: time.Since(start).Milliseconds()},
				Background:   true,
				JobID:        job.JobID,
				PID:          job.PID,
				LogPath:      job.LogPath,
				RtkSkippedBy: "background",
			}, nil
		}

		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 120 * time.Second
		}

		cmd, rewrote, skipReason := wrapWithRtk(in.Command)
		res := runtime.RunShell(ctx, timeout, cwd, cmd)
		out := RunCommandOutput{
			Result:       res,
			RtkRewrote:   rewrote,
			RtkSkippedBy: skipReason,
		}
		return nil, out, nil
	}
}

// wrapWithRtk prepends `rtk ` to the user command for transparent token
// compression, mirroring the rtk Claude Code hook. Two skip rules:
//
//  1. Command already starts with `rtk ` → don't double-wrap. ("already-rtk")
//  2. Command contains an unquoted `>`, `>>`, `&>`, `2>` redirect or a
//     `| tee` pipe → leave verbatim so raw bytes hit the file. ("file-write")
//
// File-write detection IS the escape hatch — agents that need uncompressed
// output redirect to a file then read it back with read_files. Removing the
// raw-flag knob keeps the compression contract enforced by default.
func wrapWithRtk(command string) (string, bool, string) {
	trimmed := strings.TrimSpace(command)
	if trimmed == "" {
		return command, false, ""
	}
	if strings.HasPrefix(trimmed, "rtk ") || trimmed == "rtk" {
		return command, false, "already-rtk"
	}
	if hasFileWrite(command) {
		return command, false, "file-write"
	}
	return "rtk " + command, true, ""
}

// hasFileWrite reports whether the command writes raw bytes to a file via
// shell redirect or `tee`. Matches:
//   - `>` / `>>` / `&>` / `2>` redirects to a path (not `>&` stream merges)
//   - `| tee` / `|& tee` pipes
//
// Quote-aware so `"echo > foo"` (the literal string) doesn't trigger.
func hasFileWrite(command string) bool {
	inSingle := false
	inDouble := false
	for i := 0; i < len(command); i++ {
		c := command[i]
		switch c {
		case '\\':
			i++ // skip next char (escaped)
			continue
		case '\'':
			if !inDouble {
				inSingle = !inSingle
			}
		case '"':
			if !inSingle {
				inDouble = !inDouble
			}
		case '>':
			if inSingle || inDouble {
				continue
			}
			// `>&N` is a stream-merge (e.g. `2>&1`), not a file write.
			next := byte(0)
			if i+1 < len(command) {
				next = command[i+1]
			}
			if next == '&' {
				continue
			}
			return true
		case '|':
			if inSingle || inDouble {
				continue
			}
			rest := strings.TrimLeft(command[i+1:], "& \t")
			if strings.HasPrefix(rest, "tee ") || rest == "tee" {
				return true
			}
		}
	}
	return false
}

func RegisterRunCommand(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "run_command",
		Description: "Execute a shell command with pipes/redirects/&&/||. Portal trust: no allowlist, no sandbox. Output is wrapped with `rtk` for token-compressed stdout (60-90% savings). Escape hatch — redirect to a file (`cmd > /tmp/out`, `>>`, `&>`, `2>`, or `| tee`) and the command runs verbatim; then read the file with `read_files`. Set `background=true` to spawn long-running jobs detached — returns {job_id, pid, log_path} immediately and the job survives the tool call.",
	}, runCommand(cfg))
}
