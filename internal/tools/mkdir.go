package tools

import (
	"context"
	"fmt"
	"os"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type CreateDirectoryInput struct {
	Path string `json:"path" jsonschema:"Directory path to create. Relative paths resolve against portal root. Creates parents as needed."`
}

type CreateDirectoryOutput struct {
	Path    string `json:"path"`
	Created bool   `json:"created"`
}

func createDirectory(cfg Config) func(context.Context, *mcp.CallToolRequest, CreateDirectoryInput) (*mcp.CallToolResult, CreateDirectoryOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in CreateDirectoryInput) (*mcp.CallToolResult, CreateDirectoryOutput, error) {
		p, err := cfg.ResolvePath(in.Path)
		if err != nil {
			return nil, CreateDirectoryOutput{}, err
		}
		existed := false
		if st, statErr := os.Stat(p); statErr == nil && st.IsDir() {
			existed = true
		}
		if err := os.MkdirAll(p, 0o755); err != nil {
			return nil, CreateDirectoryOutput{}, fmt.Errorf("mkdir %s: %w", p, err)
		}
		return nil, CreateDirectoryOutput{Path: p, Created: !existed}, nil
	}
}

func RegisterCreateDirectory(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "create_directory",
		Description: "Create a directory (with parents, idempotent).",
	}, createDirectory(cfg))
}
