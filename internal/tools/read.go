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

type ReadSlice struct {
	Offset            int    `json:"offset,omitempty" jsonschema:"1-indexed starting line. 0 = start of file."`
	Limit             int    `json:"limit,omitempty" jsonschema:"Number of lines to read from offset. 0 = read to EOF."`
	Tail              int    `json:"tail,omitempty" jsonschema:"If >0, read last N lines (overrides offset/limit)."`
	ReadToNextPattern string `json:"read_to_next_pattern,omitempty" jsonschema:"Read from offset until the first line matching this regex (exclusive)."`
}

type ReadFileSpec struct {
	Path              string      `json:"path" jsonschema:"Absolute path or path relative to portal root."`
	Offset            int         `json:"offset,omitempty" jsonschema:"1-indexed starting line. 0 = start of file. Ignored if reads is set."`
	Limit             int         `json:"limit,omitempty" jsonschema:"Number of lines to read from offset. 0 = read to EOF. Ignored if reads is set."`
	Tail              int         `json:"tail,omitempty" jsonschema:"If >0, read last N lines (overrides offset/limit). Ignored if reads is set."`
	ReadToNextPattern string      `json:"read_to_next_pattern,omitempty" jsonschema:"Read from offset until the first line matching this regex (exclusive). Ignored if reads is set."`
	Reads             []ReadSlice `json:"reads,omitempty" jsonschema:"Multiple slices from this file in one call. When non-empty, overrides top-level offset/limit/tail/read_to_next_pattern."`
}

type SliceResult struct {
	Offset            int    `json:"offset,omitempty"`
	Limit             int    `json:"limit,omitempty"`
	Tail              int    `json:"tail,omitempty"`
	ReadToNextPattern string `json:"read_to_next_pattern,omitempty"`
	StartLine         int    `json:"start_line"`
	EndLine           int    `json:"end_line"`
	Content           string `json:"content"`
	Lines             int    `json:"lines"`
	Truncated         bool   `json:"truncated"`
	Error             string `json:"error,omitempty"`
}

type ReadFileResult struct {
	Path       string        `json:"path"`
	Content    string        `json:"content,omitempty"`
	Lines      int           `json:"lines,omitempty"`
	StartLine  int           `json:"start_line,omitempty"`
	EndLine    int           `json:"end_line,omitempty"`
	TotalLines int           `json:"total_lines"`
	Truncated  bool          `json:"truncated,omitempty"`
	Slices     []SliceResult `json:"slices,omitempty"`
	Error      string        `json:"error,omitempty"`
}

type ReadFilesInput struct {
	Files []ReadFileSpec `json:"files" jsonschema:"One entry per file. Each spec supports offset+limit, tail, read_to_next_pattern, OR a reads[] array of multiple slices from the same file."`
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
	lines, err := readAllLines(p)
	if err != nil {
		return ReadFileResult{Path: p, Error: err.Error()}
	}
	total := len(lines)

	if len(spec.Reads) > 0 {
		slices := make([]SliceResult, 0, len(spec.Reads))
		for _, r := range spec.Reads {
			chosen, start, end, serr := applySlice(lines, r.Offset, r.Limit, r.Tail, r.ReadToNextPattern)
			sr := SliceResult{
				Offset:            r.Offset,
				Limit:             r.Limit,
				Tail:              r.Tail,
				ReadToNextPattern: r.ReadToNextPattern,
			}
			if serr != nil {
				sr.Error = serr.Error()
				slices = append(slices, sr)
				continue
			}
			sr.Content = strings.Join(chosen, "\n")
			sr.Lines = len(chosen)
			sr.StartLine = start + 1
			sr.EndLine = end
			sr.Truncated = start > 0 || end < total
			slices = append(slices, sr)
		}
		return ReadFileResult{Path: p, TotalLines: total, Slices: slices}
	}

	chosen, start, end, serr := applySlice(lines, spec.Offset, spec.Limit, spec.Tail, spec.ReadToNextPattern)
	if serr != nil {
		return ReadFileResult{Path: p, TotalLines: total, Error: serr.Error()}
	}
	return ReadFileResult{
		Path:       p,
		Content:    strings.Join(chosen, "\n"),
		Lines:      len(chosen),
		StartLine:  start + 1,
		EndLine:    end,
		TotalLines: total,
		Truncated:  start > 0 || end < total,
	}
}

func readAllLines(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1<<20), 1<<30)
	var lines []string
	for sc.Scan() {
		lines = append(lines, sc.Text())
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	return lines, nil
}

func applySlice(lines []string, offset, limit, tail int, pattern string) ([]string, int, int, error) {
	total := len(lines)
	if tail > 0 {
		start := total - tail
		if start < 0 {
			start = 0
		}
		return lines[start:total], start, total, nil
	}
	start := offset
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
	if pattern != "" {
		re, err := regexp.Compile(pattern)
		if err != nil {
			return nil, 0, 0, fmt.Errorf("regex: %v", err)
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
	} else if limit > 0 {
		end = start + limit
		if end > total {
			end = total
		}
	}
	return lines[start:end], start, end, nil
}

func RegisterReadFiles(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "read_files",
		Description: "Read one or more files. Each file supports offset/limit, tail, or read_to_next_pattern — or a reads[] array of multiple slices from the same file in one call. No character cap.",
	}, readFiles(cfg))
}
