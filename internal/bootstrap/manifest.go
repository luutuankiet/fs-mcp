package bootstrap

import "runtime"

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
type Dep struct {
	Name     string
	Version  string
	Required bool
	// URL returns the direct download URL for the given OS/arch/libc.
	// libc is "gnu", "musl", or "n/a" (darwin).
	URL func(os, arch, libc string) string
	// Extract describes how the downloaded asset is unpacked. "binary" = raw binary file; "tar.gz" = extract member; "gz" = gunzip single-file stream.
	Extract string
	// Member is the in-archive path for tar.gz archives.
	Member func(os, arch, libc string) string
	// VerifyFlag is the CLI flag to check version, e.g. "--version".
	VerifyFlag string
	// VersionContains, when matched in `--version` output, confirms the version. Substring match.
	VersionContains string
}

// Manifest is the set of deps fs-mcp manages. Updated each release.
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
			Version:  "1.8.1",
			Required: true,
			URL: func(os, arch, libc string) string {
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
				return "https://github.com/jqlang/jq/releases/download/jq-1.8.1/" + asset
			},
			Extract:         "binary",
			VerifyFlag:      "--version",
			VersionContains: "1.8.1",
		},
		{
			Name:     "yq",
			Version:  "v4.52.5",
			Required: true,
			URL: func(os, arch, libc string) string {
				return "https://github.com/mikefarah/yq/releases/download/v4.52.5/yq_" + os + "_" + arch
			},
			Extract:         "binary",
			VerifyFlag:      "--version",
			VersionContains: "4.52.5",
		},
		{
			Name:     "rg",
			Version:  "14.1.1",
			Required: true,
			URL: func(os, arch, libc string) string {
				switch os + "-" + arch {
				case "linux-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz"
				case "linux-arm64":
					if libc == "musl" {
						return ""
					}
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz"
				case "darwin-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-x86_64-apple-darwin.tar.gz"
				case "darwin-arm64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
				}
				return ""
			},
			Extract: "tar.gz",
			Member: func(os, arch, libc string) string {
				switch os + "-" + arch {
				case "linux-amd64":
					return "ripgrep-14.1.1-x86_64-unknown-linux-musl/rg"
				case "linux-arm64":
					return "ripgrep-14.1.1-aarch64-unknown-linux-gnu/rg"
				case "darwin-amd64":
					return "ripgrep-14.1.1-x86_64-apple-darwin/rg"
				case "darwin-arm64":
					return "ripgrep-14.1.1-aarch64-apple-darwin/rg"
				}
				return ""
			},
			VerifyFlag:      "--version",
			VersionContains: "ripgrep 14.1.1",
		},
		{
			Name:     "rtk",
			Version:  "0.37.1",
			Required: true,
			URL: func(os, arch, libc string) string {
				switch os + "-" + arch {
				case "linux-amd64":
					return "https://github.com/rtk-ai/rtk/releases/download/v0.37.1/rtk-x86_64-unknown-linux-musl.tar.gz"
				case "linux-arm64":
					if libc == "musl" {
						return ""
					}
					return "https://github.com/rtk-ai/rtk/releases/download/v0.37.1/rtk-aarch64-unknown-linux-gnu.tar.gz"
				case "darwin-amd64":
					return "https://github.com/rtk-ai/rtk/releases/download/v0.37.1/rtk-x86_64-apple-darwin.tar.gz"
				case "darwin-arm64":
					return "https://github.com/rtk-ai/rtk/releases/download/v0.37.1/rtk-aarch64-apple-darwin.tar.gz"
				}
				return ""
			},
			Extract:         "tar.gz",
			Member:          func(os, arch, libc string) string { return "rtk" },
			VerifyFlag:      "--version",
			VersionContains: "0.37.1",
		},
		{
			Name:     "duckdb",
			Version:  "v1.5.2",
			Required: true,
			URL: func(os, arch, libc string) string {
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
				return "https://github.com/duckdb/duckdb/releases/download/v1.5.2/" + asset
			},
			Extract:         "gz",
			VerifyFlag:      "--version",
			VersionContains: "v1.5.2",
		},
	}
}
