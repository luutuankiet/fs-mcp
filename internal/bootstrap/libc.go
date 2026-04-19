package bootstrap

import (
	"os"
	"runtime"
)

// Libc returns "gnu", "musl", or "n/a" for the current host.
//
// On linux we prefer "gnu" whenever the glibc dynamic interpreter is present —
// many distros (Debian/Ubuntu) ship the musl interpreter as a side package
// without using musl as their userland, so a bare presence-check for musl
// false-positives. Glibc presence is the stronger signal: if a glibc loader
// is installed, glibc-targeting binaries will run.
//
// We only return "musl" when no glibc interpreter is found AND a musl one is
// (Alpine and similar). Fallback is "gnu" — least-risky for unknown distros
// because most release-track linux is glibc.
//
// On darwin we return "n/a" because macOS binaries link against system
// libraries that ship with every Mac.
func Libc() string {
	if runtime.GOOS != "linux" {
		return "n/a"
	}
	gnu := []string{
		"/lib64/ld-linux-x86-64.so.2",
		"/lib/ld-linux-x86-64.so.2",
		"/lib/ld-linux-aarch64.so.1",
		"/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1",
		"/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
	}
	for _, p := range gnu {
		if _, err := os.Stat(p); err == nil {
			return "gnu"
		}
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
	return "gnu"
}
