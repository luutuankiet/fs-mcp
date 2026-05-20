package bootstrap

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const fetchTagTimeout = 1500 * time.Millisecond

// FetchLatestTag asks GitHub for the latest release tag of the given repo.
// Returns the tag verbatim — preserves "v" prefix, "jq-" prefix, etc., so
// the manifest's URL/Member templates can interpolate it directly into the
// download path that upstream actually publishes.
//
// 1.5s timeout caps per-dep added cold-start latency. Tag resolution is
// parallel across deps in Ensure(), so total worst-case is ~1.5s regardless
// of dep count. Any network failure returns ("", error) and the caller falls
// back to the embedded floor in dep.Version.
//
// Mirrors the pattern in internal/updater (fs-mcp self-update). Duplicated
// rather than imported to avoid an internal/bootstrap → internal/updater
// dependency cycle (updater calls bootstrap.Manifest() in some test paths).
func FetchLatestTag(ctx context.Context, repo string) (string, error) {
	if repo == "" {
		return "", fmt.Errorf("no repo configured")
	}
	url := "https://api.github.com/repos/" + repo + "/releases/latest"
	ctx, cancel := context.WithTimeout(ctx, fetchTagTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "fs-mcp-bootstrap")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("github releases/latest %s: HTTP %d", repo, resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", err
	}
	var meta struct {
		TagName string `json:"tag_name"`
	}
	if err := json.Unmarshal(body, &meta); err != nil {
		return "", err
	}
	tag := strings.TrimSpace(meta.TagName)
	if tag == "" {
		return "", fmt.Errorf("github releases/latest %s: empty tag_name", repo)
	}
	return tag, nil
}
