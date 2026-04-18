package portal

import (
	"fmt"
	"os"
	"path/filepath"
)

type Decision struct {
	Root   string
	Source string
}

func Detect(cliArg string) (Decision, error) {
	if v := os.Getenv("FS_MCP_ROOT"); v != "" {
		p, err := absResolve(v)
		if err != nil {
			return Decision{}, err
		}
		return Decision{Root: p, Source: "env:FS_MCP_ROOT"}, nil
	}
	if cliArg != "" {
		p, err := absResolve(cliArg)
		if err != nil {
			return Decision{}, err
		}
		return Decision{Root: p, Source: "cli"}, nil
	}
	if isHeadless() {
		return Decision{Root: "/", Source: "headless"}, nil
	}
	if h := os.Getenv("HOME"); h != "" {
		p, err := absResolve(h)
		if err == nil {
			return Decision{Root: p, Source: "dev:$HOME"}, nil
		}
	}
	return Decision{Root: "/", Source: "fallback"}, nil
}

func isHeadless() bool {
	if os.Getenv("SSH_CONNECTION") != "" {
		return true
	}
	if os.Getenv("XDG_SESSION_TYPE") == "tty" {
		return true
	}
	if os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "" {
		return true
	}
	return false
}

func absResolve(p string) (string, error) {
	if p == "" {
		return "", fmt.Errorf("empty path")
	}
	if p[0] == '~' {
		h := os.Getenv("HOME")
		if h == "" {
			return "", fmt.Errorf("cannot expand ~: HOME not set")
		}
		p = filepath.Join(h, p[1:])
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	return filepath.Clean(abs), nil
}
