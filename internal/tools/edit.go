package tools

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const (
	sentinelOverwrite = "OVERWRITE_FILE"
	sentinelAppend    = "APPEND_TO_FILE"
)

type EditOp struct {
	OldString  string `json:"old_string" jsonschema:"Exact text to find. Must be unique unless replace_all=true. Sentinels: \"\" creates a new file (errors if it exists); \"OVERWRITE_FILE\" replaces the whole file; \"APPEND_TO_FILE\" appends to end of file."`
	NewString  string `json:"new_string" jsonschema:"Replacement text. For sentinels, this is the content written / appended."`
	ReplaceAll bool   `json:"replace_all,omitempty" jsonschema:"Replace every occurrence. Default false (fail unless old_string is unique)."`
}

type EditFile struct {
	FilePath string   `json:"file_path" jsonschema:"Path to edit. Relative = portal root."`
	Edits    []EditOp `json:"edits" jsonschema:"Ordered edits applied sequentially to this file. Each edit sees the result of the previous one."`
}

type EditInput struct {
	Files []EditFile `json:"files,omitempty" jsonschema:"Multi-file batch. Each file runs its edits[] in order. If omitted, the top-level file_path/edits[] or single-edit fields are used."`
	// Single-file convenience fields (used when Files is empty).
	FilePath   string   `json:"file_path,omitempty" jsonschema:"Shortcut: single-file mode. Applies edits[] or (old_string,new_string,replace_all) to this path."`
	Edits      []EditOp `json:"edits,omitempty" jsonschema:"Shortcut: edits[] for single-file mode (with file_path)."`
	OldString  string   `json:"old_string,omitempty" jsonschema:"Shortcut: single edit. Requires file_path."`
	NewString  string   `json:"new_string,omitempty" jsonschema:"Shortcut: replacement for single edit."`
	ReplaceAll bool     `json:"replace_all,omitempty" jsonschema:"Shortcut: for single edit."`
}

type EditOpResult struct {
	Mode         string `json:"mode"`
	Replacements int    `json:"replacements,omitempty"`
	Normalized   bool   `json:"normalized_line_endings,omitempty"`
	Error        string `json:"error,omitempty"`
}

type EditFileResult struct {
	FilePath string         `json:"file_path"`
	Edits    []EditOpResult `json:"edits"`
	Bytes    int            `json:"bytes,omitempty"`
	Error    string         `json:"error,omitempty"`
}

type EditOutput struct {
	Files []EditFileResult `json:"files"`
}

func editTool(cfg Config) func(context.Context, *mcp.CallToolRequest, EditInput) (*mcp.CallToolResult, EditOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in EditInput) (*mcp.CallToolResult, EditOutput, error) {
		batch := in.Files
		if len(batch) == 0 {
			if in.FilePath == "" {
				return nil, EditOutput{}, fmt.Errorf("must provide files[] or file_path")
			}
			edits := in.Edits
			if len(edits) == 0 {
				edits = []EditOp{{OldString: in.OldString, NewString: in.NewString, ReplaceAll: in.ReplaceAll}}
			}
			batch = []EditFile{{FilePath: in.FilePath, Edits: edits}}
		}
		out := EditOutput{Files: make([]EditFileResult, 0, len(batch))}
		for _, f := range batch {
			out.Files = append(out.Files, editOne(cfg, f))
		}
		return nil, out, nil
	}
}

