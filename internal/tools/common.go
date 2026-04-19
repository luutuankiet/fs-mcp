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
