package tools

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type ReadFileSpec struct {
	Path                string `json:"path" jsonschema:"Absolute path or path relative to portal root."`
	Offset              int    `json:"offset,omitempty" jsonschema:"1-indexed starting line. 0 = start of file."`
	Limit               int    `json:"limit,omitempty" jsonschema:"Number of lines to read from offset. 0 = read to EOF."`
	Tail                int    `json:"tail,omitempty" jsonschema:"If >0, read last N lines (overrides offset/limit)."`
	ReadToNextPattern   string `json:"read_to_next_pattern,omitempty" jsonschema:"Read from offset until the first line matching this regex (exclusive). Useful for reading one function/section at a time."`
}

type ReadFileResult struct {
	Path       string `json:"path"`
	Content    string `json:"content"`
	Lines      int    `json:"lines"`
	TotalLines int    `json:"total_lines"`
	Truncated  bool   `json:"truncated"`
	Error      string `json:"error,omitempty"`
}

type ReadFilesInput struct {
	Files []ReadFileSpec `json:"files" jsonschema:"One entry per file. Each spec supports offset+limit, tail, or read_to_next_pattern modes."`
}

type ReadFilesOutput struct {
	Files []ReadFileResult `json:"files"`
}

func readFiles(cfg Config) func(context.Context, *mcp.CallToolRequest, ReadFilesInput) (*mcp.CallToolResult, ReadFilesOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in ReadFilesInput) (*mcp.CallToolResult, ReadFilesOutput, error) {
		out := ReadFilesOutput{Files: make([]ReadFileResult, 0, len(in.Files))}
		for _, spec := range in.Files {
			out.Files = append(out.Files, readOne(cfg, spec))
		}
		return nil, out, nil
	}
}

func readOne(cfg Config, spec ReadFileSpec) ReadFileResult {
	p, err := cfg.ResolvePath(spec.Path)
	if err != nil {
		return ReadFileResult{Path: spec.Path, Error: err.Error()}
	}
	f, err := os.Open(p)
	if err != nil {
		return ReadFileResult{Path: p, Error: err.Error()}
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1<<20), 1<<30)
	var lines []string
	for sc.Scan() {
		lines = append(lines, sc.Text())
	}
	if err := sc.Err(); err != nil {
		return ReadFileResult{Path: p, Error: err.Error()}
	}
	total := len(lines)

	if spec.Tail > 0 {
		start := total - spec.Tail
		if start < 0 {
			start = 0
		}
		chosen := lines[start:]
		return ReadFileResult{
			Path:       p,
			Content:    strings.Join(chosen, "\n"),
			Lines:      len(chosen),
			TotalLines: total,
			Truncated:  start > 0,
		}
	}

	start := spec.Offset
	if start > 0 {
		start--
	}
	if start > total {
		start = total
	}
	if start < 0 {
		start = 0
	}

	end := total
	if spec.ReadToNextPattern != "" {
		re, err := regexp.Compile(spec.ReadToNextPattern)
		if err != nil {
			return ReadFileResult{Path: p, Error: fmt.Sprintf("regex: %v", err)}
		}
		for i := start; i < total; i++ {
			if re.MatchString(lines[i]) {
				if i == start {
					continue
				}
				end = i
				break
			}
		}
	} else if spec.Limit > 0 {
		end = start + spec.Limit
		if end > total {
			end = total
		}
	}
	chosen := lines[start:end]
	return ReadFileResult{
		Path:       p,
		Content:    strings.Join(chosen, "\n"),
		Lines:      len(chosen),
		TotalLines: total,
		Truncated:  end < total,
	}
}

func RegisterReadFiles(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "read_files",
		Description: "Read one or more files with offset/limit, tail, or read-to-next-pattern modes. No character cap — bounded by machine memory.",
	}, readFiles(cfg))
}
