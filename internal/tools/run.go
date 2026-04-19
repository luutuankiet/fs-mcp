package tools

import (
	"context"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

type RunCommandInput struct {
	Command    string `json:"command" jsonschema:"Shell command to execute. Supports pipes, redirects, &&, ||, subshells. Auto-prepended with 'rtk' for token-compressed output (60-90% savings); see Raw flag for the escape hatch."`
	Cwd        string `json:"cwd,omitempty" jsonschema:"Working directory. Defaults to portal root."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 120."`
	Raw        bool   `json:"raw,omitempty" jsonschema:"Skip rtk rewrite and return verbatim shell output. Default false. Auto-set when the command writes to a file (>, >>, &>, tee), so binary or large captures land intact."`
}

type RunCommandOutput struct {
	runtime.Result
	RtkRewrote   bool   `json:"rtk_rewrote"`
	RtkSkippedBy string `json:"rtk_skipped_by,omitempty"`
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
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 120 * time.Second
		}

		cmd, rewrote, skipReason := wrapWithRtk(in.Command, in.Raw)
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
// compression, mirroring the rtk Claude Code hook behavior. Three escape
// hatches in priority order:
//
//  1. Caller passed Raw=true → leave verbatim. ("explicit")
//  2. Command already starts with `rtk ` → don't double-wrap. ("already-rtk")
//  3. Command contains an unquoted `>`, `>>`, `&>`, `2>` file redirect or a
//     `| tee` pipe → leave verbatim so raw bytes hit the file. ("file-write")
//
// rtk has its own per-command passthrough for commands it doesn't know — wrapping
// is always safe.
func wrapWithRtk(command string, raw bool) (string, bool, string) {
	trimmed := strings.TrimSpace(command)
	if trimmed == "" {
		return command, false, ""
	}
	if raw {
		return command, false, "explicit"
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
		Description: "Execute a shell command with pipes/redirects/&&/||. Portal trust: no allowlist, no sandbox. Default: command is wrapped with `rtk` for token-compressed stdout (60-90% savings). Auto-skip when the command writes to a file (>, >>, &>, 2>, | tee) so raw bytes land intact. Pass raw:true to force verbatim output.",
	}, runCommand(cfg))
}
