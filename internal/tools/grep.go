package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

var defaultSectionPatterns = []string{
	`^func\s+`,
	`^type\s+\w+`,
	`^\s*(async\s+)?def\s+\w+`,
	`^\s*class\s+\w+`,
	`^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+`,
	`^\s*(export\s+)?(default\s+)?class\s+\w+`,
	`^\s*(export\s+)?interface\s+\w+`,
	`^(pub\s+)?(async\s+)?fn\s+\w+`,
	`^(pub\s+)?(struct|enum|impl|trait|mod)\s+`,
}

type GrepInput struct {
	Pattern         string   `json:"pattern" jsonschema:"Regex pattern (ripgrep syntax). Required."`
	Path            string   `json:"path,omitempty" jsonschema:"Directory or file to search. Defaults to portal root."`
	Glob            string   `json:"glob,omitempty" jsonschema:"Include only files matching this glob (e.g. '*.go', '!vendor/**')."`
	IgnoreCase      bool     `json:"ignore_case,omitempty" jsonschema:"Case-insensitive match."`
	Context         int      `json:"context,omitempty" jsonschema:"Lines of before/after context per match."`
	MaxDepth        int      `json:"max_depth,omitempty" jsonschema:"Max directory depth. 0 = unbounded (capped at 4 automatically when searching '/')."`
	FilesOnly       bool     `json:"files_only,omitempty" jsonschema:"Return only paths of matching files, no content."`
	TimeoutSec      int      `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
	SectionPatterns []string `json:"section_patterns,omitempty" jsonschema:"Regexes used to compute section_end_hint per match (first line at or after the match that matches any pattern). Pass [] to disable. Default covers Go/Python/JS-TS/Rust/C-family boundaries."`
	NoSectionHint   bool     `json:"no_section_hint,omitempty" jsonschema:"Disable section_end_hint computation entirely."`
}

type GrepMatch struct {
	Path           string   `json:"path"`
	Line           int      `json:"line"`
	Text           string   `json:"text"`
	Before         []string `json:"before,omitempty"`
	After          []string `json:"after,omitempty"`
	SectionEndHint int      `json:"section_end_hint,omitempty"`
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
		if !in.NoSectionHint && len(out.Matches) > 0 {
			patterns := in.SectionPatterns
			if patterns == nil {
				patterns = defaultSectionPatterns
			}
			enrichSectionHints(out.Matches, patterns)
		}
		return nil, out, nil
	}
}

func enrichSectionHints(matches []GrepMatch, patterns []string) {
	if len(patterns) == 0 {
		return
	}
	regexes := make([]*regexp.Regexp, 0, len(patterns))
	for _, p := range patterns {
		if r, err := regexp.Compile(p); err == nil {
			regexes = append(regexes, r)
		}
	}
	if len(regexes) == 0 {
		return
	}
	fileLines := map[string][]string{}
	for i := range matches {
		m := &matches[i]
		lines, ok := fileLines[m.Path]
		if !ok {
			body, err := os.ReadFile(m.Path)
			if err != nil {
				continue
			}
			lines = strings.Split(string(body), "\n")
			fileLines[m.Path] = lines
		}
		m.SectionEndHint = findSectionEnd(lines, m.Line, regexes)
	}
}

func findSectionEnd(lines []string, matchLine int, regexes []*regexp.Regexp) int {
	for i := matchLine; i < len(lines); i++ {
		for _, r := range regexes {
			if r.MatchString(lines[i]) {
				return i + 1
			}
		}
	}
	return len(lines)
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
		Description: "Recursive regex search via ripgrep. Symlink-safe at / and network FS (auto --max-depth=4, --no-follow, --one-file-system, --max-filesize=50M, --threads=2). Each match includes section_end_hint: the first line at or after the match where a section boundary (func/class/def/type/etc.) begins — use it as end_line for a targeted read_files follow-up.",
	}, grepTool(cfg))
}
