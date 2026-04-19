package tools

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// imageExtensions maps lowercase file extensions to MIME type for native image
// passthrough via MCP ImageContent. Vision-capable models can consume these
// directly without a base64 detour through the LLM. SVG stays text — XML is
// more useful read as source than rendered.
var imageExtensions = map[string]string{
	".png":  "image/png",
	".jpg":  "image/jpeg",
	".jpeg": "image/jpeg",
	".gif":  "image/gif",
	".webp": "image/webp",
	".bmp":  "image/bmp",
	".ico":  "image/x-icon",
	".tiff": "image/tiff",
	".tif":  "image/tiff",
}

// maxImageBytes caps a single image's raw size before refusing to ship it.
// Base64 inflates ~33%, so 5 MB raw is ~6.7 MB on the wire. Larger images
// would torpedo the model's context window. Configurable later if needed.
const maxImageBytes = 5 * 1024 * 1024

func imageMime(path string) (string, bool) {
	mime, ok := imageExtensions[strings.ToLower(filepath.Ext(path))]
	return mime, ok
}

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

// imageBlob carries a successfully-loaded image's raw bytes alongside the
// MIME type and source path. The handler aggregates these and emits MCP
// ImageContent blocks alongside the text/JSON output.
type imageBlob struct {
	path string
	mime string
	data []byte
}

func readFiles(cfg Config) func(context.Context, *mcp.CallToolRequest, ReadFilesInput) (*mcp.CallToolResult, ReadFilesOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in ReadFilesInput) (*mcp.CallToolResult, ReadFilesOutput, error) {
		out := ReadFilesOutput{Files: make([]ReadFileResult, 0, len(in.Files))}
		var images []imageBlob
		for _, spec := range in.Files {
			r, img := readOne(cfg, spec)
			out.Files = append(out.Files, r)
			if img != nil {
				images = append(images, *img)
			}
		}
		if len(images) == 0 {
			return nil, out, nil
		}
		// Mixed content: SDK only auto-mirrors structuredContent → Content[TextContent]
		// when Content is nil. Once we add ImageContent blocks we own the whole
		// Content array, so manually marshal the structured output as the leading
		// TextContent so non-vision clients still see the metadata.
		outBytes, err := json.Marshal(out)
		if err != nil {
			return nil, out, fmt.Errorf("marshal output: %w", err)
		}
		content := []mcp.Content{&mcp.TextContent{Text: string(outBytes)}}
		for _, im := range images {
			content = append(content, &mcp.ImageContent{Data: im.data, MIMEType: im.mime})
		}
		return &mcp.CallToolResult{Content: content}, out, nil
	}
}

func readOne(cfg Config, spec ReadFileSpec) (ReadFileResult, *imageBlob) {
	p, err := cfg.ResolvePath(spec.Path)
	if err != nil {
		return ReadFileResult{Path: spec.Path, Error: err.Error()}, nil
	}
	if mime, ok := imageMime(p); ok {
		return readImage(p, mime)
	}
	lines, err := readAllLines(p)
	if err != nil {
		return ReadFileResult{Path: p, Error: err.Error()}, nil
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
		return ReadFileResult{Path: p, TotalLines: total, Slices: slices}, nil
	}

	chosen, start, end, serr := applySlice(lines, spec.Offset, spec.Limit, spec.Tail, spec.ReadToNextPattern)
	if serr != nil {
		return ReadFileResult{Path: p, TotalLines: total, Error: serr.Error()}, nil
	}
	return ReadFileResult{
		Path:       p,
		Content:    strings.Join(chosen, "\n"),
		Lines:      len(chosen),
		StartLine:  start + 1,
		EndLine:    end,
		TotalLines: total,
		Truncated:  start > 0 || end < total,
	}, nil
}

// readImage loads a recognized-extension image and returns both a metadata
// ReadFileResult (so the structured payload still describes what was read)
// and a side-channel imageBlob the handler attaches as MCP ImageContent.
// Files larger than maxImageBytes are refused — base64 inflation would burn
// too much of the model's context window.
func readImage(path, mime string) (ReadFileResult, *imageBlob) {
	st, err := os.Stat(path)
	if err != nil {
		return ReadFileResult{Path: path, Error: err.Error()}, nil
	}
	if st.Size() > maxImageBytes {
		return ReadFileResult{
			Path:    path,
			Content: fmt.Sprintf("[image %s skipped: %d bytes exceeds %d byte cap]", mime, st.Size(), maxImageBytes),
			Error:   "image exceeds size cap",
		}, nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ReadFileResult{Path: path, Error: err.Error()}, nil
	}
	return ReadFileResult{
		Path:    path,
		Content: fmt.Sprintf("[image %s, %d bytes — passed through as MCP ImageContent block]", mime, len(data)),
	}, &imageBlob{path: path, mime: mime, data: data}
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
		Description: "Read one or more files. Each file supports offset/limit, tail, or read_to_next_pattern — or a reads[] array of multiple slices from the same file in one call. No character cap. Image files (png/jpg/jpeg/gif/webp/bmp/ico/tiff up to 5 MB) are passed through as MCP ImageContent blocks for vision-capable models; SVG stays text.",
	}, readFiles(cfg))
}
