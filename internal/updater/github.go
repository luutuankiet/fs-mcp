package updater

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	defaultRepo  = "luutuankiet/fs-mcp"
	githubTimeout = 1500 * time.Millisecond
)

// fetchLatestTag asks GitHub for the latest release tag (e.g. "v2.0.4"). The
// 1.5 s timeout is the cap on cold-start added latency on cache-miss days;
// any slower and we'd noticeably stretch fs-mcp's <10 ms cold-start budget.
func fetchLatestTag(ctx context.Context) (string, error) {
	url := "https://api.github.com/repos/" + defaultRepo + "/releases/latest"
	ctx, cancel := context.WithTimeout(ctx, githubTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "fs-mcp-self-updater")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("github releases/latest: HTTP %d", resp.StatusCode)
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
		return "", fmt.Errorf("github releases/latest: empty tag_name")
	}
	return tag, nil
}

// assetURL produces the same tarball URL shape that scripts/install.sh uses,
// so the auto-updater and the manual installer can never disagree about
// where the binary lives.
func assetURL(tag, goos, goarch string) string {
	stripped := strings.TrimPrefix(tag, "v")
	return fmt.Sprintf(
		"https://github.com/%s/releases/download/%s/fs-mcp_%s_%s_%s.tar.gz",
		defaultRepo, tag, stripped, goos, goarch,
	)
}
