package tools

import (
	"bufio"
	"os"
	"strings"
)

var networkFSTypes = map[string]bool{
	"nfs":       true,
	"nfs4":      true,
	"cifs":      true,
	"smbfs":     true,
	"fuse.sshfs": true,
}

// isNetworkFS checks /proc/mounts (Linux only) to see if path is on a
// network filesystem. On darwin we return false; rg's --one-file-system
// flag is usually enough there.
func isNetworkFS(path string) bool {
	f, err := os.Open("/proc/mounts")
	if err != nil {
		return false
	}
	defer f.Close()
	best := ""
	bestType := ""
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) < 3 {
			continue
		}
		mountpoint, fstype := fields[1], fields[2]
		if strings.HasPrefix(path, mountpoint) && len(mountpoint) >= len(best) {
			best = mountpoint
			bestType = fstype
		}
	}
	return networkFSTypes[bestType]
}
