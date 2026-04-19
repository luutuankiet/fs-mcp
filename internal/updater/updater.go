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

// fetchLatest is the network side of resolveLatest, extracted to a var so
// tests can swap it without real HTTP. Production value is fetchLatestTag
// from github.go; tests assign their own stub.
var fetchLatest = fetchLatestTag

// resolveLatest always asks GitHub first so fleet-wide releases propagate on
// the very next restart. The on-disk cache is kept only as an offline fallback
// for the "GitHub is slow/unreachable" case — never as the primary source of
// truth. 1.5 s is the worst-case added cold-start latency; see github.go.
func resolveLatest(ctx context.Context) (string, string, error) {
	tag, err := fetchLatest(ctx)
	if err == nil {
		_ = mustWriteCache(tag) // best-effort; stale cache stays if this fails
		return tag, "github", nil
	}
	// Network failed — fall back to whatever we saw last time. No TTL here:
	// an old cached version is still better than refusing to start the updater
	// and risking a no-op. `isNewer` in the caller will skip the swap if the
	// cached tag is ≤ current, so "stale cache == current" is a safe no-op.
	if c, cerr := readCache(); cerr == nil && c.LatestVersion != "" {
		return c.LatestVersion, "cache-fallback", nil
	}
	return "", "", err
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
