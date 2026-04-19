package tools

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// GSD Reader auto-dump — debounced fire-and-forget POST of a gsd-lite/
// project's markdown artifacts to a remote reader server. Mirrors v1.47.3
// src/fs_mcp/server.py:_trigger_gsd_dump. Opt-in via GSD_READER_REMOTE;
// no-op and zero cost when the env var is unset.
//
// Env:
//   GSD_READER_REMOTE  required base URL (e.g. https://gsd.example.org)
//   GSD_READER_USER    optional basic-auth username
//   GSD_READER_PASS    optional basic-auth password

var gsdArtifactNames = map[string]bool{
	"WORK.md":         true,
	"PROJECT.md":      true,
	"ARCHITECTURE.md": true,
}

const gsdDumpDebounce = 10 * time.Second

var (
	gsdDumpMu      sync.Mutex
	gsdDumpPending = map[string]*time.Timer{}
	gsdHTTPClient  = &http.Client{Timeout: 300 * time.Second}
)

// isGsdArtifact: true when path is <anywhere>/gsd-lite/<WORK|PROJECT|ARCHITECTURE>.md
func isGsdArtifact(p string) bool {
	if !gsdArtifactNames[filepath.Base(p)] {
		return false
	}
	return filepath.Base(filepath.Dir(p)) == "gsd-lite"
}

// triggerGsdDump schedules a debounced upload for the gsd-lite/ directory
// containing p. Multiple rapid commits to the same directory coalesce into
// one POST (last-writer-wins snapshot). Safe to call from any tool handler.
func triggerGsdDump(p string) {
	remote := os.Getenv("GSD_READER_REMOTE")
	if remote == "" {
		return
	}
	gsdDir := filepath.Dir(p)
	dumpKey := filepath.Join(gsdDir, "WORK.md")

	gsdDumpMu.Lock()
	defer gsdDumpMu.Unlock()
	if existing, ok := gsdDumpPending[dumpKey]; ok {
		existing.Stop()
	}
	gsdDumpPending[dumpKey] = time.AfterFunc(gsdDumpDebounce, func() {
		doGsdDump(remote, gsdDir, dumpKey)
	})
	log.Printf("[gsd-dump] Scheduled in %s: %s", gsdDumpDebounce, dumpKey)
}

func doGsdDump(remote, gsdDir, dumpKey string) {
	gsdDumpMu.Lock()
	delete(gsdDumpPending, dumpKey)
	gsdDumpMu.Unlock()

	worklog := filepath.Join(gsdDir, "WORK.md")
	workBody, err := os.ReadFile(worklog)
	if err != nil {
		log.Printf("[gsd-dump] Skip: %s not found (%v)", worklog, err)
		return
	}
	projectBody, _ := os.ReadFile(filepath.Join(gsdDir, "PROJECT.md"))
	archBody, _ := os.ReadFile(filepath.Join(gsdDir, "ARCHITECTURE.md"))

	payload, err := json.Marshal(map[string]string{
		"work":         string(workBody),
		"project":      string(projectBody),
		"architecture": string(archBody),
		"base_path":    gsdDir,
	})
	if err != nil {
		log.Printf("[gsd-dump] marshal: %v", err)
		return
	}

	url := strings.TrimRight(remote, "/") + "/upload-markdown/" + deriveProjectName(gsdDir)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		log.Printf("[gsd-dump] new-request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; gsd-lite-autodump/2.0)")
	if user := os.Getenv("GSD_READER_USER"); user != "" {
		pass := os.Getenv("GSD_READER_PASS")
		auth := base64.StdEncoding.EncodeToString([]byte(user + ":" + pass))
		req.Header.Set("Authorization", "Basic "+auth)
	}

	sizeKB := float64(len(payload)) / 1024
	log.Printf("[gsd-dump] Uploading %.0fKB -> %s", sizeKB, url)

	resp, err := gsdHTTPClient.Do(req)
	if err != nil {
		log.Printf("[gsd-dump] Network error: %v", err)
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	trimmed := strings.TrimSpace(string(body))
	if resp.StatusCode >= 400 {
		log.Printf("[gsd-dump] HTTP %d: %s", resp.StatusCode, trimmed)
		return
	}
	log.Printf("[gsd-dump] Done (%d): %s", resp.StatusCode, trimmed)
}

// deriveProjectName: last 2 path segments of the gsd-lite/ parent,
// joined with "/". Mirrors the v1 CLI naming convention so uploads
// land in the same slot across the v1→v2 transition.
func deriveProjectName(gsdDir string) string {
	parts := []string{}
	for _, part := range strings.Split(filepath.Clean(gsdDir), string(filepath.Separator)) {
		if part != "" {
			parts = append(parts, part)
		}
	}
	switch len(parts) {
	case 0:
		return "unknown"
	case 1:
		return parts[0]
	default:
		return parts[len(parts)-2] + "/" + parts[len(parts)-1]
	}
}
