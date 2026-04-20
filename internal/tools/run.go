package tools

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

type RunCommandInput struct {
	Command    string `json:"command" jsonschema:"Shell command to execute. Supports pipes, redirects, &&, ||, subshells. Output is rtk-compressed by default (60-90% token savings, recommended). Use compress=false only when downstream consumes bytes literally."`
	Cwd        string `json:"cwd,omitempty" jsonschema:"Working directory. Defaults to portal root."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 120."`
	Compress   *bool  `json:"compress,omitempty" jsonschema:"Compress output via rtk (default true — keep enabled for token efficiency). Set false ONLY when downstream consumes bytes literally: diff, sha256sum, jq -r, scripts parsing fixed format. Human-readable output: leave enabled."`
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

		compress := true
		if in.Compress != nil {
			compress = *in.Compress
		}

		cmd, rewrote, skipReason := wrapWithRtk(in.Command, compress)
		res := runtime.RunShell(ctx, timeout, cwd, cmd)
		out := RunCommandOutput{
			Result:       res,
			RtkRewrote:   rewrote,
			RtkSkippedBy: skipReason,
		}
		return nil, out, nil
	}
}

// wrapWithRtk delegates the wrap decision to `rtk rewrite` — the same source
// of truth the Claude Code rtk hook uses. rtk handles tokenization of compound
// commands (`&&`, `||`, `;`, `|`), shell builtins, heredocs, and per-tool
// pipe-compatibility rules. fs-mcp does not re-implement a shell lexer.
//
// fs-mcp diverges from rtk's Claude Code integration in two ways:
//
//  1. Permission exit codes (rtk's 2/3) are ignored — fs-mcp is a portal with
//     full-trust semantics (no allowlist, no sandbox). Host operator policy,
//     not fs-mcp, governs what runs on the host.
//  2. An explicit `compress=false` input skips rtk entirely — the documented
//     escape hatch for cases where downstream consumes bytes literally
//     (diff, jq -r, sha256sum, scripts parsing fixed-format stdin).
func wrapWithRtk(command string, compress bool) (string, bool, string) {
	if !compress {
		return command, false, "compress-false"
	}
	trimmed := strings.TrimSpace(command)
	if trimmed == "" {
		return command, false, ""
	}
	// Fast path: already wrapped. rtk rewrite handles this too, but skipping
	// the subprocess is cheap courtesy.
	if strings.HasPrefix(trimmed, "rtk ") || trimmed == "rtk" {
		return command, false, "already-rtk"
	}

	var stdout bytes.Buffer
	c := exec.Command("rtk", "rewrite", command)
	c.Stdout = &stdout
	err := c.Run()
	if err != nil {
		var execErr *exec.Error
		if errors.As(err, &execErr) && errors.Is(execErr, exec.ErrNotFound) {
			return command, false, "rtk-unavailable"
		}
		// Non-zero exit from rtk is still informative — stdout holds the
		// rewrite if rtk produced one (exit 3 = rewrite-with-ask). Fall through.
	}
	rewritten := strings.TrimSpace(stdout.String())
	if rewritten == "" || rewritten == command {
		return command, false, "no-op"
	}
	return rewritten, true, ""
}

func RegisterRunCommand(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "run_command",
		Description: "Execute a shell command with pipes/redirects/&&/||. Portal trust: no allowlist, no sandbox. Output is rtk-compressed by default for 60-90% token savings — keep enabled. Set `compress=false` ONLY when downstream consumes bytes literally (diff, sha256sum, jq -r, scripts parsing fixed format); for human-readable output, leave enabled. Set `background=true` to spawn long-running jobs detached — returns {job_id, pid, log_path} immediately and the job survives the tool call.",
	}, runCommand(cfg))
}
