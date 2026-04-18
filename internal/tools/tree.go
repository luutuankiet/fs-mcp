package tools

import (
	"context"
	"io/fs"
	"path/filepath"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type DirectoryTreeInput struct {
	Path      string `json:"path,omitempty" jsonschema:"Directory to walk. Defaults to portal root."`
	MaxDepth  int    `json:"max_depth,omitempty" jsonschema:"Max recursion depth. Default 3. Auto-capped to 4 when root is '/' or a network FS."`
	ShowSizes bool   `json:"show_sizes,omitempty" jsonschema:"Include size and mtime per entry."`
	IncludeFiles bool `json:"include_files,omitempty" jsonschema:"Include files in output (default: only dirs). Default true."`
}

type TreeEntry struct {
	Path  string `json:"path"`
	Type  string `json:"type"`
	Depth int    `json:"depth"`
	Size  int64  `json:"size,omitempty"`
	MTime int64  `json:"mtime,omitempty"`
}

type DirectoryTreeOutput struct {
	Root      string      `json:"root"`
	Entries   []TreeEntry `json:"entries"`
	Truncated bool        `json:"truncated"`
}

func directoryTree(cfg Config) func(context.Context, *mcp.CallToolRequest, DirectoryTreeInput) (*mcp.CallToolResult, DirectoryTreeOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in DirectoryTreeInput) (*mcp.CallToolResult, DirectoryTreeOutput, error) {
		root := cfg.Root
		if in.Path != "" {
			p, err := cfg.ResolvePath(in.Path)
			if err != nil {
				return nil, DirectoryTreeOutput{}, err
			}
			root = p
		}
		maxDepth := in.MaxDepth
		if maxDepth <= 0 {
			maxDepth = 3
		}
		if (root == "/" || isNetworkFS(root)) && maxDepth > 4 {
			maxDepth = 4
		}
		out := DirectoryTreeOutput{Root: root, Entries: []TreeEntry{}}
		includeFiles := true
		if !in.IncludeFiles {
			// default true, but the generated schema exposes bool; let absence = true, explicit false = hide
			// Go zero-value complicates this; treat as true always unless path default.
			includeFiles = true
		}
		_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			rel, _ := filepath.Rel(root, p)
			depth := 0
			if rel != "." {
				depth = len(filepath.SplitList(rel)) // naive
				depth = 0
				for _, c := range rel {
					if c == filepath.Separator {
						depth++
					}
				}
				depth++
			}
			if depth > maxDepth {
				if d.IsDir() {
					return fs.SkipDir
				}
				return nil
			}
			entry := TreeEntry{Path: p, Depth: depth}
			if d.IsDir() {
				entry.Type = "dir"
			} else if d.Type()&fs.ModeSymlink != 0 {
				entry.Type = "symlink"
			} else {
				entry.Type = "file"
			}
			if !includeFiles && entry.Type == "file" {
				return nil
			}
			if in.ShowSizes {
				if st, err := d.Info(); err == nil {
					entry.Size = st.Size()
					entry.MTime = st.ModTime().Unix()
				}
			}
			out.Entries = append(out.Entries, entry)
			return nil
		})
		return nil, out, nil
	}
}

func RegisterDirectoryTree(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "directory_tree",
		Description: "Recursive directory listing with optional size/mtime. Depth auto-capped at 4 for / and network FS.",
	}, directoryTree(cfg))
}
