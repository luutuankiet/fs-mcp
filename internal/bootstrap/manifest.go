package bootstrap

import (
	"runtime"
	"strings"
)

// Platform returns the current OS/arch tuple used to select binary assets.
// Linux and macOS only. Windows is not supported.
func Platform() (os, arch string, ok bool) {
	switch runtime.GOOS {
	case "linux", "darwin":
	default:
		return "", "", false
	}
	switch runtime.GOARCH {
	case "amd64", "arm64":
	default:
		return "", "", false
	}
	return runtime.GOOS, runtime.GOARCH, true
}

// Dep describes one managed CLI dependency.
//
// Versioning model (v2.0.7+): the embedded Version is a FLOOR, not a pin.
// On cold start, Ensure() asks GitHub's releases/latest API for each dep's
// current tag (via Repo) and prefers that. Version is only used when:
//   - Repo is empty (auto-upgrade explicitly disabled for this dep), OR
//   - the upstream API is unreachable AND no managed binary exists yet
//     (first-install on a host with broken network), OR
//   - the operator sets FS_MCP_PIN_DEPS=1 (air-gap / fleet-freeze override).
//
// URL / Member / VersionContains accept the resolved tag so the same template
// works across every upstream release. The tag is whatever GitHub returns in
// tag_name, verbatim ("v0.40.0", "jq-1.8.1", "15.1.0", "v1.5.2", ...).
type Dep struct {
	Name string
	// Version is the floor tag — must be a valid past release of Repo,
	// formatted exactly as upstream's tag_name.
	Version  string
	Required bool
	// Repo is the "owner/repo" string for GitHub's releases/latest API.
	// Empty disables auto-upgrade — the dep stays pinned to Version forever.
	Repo string
	// URL returns the direct download URL for the given OS/arch/libc/tag.
	// libc is "gnu", "musl", or "n/a" (darwin).
	URL func(os, arch, libc, tag string) string
	// Extract: "binary" = raw binary file; "tar.gz" = extract Member; "gz" = gunzip stream.
	Extract string
	// Member is the in-archive path for tar.gz archives. Takes tag because
	// some upstreams (e.g. ripgrep) embed the version in the directory name.
	Member func(os, arch, libc, tag string) string
	// VerifyFlag is the CLI flag to check version, e.g. "--version".
	VerifyFlag string
	// VersionContains returns the expected substring in --version output for
	// the given tag — used to confirm a downloaded binary matches the target.
	VersionContains func(tag string) string
}