func editOne(cfg Config, f EditFile) EditFileResult {
	p, err := cfg.ResolvePath(f.FilePath)
	if err != nil {
		return EditFileResult{FilePath: f.FilePath, Error: err.Error()}
	}
	if len(f.Edits) == 0 {
		return EditFileResult{FilePath: p, Error: "edits[] is empty"}
	}

	result := EditFileResult{FilePath: p, Edits: make([]EditOpResult, 0, len(f.Edits))}

	var src string
	var fileExists bool
	var isBinary bool
	if body, err := os.ReadFile(p); err == nil {
		src = string(body)
		fileExists = true
		if bytes.IndexByte(body, 0) >= 0 {
			isBinary = true
		}
	} else if !os.IsNotExist(err) {
		return EditFileResult{FilePath: p, Error: err.Error()}
	}

	if isBinary {
		// Binary files may only be touched via sentinels. Normal string-replace
		// would corrupt them. OVERWRITE_FILE / APPEND_TO_FILE are intent-explicit
		// so allow those; reject the replace flow.
		for _, op := range f.Edits {
			switch op.OldString {
			case "", sentinelOverwrite, sentinelAppend:
				continue
			default:
				return EditFileResult{FilePath: p, Error: "file contains NUL byte (binary); only \"\", OVERWRITE_FILE, APPEND_TO_FILE sentinels are allowed"}
			}
		}
	}

	// Per-file best-effort: each op is attempted independently, failures are
	// reported per-op, successful edits still write. Agents pay the retry cost
	// only for the ops that actually failed — not the whole chain.
	// Caveat: if op N depends on text introduced by op N-1 and N-1 failed,
	// N will also fail — the agent's ordering assumption is preserved, we
	// just don't throw away the unrelated wins.
	anySuccess := false
	for _, op := range f.Edits {
		r := applyOp(&src, &fileExists, op)
		result.Edits = append(result.Edits, r)
		if r.Error == "" {
			anySuccess = true
		}
	}

	if !anySuccess {
		return result
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		result.Error = err.Error()
		return result
	}
	if err := atomicWriteFile(p, []byte(src)); err != nil {
		result.Error = err.Error()
		return result
	}
	result.Bytes = len(src)
	return result
}

// atomicWriteFile writes via a sibling temp file + rename so a crash mid-write
// never leaves the destination truncated or partially overwritten.
func atomicWriteFile(path string, data []byte) error {
	dir := filepath.Dir(path)
	base := filepath.Base(path)
	tmp := filepath.Join(dir, "."+base+".fs-mcp.tmp")
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func applyOp(src *string, exists *bool, op EditOp) EditOpResult {
	switch op.OldString {
	case "":
		if *exists {
			return EditOpResult{Mode: "create", Error: "file already exists (use OVERWRITE_FILE sentinel to replace)"}
		}
		*src = op.NewString
		*exists = true
		return EditOpResult{Mode: "create"}
	case sentinelOverwrite:
		*src = op.NewString
		*exists = true
		return EditOpResult{Mode: "overwrite"}
	case sentinelAppend:
		if !*exists {
			*src = op.NewString
			*exists = true
			return EditOpResult{Mode: "append", Replacements: 0}
		}
		*src = *src + op.NewString
		return EditOpResult{Mode: "append"}
	}

	if !*exists {
		return EditOpResult{Mode: "replace", Error: "file does not exist (use \"\" old_string to create, or OVERWRITE_FILE sentinel)"}
	}

	old := op.OldString
	new_ := op.NewString
	normalized := false
	count := strings.Count(*src, old)
	if count == 0 && strings.Contains(*src, "\r\n") && !strings.Contains(old, "\r\n") {
		altOld := strings.ReplaceAll(old, "\n", "\r\n")
		altNew := strings.ReplaceAll(new_, "\n", "\r\n")
		if alt := strings.Count(*src, altOld); alt > 0 {
			old = altOld
			new_ = altNew
			count = alt
			normalized = true
		}
	}
	if count == 0 {
		return EditOpResult{Mode: "replace", Error: "no match found for old_string"}
	}
	if !op.ReplaceAll && count > 1 {
		return EditOpResult{Mode: "replace", Error: fmt.Sprintf("old_string matches %d occurrences — make it unique or set replace_all=true", count)}
	}
	n := 1
	if op.ReplaceAll {
		n = count
	}
	*src = strings.Replace(*src, old, new_, n)
	return EditOpResult{Mode: "replace", Replacements: n, Normalized: normalized}
}

func RegisterEdit(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "edit",
		Description: "Exact find-and-replace in one or more files. Batch: files:[{file_path, edits:[{old_string,new_string,replace_all?}]}]. Sentinels for old_string: \"\" creates file, \"OVERWRITE_FILE\" replaces whole file, \"APPEND_TO_FILE\" appends. Line endings auto-normalize if source is CRLF and pattern is LF. Per-file best-effort: each edit is attempted independently; successful ones write even if siblings fail; per-op error/mode reported back so the agent retries only what broke. Binary files (files with NUL bytes) reject non-sentinel edits. Writes are atomic (tempfile + rename).",
	}, editTool(cfg))
}
