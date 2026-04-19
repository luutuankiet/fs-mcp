package bootstrap

import (
	"archive/tar"
	"compress/gzip"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

// BinDir returns the managed-binary directory. Creates it if missing.
func BinDir() (string, error) {
	home := os.Getenv("HOME")
	if home == "" {
		return "", fmt.Errorf("HOME not set")
	}
	if bh := os.Getenv("XDG_BIN_HOME"); bh != "" {
		if err := os.MkdirAll(bh, 0o755); err == nil {
			return bh, nil
		}
	}
	dir := filepath.Join(home, ".local", "bin")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

// Status holds the outcome of ensuring one dep.
type Status struct {
	Name       string
	Version    string
	Path       string
	Installed  bool // true if we downloaded it this run
	Source     string // "managed" (our bin dir) or "system" (found on PATH) or "missing"
	Error      error
}

// Ensure walks the manifest and installs/upgrades as needed. Returns per-dep status.
func Ensure() ([]Status, error) {
	goos, arch, ok := Platform()
	if !ok {
		return nil, fmt.Errorf("unsupported platform: %s/%s (linux and darwin only)", runtime.GOOS, runtime.GOARCH)
	}
	libc := Libc()
	bin, err := BinDir()
	if err != nil {
		return nil, err
	}
	var statuses []Status
	for _, d := range Manifest() {
		statuses = append(statuses, ensureOne(d, goos, arch, libc, bin))
	}
	return statuses, nil
}

func ensureOne(d Dep, goos, arch, libc, bin string) Status {
	managed := filepath.Join(bin, d.Name)
	st := Status{Name: d.Name, Version: d.Version}

	if versionOK(managed, d) {
		st.Path = managed
		st.Source = "managed"
		return st
	}
	// fall back to system PATH (user-installed)
	if p, err := exec.LookPath(d.Name); err == nil && p != managed {
		if versionOK(p, d) {
			st.Path = p
			st.Source = "system"
			return st
		}
	}
	// Install to managed.
	if err := downloadTo(d, goos, arch, libc, managed); err != nil {
		st.Source = "missing"
		st.Error = err
		return st
	}
	st.Path = managed
	st.Source = "managed"
	st.Installed = true
	return st
}

func versionOK(path string, d Dep) bool {
	if path == "" {
		return false
	}
	if _, err := os.Stat(path); err != nil {
		return false
	}
	if d.VersionContains == "" {
		return true
	}
	out, err := exec.Command(path, d.VerifyFlag).CombinedOutput()
	if err != nil {
		return false
	}
	return strings.Contains(string(out), d.VersionContains)
}

func downloadTo(d Dep, goos, arch, libc, dest string) error {
	url := d.URL(goos, arch, libc)
	if url == "" {
		return fmt.Errorf("no upstream build of %s for %s/%s libc=%s — install manually to $HOME/.local/bin or system PATH", d.Name, goos, arch, libc)
	}
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("download %s: %w", d.Name, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("download %s: HTTP %d", d.Name, resp.StatusCode)
	}

	tmp := dest + ".new"
	defer os.Remove(tmp)

	switch d.Extract {
	case "binary":
		f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o755)
		if err != nil {
			return err
		}
		if _, err := io.Copy(f, resp.Body); err != nil {
			f.Close()
			return err
		}
		f.Close()
	case "tar.gz":
		member := ""
		if d.Member != nil {
			member = d.Member(goos, arch, libc)
		}
		if member == "" {
			return fmt.Errorf("%s: no archive member defined for %s/%s", d.Name, goos, arch)
		}
		if err := extractTarGz(resp.Body, member, tmp); err != nil {
			return fmt.Errorf("%s extract: %w", d.Name, err)
		}
	case "gz":
		if err := extractGz(resp.Body, tmp); err != nil {
			return fmt.Errorf("%s extract: %w", d.Name, err)
		}
	default:
		return fmt.Errorf("%s: unknown Extract type %q", d.Name, d.Extract)
	}
	if err := os.Chmod(tmp, 0o755); err != nil {
		return err
	}
	if err := os.Rename(tmp, dest); err != nil {
		return err
	}
	log.Printf("bootstrap: installed %s %s → %s", d.Name, d.Version, dest)
	return nil
}

func extractTarGz(r io.Reader, member, dest string) error {
	gz, err := gzip.NewReader(r)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			return fmt.Errorf("member %q not found in archive", member)
		}
		if err != nil {
			return err
		}
		if h.Name == member || filepath.Clean(h.Name) == filepath.Clean(member) {
			f, err := os.OpenFile(dest, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o755)
			if err != nil {
				return err
			}
			defer f.Close()
			_, err = io.Copy(f, tr)
			return err
		}
	}
}

func extractGz(r io.Reader, dest string) error {
	gz, err := gzip.NewReader(r)
	if err != nil {
		return err
	}
	defer gz.Close()
	f, err := os.OpenFile(dest, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, gz)
	return err
}

// WirePath prepends the managed bin dir to $PATH so all subprocesses (rg, jq, yq, rtk)
// inherit it without touching the user's shell rc.
func WirePath(bin string) {
	old := os.Getenv("PATH")
	if old == "" {
		os.Setenv("PATH", bin)
		return
	}
	if strings.HasPrefix(old, bin+string(os.PathListSeparator)) {
		return
	}
	os.Setenv("PATH", bin+string(os.PathListSeparator)+old)
}
