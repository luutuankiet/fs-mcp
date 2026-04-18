package bootstrap

import (
	"os"
	"runtime"
)

// Libc returns "gnu", "musl", or "n/a" for the current host.
// On linux we probe /lib for the musl dynamic interpreter — its presence is
// sufficient evidence the host runs musl userland. On darwin we return "n/a"
// because macOS binaries always link against system libraries that ship with
// every Mac.
//
// If neither musl nor gnu interpreters are found on linux, we fall back to
// "gnu" (overwhelming majority case) and let the installed binary's first-run
// verify step surface the mismatch.
func Libc() string {
	if runtime.GOOS != "linux" {
		return "n/a"
	}
	musl := []string{
		"/lib/ld-musl-x86_64.so.1",
		"/lib/ld-musl-aarch64.so.1",
		"/lib/ld-musl-armhf.so.1",
	}
	for _, p := range musl {
		if _, err := os.Stat(p); err == nil {
			return "musl"
		}
	}
	gnu := []string{
		"/lib64/ld-linux-x86-64.so.2",
		"/lib/ld-linux-x86-64.so.2",
		"/lib/ld-linux-aarch64.so.1",
		"/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1",
	}
	for _, p := range gnu {
		if _, err := os.Stat(p); err == nil {
			return "gnu"
		}
	}
	return "gnu"
}
