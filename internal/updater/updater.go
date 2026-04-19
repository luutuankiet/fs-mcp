// Package updater self-updates the fs-mcp binary on cold start so that the
// MCP client only ever has to "restart the server" to roll out a new
// version — same UX as v1's `uvx fs-mcp@latest`, no per-host SSH.
package updater

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// Result reports what CheckAndUpdate did so the caller can re-exec when the
// binary on disk has changed.
type Result struct {
	Updated      bool   // true → exePath has been replaced; caller should re-exec
	FromVersion  string // current binary's version
	ToVersion    string // newly-installed version (only set if Updated)
	Skipped      string // human-readable reason we did nothing (e.g. "pinned")
}

// CheckAndUpdate is the single entry point called from main(). It must not
// block fs-mcp startup beyond the configured timeouts even if the network
// is broken — any error short-circuits to "skip update, run current binary."
func CheckAndUpdate(ctx context.Context, currentVersion, exePath string) (Result, error) {
	if currentVersion == "" || currentVersion == "dev" {
		return Result{Skipped: "dev build"}, nil
	}
	if pin, err := pinnedVersion(); err == nil && pin != "" {
		return Result{Skipped: "pinned to " + pin}, nil
	}

	latest, source, err := resolveLatest(ctx)
	if err != nil {
		return Result{Skipped: "could not resolve latest: " + err.Error()}, nil
	}

	if !isNewer(latest, currentVersion) {
		return Result{Skipped: fmt.Sprintf("on latest (%s, source=%s)", latest, source)}, nil
	}

	if err := downloadAndSwap(ctx, latest, exePath); err != nil {
		return Result{Skipped: "swap failed: " + err.Error()}, err
	}

	return Result{Updated: true, FromVersion: currentVersion, ToVersion: latest}, nil
}

// resolveLatest prefers the daily cache to keep cold-start cost ~zero. It
// only hits the network when the cache is missing or older than 24 h.
func resolveLatest(ctx context.Context) (string, string, error) {
	if c, err := readCache(); err == nil && cacheAlive(c) {
		return c.LatestVersion, "cache", nil
	}
	tag, err := fetchLatestTag(ctx)
	if err != nil {
		return "", "", err
	}
	_ = mustWriteCache(tag) // best-effort cache write; never block on it
	return tag, "github", nil
}

// isNewer compares two semver-ish tags ("v2.0.4" vs "v2.0.3"). Strictly
// greater on the first dotted segment that differs. Pre-release suffixes
// (e.g. "v2.0.4-rc1") are ignored — fs-mcp doesn't ship pre-releases yet.
func isNewer(latest, current string) bool {
	a := splitSemver(latest)
	b := splitSemver(current)
	for i := 0; i < 3; i++ {
		if a[i] > b[i] {
			return true
		}
		if a[i] < b[i] {
			return false
		}
	}
	return false
}

func splitSemver(v string) [3]int {
	v = strings.TrimPrefix(v, "v")
	if i := strings.IndexAny(v, "-+"); i >= 0 {
		v = v[:i]
	}
	parts := strings.SplitN(v, ".", 3)
	out := [3]int{}
	for i := 0; i < len(parts) && i < 3; i++ {
		n := 0
		for _, c := range parts[i] {
			if c < '0' || c > '9' {
				break
			}
			n = n*10 + int(c-'0')
		}
		out[i] = n
	}
	return out
}

// ErrSkipped is returned when the caller should treat the result as "no
// action needed" — kept around so future callers can branch on it cleanly.
var ErrSkipped = errors.New("updater: skipped")
