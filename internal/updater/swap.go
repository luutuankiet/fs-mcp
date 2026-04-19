package updater

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

const downloadTimeout = 30 * time.Second

// downloadAndSwap fetches the release tarball for `tag`, extracts the fs-mcp
// binary, and atomically replaces `exePath`. Linux and macOS both let you
// `rename(2)` over a binary that's currently executing because the kernel
// keeps the on-disk inode alive until the old process exits — so the swap
// is invisible to the running mcp client.
func downloadAndSwap(ctx context.Context, tag, exePath string) error {
	url := assetURL(tag, runtime.GOOS, runtime.GOARCH)
	ctx, cancel := context.WithTimeout(ctx, downloadTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("download %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("download %s: HTTP %d", url, resp.StatusCode)
	}

	gz, err := gzip.NewReader(resp.Body)
	if err != nil {
		return fmt.Errorf("gunzip: %w", err)
	}
	defer gz.Close()

	tmp, err := os.CreateTemp(filepath.Dir(exePath), ".fs-mcp.update.*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	cleanup := func() { _ = os.Remove(tmpPath) }

	tr := tar.NewReader(gz)
	found := false
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			tmp.Close()
			cleanup()
			return fmt.Errorf("untar: %w", err)
		}
		if filepath.Base(hdr.Name) != "fs-mcp" || hdr.Typeflag != tar.TypeReg {
			continue
		}
		if _, err := io.Copy(tmp, tr); err != nil {
			tmp.Close()
			cleanup()
			return fmt.Errorf("write tmp: %w", err)
		}
		found = true
		break
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return err
	}
	if !found {
		cleanup()
		return fmt.Errorf("tarball did not contain an fs-mcp binary")
	}
	if err := os.Chmod(tmpPath, 0o755); err != nil {
		cleanup()
		return err
	}
	if err := os.Rename(tmpPath, exePath); err != nil {
		cleanup()
		return fmt.Errorf("atomic swap: %w", err)
	}
	return nil
}
