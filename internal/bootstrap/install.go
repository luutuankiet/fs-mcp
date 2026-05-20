package bootstrap

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
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
	Name      string
	Version   string
	Path      string
	Installed bool   // true if we downloaded it this run
	Source    string // "managed" / "system" / "missing" — or "managed (...)" w/ diagnostic suffix
	Error     error
}

// Ensure walks the manifest and installs/upgrades as needed. Returns per-dep status.
//
// Upstream tag resolution is parallel — all deps query GitHub concurrently,
// each capped at fetchTagTimeout (see remote.go). Worst-case added cold-start
// latency is ~fetchTagTimeout regardless of dep count.
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

	manifest := Manifest()
	targets := make([]targetTag, len(manifest))

	var wg sync.WaitGroup
	for i := range manifest {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			targets[i] = resolveTarget(manifest[i])
		}(i)
	}
	wg.Wait()

	statuses := make([]Status, len(manifest))
	for i, d := range manifest {
		statuses[i] = ensureOne(d, goos, arch, libc, bin, targets[i])
	}
	return statuses, nil
}

// targetTag is the resolved upgrade target for one dep, plus its provenance.
type targetTag struct {
	tag    string
	source string // "upstream" | "floor-pinned" | "floor-fallback"
}

// resolveTarget asks GitHub for the latest tag of dep.Repo. Falls back to
// the embedded floor (dep.Version) when the API is unreachable, the repo is
// unconfigured, or FS_MCP_PIN_DEPS=1 is set (operator override for air-gap
// or freezing a whole fleet without recutting fs-mcp).
func resolveTarget(d Dep) targetTag {
	if d.Repo == "" || os.Getenv("FS_MCP_PIN_DEPS") == "1" {
		return targetTag{tag: d.Version, source: "floor-pinned"}
	}
	ctx := context.Background()
	if t, err := FetchLatestTag(ctx, d.Repo); err == nil {
		return targetTag{tag: t, source: "upstream"}
	}
	return targetTag{tag: d.Version, source: "floor-fallback"}
}

func ensureOne(d Dep, goos, arch, libc, bin string, target targetTag) Status {
	managed := filepath.Join(bin, d.Name)
	st := Status{Name: d.Name, Version: target.tag}

	if versionOK(managed, d, target.tag) {
		st.Path = managed
		st.Source = "managed"
		if target.source == "floor-fallback" {
			st.Source = "managed (upstream check failed; pinned to floor)"
		}
		return st
	}
	// System-PATH fallback (only if it happens to match the target — won't downgrade).
	if p, err := exec.LookPath(d.Name); err == nil && p != managed {
		if versionOK(p, d, target.tag) {
			st.Path = p
			st.Source = "system"
			return st
		}
	}
	// Install / upgrade.
	if err := downloadTo(d, goos, arch, libc, target.tag, managed); err != nil {
		// Graceful fallback: keep the existing managed binary if any.
		// Operator sees a diagnostic Source string AND fs-mcp keeps booting.
		if _, statErr := os.Stat(managed); statErr == nil {
			st.Path = managed
			st.Source = "managed (upgrade to " + target.tag + " failed: " + truncateErr(err) + ")"
			if cur := currentVersion(managed, d); cur != "" {
				st.Version = cur
			}
			return st
		}
		st.Source = "missing"
		st.Error = err
		return st
	}
	st.Path = managed
	st.Source = "managed"
	st.Installed = true
	return st
}

// versionOK runs `path --version` and confirms it matches the expected
// substring derived from target. Missing path → false; missing VersionContains
// derivation → true (assumes any present binary is acceptable).
func versionOK(path string, d Dep, target string) bool {
	if path == "" {
		return false
	}
	if _, err := os.Stat(path); err != nil {
		return false
	}
	expected := ""
	if d.VersionContains != nil {
		expected = d.VersionContains(target)
	}
	if expected == "" {
		return true
	}
	out, err := exec.Command(path, d.VerifyFlag).CombinedOutput()
	if err != nil {
		return false
	}
	return strings.Contains(string(out), expected)
}

// currentVersion reads the first line of `path --version` for display purposes
// when an upgrade was attempted but failed (so doctor can still report what's
// actually installed).
func currentVersion(path string, d Dep) string {
	if d.VerifyFlag == "" {
		return ""
	}
	out, err := exec.Command(path, d.VerifyFlag).CombinedOutput()
	if err != nil {
		return ""
	}
	first := strings.SplitN(strings.TrimSpace(string(out)), "\n", 2)[0]
	return first
}

func truncateErr(err error) string {
	s := err.Error()
	if len(s) > 80 {
		return s[:77] + "..."
	}
	return s
}

func downloadTo(d Dep, goos, arch, libc, tag, dest string) error {
	url := d.URL(goos, arch, libc, tag)
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
			member = d.Member(goos, arch, libc, tag)
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
	log.Printf("bootstrap: installed %s %s → %s", d.Name, tag, dest)
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
