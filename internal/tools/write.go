package tools

import (
	"context"
	"os"
	"path/filepath"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type WriteInput struct {
	FilePath string `json:"file_path" jsonschema:"Path to write. Creates parent directories if missing."`
	Content  string `json:"content" jsonschema:"File content. Overwrites existing files."`
}

type WriteOutput struct {
	FilePath string `json:"file_path"`
	Bytes    int    `json:"bytes"`
	Created  bool   `json:"created"`
}

func writeTool(cfg Config) func(context.Context, *mcp.CallToolRequest, WriteInput) (*mcp.CallToolResult, WriteOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in WriteInput) (*mcp.CallToolResult, WriteOutput, error) {
		p, err := cfg.ResolvePath(in.FilePath)
		if err != nil {
			return nil, WriteOutput{}, err
		}
		existed := false
		if _, err := os.Stat(p); err == nil {
			existed = true
		}
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			return nil, WriteOutput{}, err
		}
		if err := os.WriteFile(p, []byte(in.Content), 0o644); err != nil {
			return nil, WriteOutput{}, err
		}
		return nil, WriteOutput{FilePath: p, Bytes: len(in.Content), Created: !existed}, nil
	}
}

func RegisterWrite(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "write",
		Description: "Write content to a file (creates parent dirs). Overwrites existing. Use edit for surgical changes.",
	}, writeTool(cfg))
}
