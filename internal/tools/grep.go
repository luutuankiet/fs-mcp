package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

type GrepInput struct {
	Pattern    string `json:"pattern" jsonschema:"Regex pattern (ripgrep syntax). Required."`
	Path       string `json:"path,omitempty" jsonschema:"Directory or file to search. Defaults to portal root."`
	Glob       string `json:"glob,omitempty" jsonschema:"Include only files matching this glob (e.g. '*.go', '!vendor/**')."`
	IgnoreCase bool   `json:"ignore_case,omitempty" jsonschema:"Case-insensitive match."`
	Context    int    `json:"context,omitempty" jsonschema:"Lines of before/after context per match."`
	MaxDepth   int    `json:"max_depth,omitempty" jsonschema:"Max directory depth. 0 = unbounded (capped at 4 automatically when searching '/')."`
	FilesOnly  bool   `json:"files_only,omitempty" jsonschema:"Return only paths of matching files, no content."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
}

type GrepMatch struct {
	Path   string   `json:"path"`
	Line   int      `json:"line"`
	Text   string   `json:"text"`
	Before []string `json:"before,omitempty"`
	After  []string `json:"after,omitempty"`
}

type GrepOutput struct {
	Matches   []GrepMatch `json:"matches,omitempty"`
	Files     []string    `json:"files,omitempty"`
	TimedOut  bool        `json:"timed_out"`
	ElapsedMs int64       `json:"elapsed_ms"`
}

func grepTool(cfg Config) func(context.Context, *mcp.CallToolRequest, GrepInput) (*mcp.CallToolResult, GrepOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in GrepInput) (*mcp.CallToolResult, GrepOutput, error) {
		if in.Pattern == "" {
			return nil, GrepOutput{}, fmt.Errorf("pattern is required")
		}
		path := in.Path
		if path == "" {
			path = cfg.Root
		} else {
			p, err := cfg.ResolvePath(path)
			if err != nil {
				return nil, GrepOutput{}, err
			}
			path = p
		}
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 30 * time.Second
		}

		args := []string{
			"--no-follow",
			"--one-file-system",
			"--max-filesize=50M",
			"--threads=2",
		}
		if path == "/" || isNetworkFS(path) {
			maxDepth := in.MaxDepth
			if maxDepth <= 0 || maxDepth > 4 {
				maxDepth = 4
			}
			args = append(args, fmt.Sprintf("--max-depth=%d", maxDepth))
		} else if in.MaxDepth > 0 {
			args = append(args, fmt.Sprintf("--max-depth=%d", in.MaxDepth))
		}
		if in.IgnoreCase {
			args = append(args, "-i")
		}
		if in.Glob != "" {
			args = append(args, "-g", in.Glob)
		}
		if in.Context > 0 {
			args = append(args, fmt.Sprintf("-C%d", in.Context))
		}
		if in.FilesOnly {
			args = append(args, "-l", in.Pattern, path)
			res := runtime.Run(ctx, timeout, "rg", args...)
			out := GrepOutput{TimedOut: res.TimedOut, ElapsedMs: res.ElapsedMs}
			if res.Stdout != "" {
				for _, line := range strings.Split(strings.TrimSpace(res.Stdout), "\n") {
					if line != "" {
						out.Files = append(out.Files, line)
					}
				}
			}
			return nil, out, nil
		}
		args = append(args, "--json", in.Pattern, path)
		res := runtime.Run(ctx, timeout, "rg", args...)
		out := GrepOutput{TimedOut: res.TimedOut, ElapsedMs: res.ElapsedMs}
		parseRgJSON(res.Stdout, &out)
		return nil, out, nil
	}
}

type rgEvent struct {
	Type string `json:"type"`
	Data struct {
		Path struct {
			Text string `json:"text"`
		} `json:"path"`
		Lines struct {
			Text string `json:"text"`
		} `json:"lines"`
		LineNumber int `json:"line_number"`
	} `json:"data"`
}

func parseRgJSON(stdout string, out *GrepOutput) {
	for _, line := range strings.Split(stdout, "\n") {
		if line == "" {
			continue
		}
		var ev rgEvent
		if err := json.Unmarshal([]byte(line), &ev); err != nil {
			continue
		}
		switch ev.Type {
		case "match":
			out.Matches = append(out.Matches, GrepMatch{
				Path: ev.Data.Path.Text,
				Line: ev.Data.LineNumber,
				Text: strings.TrimRight(ev.Data.Lines.Text, "\n"),
			})
		case "context":
			if len(out.Matches) > 0 {
				last := &out.Matches[len(out.Matches)-1]
				if ev.Data.LineNumber < last.Line {
					last.Before = append(last.Before, strings.TrimRight(ev.Data.Lines.Text, "\n"))
				} else {
					last.After = append(last.After, strings.TrimRight(ev.Data.Lines.Text, "\n"))
				}
			}
		}
	}
}

func RegisterGrep(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "grep",
		Description: "Recursive regex search via ripgrep. Symlink-safe at / and network FS (auto --max-depth=4, --no-follow, --one-file-system, --max-filesize=50M, --threads=2).",
	}, grepTool(cfg))
}
