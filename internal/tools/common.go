package tools

import (
	"fmt"
	"os"
	"path/filepath"
)

type Config struct {
	Root       string
	ManagedBin string
}

// ignoredDirNames are directory basenames universally treated as machine-
// generated noise: dependency caches, build outputs, language venvs, VCS
// internals. Matched by basename anywhere in the walk, so the rule is
// repo-agnostic and safe across roots that contain multiple sibling repos —
// no risk of one repo's ignore pattern hiding another repo's source.
//
// Borderline names that legitimate source code sometimes uses (bin, obj,
// env, lib, .vscode, .idea, .github) are intentionally excluded. The
// `include_ignored: true` flag on grep + directory_tree disables this
// filter entirely when an agent genuinely needs to traverse vendored
// packages.
var ignoredDirNames = map[string]struct{}{
	"node_modules":  {},
	".git":          {},
	".svn":          {},
	".hg":           {},
	"dist":          {},
	"build":         {},
	"target":        {},
	".venv":         {},
	"venv":          {},
	"__pycache__":   {},
	".pytest_cache": {},
	".mypy_cache":   {},
	".ruff_cache":   {},
	".tox":          {},
	".next":         {},
	".nuxt":         {},
	".cache":        {},
	".terraform":    {},
	".gradle":       {},
	"coverage":      {},
	".nyc_output":   {},
}

// isIgnoredDirName reports whether the basename matches a universally
// machine-generated directory. Callers must already have established that
// the entry is a directory.
func isIgnoredDirName(name string) bool {
	_, ok := ignoredDirNames[name]
	return ok
}

// ignoredDirGlobs returns ripgrep --glob exclusions matching the same
// denylist. Used by grep when include_ignored is false.
func ignoredDirGlobs() []string {
	out := make([]string, 0, len(ignoredDirNames)*2)
	for name := range ignoredDirNames {
		out = append(out, "-g", "!"+name)
	}
	return out
}

func (c Config) ResolvePath(p string) (string, error) {
	if p == "" || p == "." {
		return c.Root, nil
	}
	if p[0] == '~' {
		h := os.Getenv("HOME")
		if h == "" {
			return "", fmt.Errorf("cannot expand ~: HOME not set")
		}
		p = filepath.Join(h, p[1:])
	}
	if !filepath.IsAbs(p) {
		p = filepath.Join(c.Root, p)
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	return filepath.Clean(abs), nil
}
