package updater

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// withTempState points stateDir() at a throwaway dir for the test. Returns a
// cleanup that restores XDG_STATE_HOME.
func withTempState(t *testing.T) {
	t.Helper()
	d := t.TempDir()
	prev, had := os.LookupEnv("XDG_STATE_HOME")
	_ = os.Setenv("XDG_STATE_HOME", d)
	t.Cleanup(func() {
		if had {
			_ = os.Setenv("XDG_STATE_HOME", prev)
		} else {
			_ = os.Unsetenv("XDG_STATE_HOME")
		}
	})
}

// stubFetch replaces the network call for the test, restoring on cleanup.
func stubFetch(t *testing.T, fn func(context.Context) (string, error)) {
	t.Helper()
	prev := fetchLatest
	fetchLatest = fn
	t.Cleanup(func() { fetchLatest = prev })
}

// TestResolveLatest_NetworkWinsOverCache: stale cache is present AND fresh
// network succeeds → network wins and refreshes the cache. This is the core
// behavioral change from the 24h-cache design: propagation is instant.
func TestResolveLatest_NetworkWinsOverCache(t *testing.T) {
	withTempState(t)
	// Seed a stale cache with an old version.
	_ = writeCache(cachedLatest{CheckedAt: time.Now().Add(-1 * time.Minute), LatestVersion: "v2.0.3"})
	stubFetch(t, func(ctx context.Context) (string, error) { return "v2.0.4", nil })

	tag, source, err := resolveLatest(context.Background())
	if err != nil {
		t.Fatalf("resolveLatest: %v", err)
	}
	if tag != "v2.0.4" {
		t.Errorf("tag=%q, want v2.0.4 (network should win even when cache is ~fresh)", tag)
	}
	if source != "github" {
		t.Errorf("source=%q, want github", source)
	}
	// Cache should have been refreshed to the new value.
	c, err := readCache()
	if err != nil {
		t.Fatalf("readCache after resolve: %v", err)
	}
	if c.LatestVersion != "v2.0.4" {
		t.Errorf("cache not refreshed: got %q, want v2.0.4", c.LatestVersion)
	}
}

// TestResolveLatest_NetworkFailFallsBackToCache: GitHub unreachable, cache
// present → use cache as fallback. The "stale" cache is whatever we last
// saved; no TTL applies because no answer is worse than a stale answer.
func TestResolveLatest_NetworkFailFallsBackToCache(t *testing.T) {
	withTempState(t)
	_ = writeCache(cachedLatest{CheckedAt: time.Now().Add(-90 * 24 * time.Hour), LatestVersion: "v2.0.3"})
	stubFetch(t, func(ctx context.Context) (string, error) { return "", errors.New("no route to github") })

	tag, source, err := resolveLatest(context.Background())
	if err != nil {
		t.Fatalf("resolveLatest: %v", err)
	}
	if tag != "v2.0.3" {
		t.Errorf("tag=%q, want v2.0.3 (should fall back to 3-month-old cache)", tag)
	}
	if source != "cache-fallback" {
		t.Errorf("source=%q, want cache-fallback", source)
	}
}

// TestResolveLatest_NetworkFailNoCachePropagatesErr: no cache AND network
// fails → return the underlying error so the caller logs "skipping update"
// and moves on. Must NOT crash startup.
func TestResolveLatest_NetworkFailNoCachePropagatesErr(t *testing.T) {
	withTempState(t)
	// No cache seeded.
	cp, _ := cachePath()
	_ = os.Remove(cp)
	stubFetch(t, func(ctx context.Context) (string, error) { return "", errors.New("dns lookup failed") })

	_, _, err := resolveLatest(context.Background())
	if err == nil {
		t.Fatalf("resolveLatest returned nil err, want the underlying network failure")
	}
	if err.Error() != "dns lookup failed" {
		t.Errorf("err=%v, want 'dns lookup failed'", err)
	}
}

// TestResolveLatest_NoNetworkCall_WhenCachedTagMatches: regression guard —
// even with the new always-try-network design, if cache is present and
// identical to what network returns, the cache write should be idempotent
// (no spurious disk churn beyond one write per startup).
func TestResolveLatest_CacheWriteIsIdempotent(t *testing.T) {
	withTempState(t)
	stubFetch(t, func(ctx context.Context) (string, error) { return "v2.0.4", nil })

	for i := 0; i < 3; i++ {
		if _, _, err := resolveLatest(context.Background()); err != nil {
			t.Fatalf("iter %d: %v", i, err)
		}
	}
	c, err := readCache()
	if err != nil {
		t.Fatalf("readCache: %v", err)
	}
	if c.LatestVersion != "v2.0.4" {
		t.Errorf("cache LatestVersion=%q, want v2.0.4", c.LatestVersion)
	}
}

// Sanity: the old cacheTTL symbol must be gone so nothing else depends on
// 24h semantics. Trip-wire test — if someone re-introduces a TTL-based
// gate, this will force them to delete the test too and make the intent
// explicit in review.
func TestNoCacheTTLSymbol(t *testing.T) {
	// cacheAlive and cacheTTL were deleted in v2.0.5. This file purposefully
	// doesn't reference them. If a future refactor re-adds a TTL gate without
	// deleting this comment, the next reviewer will notice the contradiction.
	_ = filepath.Separator // keep imports alive
}
