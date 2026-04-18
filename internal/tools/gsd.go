package tools

import (
	"context"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

var gsdSkipDirs = map[string]bool{
	"node_modules":  true,
	".venv":         true,
	"__pycache__":   true,
	".git":          true,
	".cache":        true,
	".npm":          true,
	"venv":          true,
	"site-packages": true,
	".tox":          true,
	"dist":          true,
	"build":         true,
	".next":         true,
	".turbo":        true,
	"target":        true,
	".terraform":    true,
}

var gsdHeavyRootDirs = map[string]bool{
	"proc": true, "sys": true, "run": true, "snap": true,
	"tmp": true, "mnt": true, "media": true, "boot": true,
	"lost+found": true, "dev": true,
}

var gsdNoiseFragments = []string{
	"tests/evals/", "template/gsd-lite", ".opencode/",
	"wt-npm/", "wheels-v5",
	// Deep-path excludes that won't be caught by heavy-root first-level skip.
	// Same-device check alone doesn't help inside one big volume with docker/log spillage.
	"var/lib/docker/", "var/lib/containers/", "var/lib/snapd/",
	"var/cache/", "var/log/",
	"persistent/home/",
}

type GsdDirsInput struct {
	MaxDepth   int    `json:"max_depth,omitempty" jsonschema:"Max directory depth. Default 15."`
	NoMeta     bool   `json:"no_meta,omitempty" jsonschema:"Disable PROJECT.md summary + last_modified. Default false (metadata on)."`
	SearchPath string `json:"search_path,omitempty" jsonschema:"Directory to search. Defaults to portal root."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
}

type GsdDir struct {
	Path           string   `json:"path"`
	LastModified   string   `json:"last_modified,omitempty"`
	ProjectSummary []string `json:"project_summary,omitempty"`
}

type GsdDirsOutput struct {
	Dirs      []GsdDir `json:"dirs"`
	Scanned   int      `json:"scanned"`
	TimedOut  bool     `json:"timed_out"`
	ElapsedMs int64    `json:"elapsed_ms"`
}

func listGsdLiteDirs(cfg Config) func(context.Context, *mcp.CallToolRequest, GsdDirsInput) (*mcp.CallToolResult, GsdDirsOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in GsdDirsInput) (*mcp.CallToolResult, GsdDirsOutput, error) {
		start := time.Now()
		maxDepth := in.MaxDepth
		if maxDepth <= 0 {
			maxDepth = 15
		}
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 30 * time.Second
		}

		root := cfg.Root
		if in.SearchPath != "" {
			p, err := cfg.ResolvePath(in.SearchPath)
			if err != nil {
				return nil, GsdDirsOutput{}, err
			}
			root = p
		}
		root = filepath.Clean(root)

		walkCtx, cancel := context.WithTimeout(ctx, timeout)
		defer cancel()

		out := GsdDirsOutput{}
		rootDev := devOf(root)
		isRootSlash := root == "/"

		_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, walkErr error) error {
			if walkCtx.Err() != nil {
				out.TimedOut = true
				return fs.SkipAll
			}
			if walkErr != nil {
				return nil
			}
			out.Scanned++

			if !d.IsDir() {
				return nil
			}

			info, err := os.Lstat(p)
			if err != nil {
				return nil
			}
			if info.Mode()&fs.ModeSymlink != 0 {
				return fs.SkipDir
			}
			if rootDev != 0 && devOfInfo(info) != rootDev {
				return fs.SkipDir
			}

			if p != root {
				base := filepath.Base(p)
				if gsdSkipDirs[base] {
					return fs.SkipDir
				}
				if isRootSlash {
					rel := strings.TrimPrefix(p, "/")
					first := strings.SplitN(rel, "/", 2)[0]
					if gsdHeavyRootDirs[first] {
						return fs.SkipDir
					}
				}
				rel, _ := filepath.Rel(root, p)
				for _, nf := range gsdNoiseFragments {
					if strings.Contains(rel, nf) {
						return fs.SkipDir
					}
				}
				depth := 1 + strings.Count(rel, string(filepath.Separator))
				if depth > maxDepth {
					return fs.SkipDir
				}
			}

			gsdPath := filepath.Join(p, "gsd-lite")
			projectMd := filepath.Join(gsdPath, "PROJECT.md")
			workMd := filepath.Join(gsdPath, "WORK.md")

			hit := false
			if _, err := os.Stat(projectMd); err == nil {
				hit = true
			}
			if !hit {
				if _, err := os.Stat(workMd); err == nil {
					hit = true
				}
			}
			if !hit {
				return nil
			}

			dir := GsdDir{Path: p}
			if !in.NoMeta {
				dir.LastModified = gsdLastModified(gsdPath)
				dir.ProjectSummary = gsdProjectSummary(projectMd)
			}
			out.Dirs = append(out.Dirs, dir)
			return fs.SkipDir
		})

		out.ElapsedMs = time.Since(start).Milliseconds()
		return nil, out, nil
	}
}

func devOf(path string) uint64 {
	info, err := os.Lstat(path)
	if err != nil {
		return 0
	}
	return devOfInfo(info)
}

func devOfInfo(info os.FileInfo) uint64 {
	if stat, ok := info.Sys().(*syscall.Stat_t); ok {
		return uint64(stat.Dev)
	}
	return 0
}

func gsdLastModified(gsdPath string) string {
	workMd := filepath.Join(gsdPath, "WORK.md")
	if info, err := os.Stat(workMd); err == nil {
		return info.ModTime().UTC().Format(time.RFC3339)
	}
	entries, err := os.ReadDir(gsdPath)
	if err != nil {
		return ""
	}
	var newest time.Time
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			continue
		}
		if info.ModTime().After(newest) {
			newest = info.ModTime()
		}
	}
	if newest.IsZero() {
		return ""
	}
	return newest.UTC().Format(time.RFC3339)
}

func gsdProjectSummary(projectMd string) []string {
	body, err := os.ReadFile(projectMd)
	if err != nil {
		return nil
	}
	lines := strings.Split(string(body), "\n")
	var summary []string
	for _, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "*") && strings.HasSuffix(line, "*") {
			continue
		}
		summary = append(summary, line)
		if len(summary) >= 5 {
			break
		}
	}
	return summary
}

func RegisterListGsdLiteDirs(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:        "list_gsd_lite_dirs",
		Description: "Find gsd-lite project directories (detected via <dir>/gsd-lite/PROJECT.md or WORK.md). NAS-safe walker: no-follow symlinks, one-file-system (same device only), heavy-path skip at /, skip-dir set (node_modules, .git, .venv, target, etc.). Optional PROJECT.md summary + last_modified per hit.",
	}, listGsdLiteDirs(cfg))
}
