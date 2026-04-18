package tools

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type EditInput struct {
	FilePath   string `json:"file_path" jsonschema:"Path to edit. Relative = portal root."`
	OldString  string `json:"old_string" jsonschema:"Exact text to find. Must be unique unless replace_all=true."`
	NewString  string `json:"new_string" jsonschema:"Replacement text. Empty string = delete."`
	ReplaceAll bool   `json:"replace_all,omitempty" jsonschema:"Replace every occurrence. Default false (fail unless old_string is unique)."`
}

type EditOutput struct {
	FilePath     string `json:"file_path"`
	Replacements int    `json:"replacements"`
	Bytes        int    `json:"bytes"`
}

func editTool(cfg Config) func(context.Context, *mcp.CallToolRequest, EditInput) (*mcp.CallToolResult, EditOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in EditInput) (*mcp.CallToolResult, EditOutput, error) {
		if in.OldString == "" {
			return nil, EditOutput{}, fmt.Errorf("old_string must not be empty (use write tool to create/overwrite a file)")
		}
		p, err := cfg.ResolvePath(in.FilePath)
		if err != nil {
			return nil, EditOutput{}, err
		}
		body, err := os.ReadFile(p)
		if err != nil {
			return nil, EditOutput{}, err
		}
		src := string(body)
		count := strings.Count(src, in.OldString)
		if count == 0 {
			return nil, EditOutput{}, fmt.Errorf("no match found for old_string in %s", p)
		}
		if !in.ReplaceAll && count > 1 {
			return nil, EditOutput{}, fmt.Errorf("old_string matches %d occurrences in %s — make it unique or set replace_all=true", count, p)
		}
		n := 1
		if in.ReplaceAll {
			n = count
		}
		out := strings.Replace(src, in.OldString, in.NewString, n)
		if err := os.WriteFile(p, []byte(out), 0o644); err != nil {
			return nil, EditOutput{}, err
		}
		return nil, EditOutput{FilePath: p, Replacements: n, Bytes: len(out)}, nil
	}
}

func RegisterEdit(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "edit",
		Description: "Exact find-and-replace in a file. Fails if old_string is not found, or (without replace_all) if it matches more than once. Atomic per call.",
	}, editTool(cfg))
}
