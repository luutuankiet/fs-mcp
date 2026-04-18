package tools

import (
	"context"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

type RunCommandInput struct {
	Command    string `json:"command" jsonschema:"Shell command to execute. Supports pipes, redirects, &&, ||, subshells."`
	Cwd        string `json:"cwd,omitempty" jsonschema:"Working directory. Defaults to portal root."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 120."`
}

type RunCommandOutput = runtime.Result

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
		res := runtime.RunShell(ctx, timeout, cwd, in.Command)
		return nil, res, nil
	}
}

func RegisterRunCommand(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "run_command",
		Description: "Execute a shell command with pipes/redirects/&&/||. Portal trust: no allowlist, no sandbox.",
	}, runCommand(cfg))
}
