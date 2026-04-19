package updater

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"
)

// stateDir holds the auto-update bookkeeping files: a daily latest-version
// cache and a presence-marker for explicit pinning by install.sh.
func stateDir() (string, error) {
	xdg := os.Getenv("XDG_STATE_HOME")
	if xdg == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		xdg = filepath.Join(home, ".local", "state")
	}
	dir := filepath.Join(xdg, "fs-mcp")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

// cachedLatest records the last successfully-fetched tag so the updater has
// something to fall back on when GitHub is unreachable. It is NO LONGER the
// primary source of truth — resolveLatest always tries the network first and
// only reads this cache on failure. CheckedAt is retained for operator
// debugging (jq the file to see "last time I heard from GitHub").
type cachedLatest struct {
	CheckedAt     time.Time `json:"checked_at"`
	LatestVersion string    `json:"latest_version"`
}

func cachePath() (string, error) {
	dir, err := stateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "last-check.json"), nil
}

func readCache() (cachedLatest, error) {
	p, err := cachePath()
	if err != nil {
		return cachedLatest{}, err
	}
	body, err := os.ReadFile(p)
	if err != nil {
		return cachedLatest{}, err
	}
	var c cachedLatest
	if err := json.Unmarshal(body, &c); err != nil {
		return cachedLatest{}, err
	}
	return c, nil
}

func writeCache(c cachedLatest) error {
	p, err := cachePath()
	if err != nil {
		return err
	}
	body, err := json.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(p, body, 0o644)
}

// pinnedVersion returns the pin if install.sh wrote one (presence = pinned).
// Empty string means floating: track latest.
func pinnedVersion() (string, error) {
	dir, err := stateDir()
	if err != nil {
		return "", err
	}
	body, err := os.ReadFile(filepath.Join(dir, "pinned-version"))
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	v := string(body)
	for len(v) > 0 && (v[len(v)-1] == '\n' || v[len(v)-1] == '\r' || v[len(v)-1] == ' ') {
		v = v[:len(v)-1]
	}
	return v, nil
}

func mustWriteCache(latest string) error {
	return writeCache(cachedLatest{CheckedAt: time.Now(), LatestVersion: latest})
}