// Manifest is the set of deps fs-mcp manages. Floors are bumped occasionally
// as a "this is known to exist upstream" sanity baseline — actual installed
// versions track GitHub releases/latest at cold start.
//
// Linkage strategy per dep:
//   - jq   — statically linked for all linux variants; no libc branching.
//   - yq   — Go binary (CGO_ENABLED=0), fully static; no libc branching.
//   - rg   — linux-amd64 uses `-unknown-linux-musl` (static-pie); linux-arm64 only ships `-unknown-linux-gnu` (glibc-dynamic). No upstream arm64 musl build.
//   - rtk  — same shape as rg: musl-static for x86_64, gnu-dynamic for aarch64.
//   - duckdb — no static build exists; picks gnu/musl variant per libc.
//
// Gap: linux-arm64-musl (e.g. Alpine on Pi) cannot auto-install rg / rtk —
// upstream does not publish binaries. Documented as a known limitation.
func Manifest() []Dep {
	return []Dep{
		{
			Name:     "jq",
			Version:  "jq-1.8.1",
			Required: true,
			Repo:     "jqlang/jq",
			URL: func(os, arch, libc, tag string) string {
				asset := ""
				switch os + "-" + arch {
				case "linux-amd64":
					asset = "jq-linux-amd64"
				case "linux-arm64":
					asset = "jq-linux-arm64"
				case "darwin-amd64":
					asset = "jq-macos-amd64"
				case "darwin-arm64":
					asset = "jq-macos-arm64"
				}
				if asset == "" {
					return ""
				}
				return "https://github.com/jqlang/jq/releases/download/" + tag + "/" + asset
			},
			Extract:    "binary",
			VerifyFlag: "--version",
			// jq prints "jq-1.8.1" — the tag IS the version line.
			VersionContains: func(tag string) string { return tag },
		},
		{
			Name:     "yq",
			Version:  "v4.52.5",
			Required: true,
			Repo:     "mikefarah/yq",
			URL: func(os, arch, libc, tag string) string {
				return "https://github.com/mikefarah/yq/releases/download/" + tag + "/yq_" + os + "_" + arch
			},
			Extract:    "binary",
			VerifyFlag: "--version",
			// yq prints "yq (https://github.com/mikefarah/yq/) version v4.53.2"
			VersionContains: func(tag string) string { return strings.TrimPrefix(tag, "v") },
		},
		{
			Name:     "rg",
			Version:  "14.1.1",
			Required: true,
			Repo:     "BurntSushi/ripgrep",
			URL: func(os, arch, libc, tag string) string {
				ver := strings.TrimPrefix(tag, "v")
				switch os + "-" + arch {
				case "linux-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/" + tag + "/ripgrep-" + ver + "-x86_64-unknown-linux-musl.tar.gz"
				case "linux-arm64":
					if libc == "musl" {
						return ""
					}
					return "https://github.com/BurntSushi/ripgrep/releases/download/" + tag + "/ripgrep-" + ver + "-aarch64-unknown-linux-gnu.tar.gz"
				case "darwin-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/" + tag + "/ripgrep-" + ver + "-x86_64-apple-darwin.tar.gz"
				case "darwin-arm64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/" + tag + "/ripgrep-" + ver + "-aarch64-apple-darwin.tar.gz"
				}
				return ""
			},
			Extract: "tar.gz",
			Member: func(os, arch, libc, tag string) string {
				ver := strings.TrimPrefix(tag, "v")
				switch os + "-" + arch {
				case "linux-amd64":
					return "ripgrep-" + ver + "-x86_64-unknown-linux-musl/rg"
				case "linux-arm64":
					return "ripgrep-" + ver + "-aarch64-unknown-linux-gnu/rg"
				case "darwin-amd64":
					return "ripgrep-" + ver + "-x86_64-apple-darwin/rg"
				case "darwin-arm64":
					return "ripgrep-" + ver + "-aarch64-apple-darwin/rg"
				}
				return ""
			},
			VerifyFlag: "--version",
			// ripgrep prints "ripgrep 14.1.1\n..."
			VersionContains: func(tag string) string { return "ripgrep " + strings.TrimPrefix(tag, "v") },
		},
		{
			Name:     "rtk",
			Version:  "v0.37.1",
			Required: true,
			Repo:     "rtk-ai/rtk",
			URL: func(os, arch, libc, tag string) string {
				switch os + "-" + arch {
				case "linux-amd64":
					return "https://github.com/rtk-ai/rtk/releases/download/" + tag + "/rtk-x86_64-unknown-linux-musl.tar.gz"
				case "linux-arm64":
					if libc == "musl" {
						return ""
					}
					return "https://github.com/rtk-ai/rtk/releases/download/" + tag + "/rtk-aarch64-unknown-linux-gnu.tar.gz"
				case "darwin-amd64":
					return "https://github.com/rtk-ai/rtk/releases/download/" + tag + "/rtk-x86_64-apple-darwin.tar.gz"
				case "darwin-arm64":
					return "https://github.com/rtk-ai/rtk/releases/download/" + tag + "/rtk-aarch64-apple-darwin.tar.gz"
				}
				return ""
			},
			Extract:    "tar.gz",
			Member:     func(os, arch, libc, tag string) string { return "rtk" },
			VerifyFlag: "--version",
			// rtk prints "rtk 0.40.0"
			VersionContains: func(tag string) string { return strings.TrimPrefix(tag, "v") },
		},
		{
			Name:     "duckdb",
			Version:  "v1.5.2",
			Required: true,
			Repo:     "duckdb/duckdb",
			URL: func(os, arch, libc, tag string) string {
				suffix := ""
				if libc == "musl" {
					suffix = "-musl"
				}
				asset := ""
				switch os + "-" + arch {
				case "linux-amd64":
					asset = "duckdb_cli-linux-amd64" + suffix + ".gz"
				case "linux-arm64":
					asset = "duckdb_cli-linux-arm64" + suffix + ".gz"
				case "darwin-amd64":
					asset = "duckdb_cli-osx-amd64.gz"
				case "darwin-arm64":
					asset = "duckdb_cli-osx-arm64.gz"
				}
				if asset == "" {
					return ""
				}
				return "https://github.com/duckdb/duckdb/releases/download/" + tag + "/" + asset
			},
			Extract:    "gz",
			VerifyFlag: "--version",
			// duckdb prints "v1.5.2 abc123" — tag matches the v-prefixed first token.
			VersionContains: func(tag string) string { return tag },
		},
	}
}
