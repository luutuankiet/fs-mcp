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
	// URL returns the direct download URL for the given OS/arch.
	URL func(os, arch string) string
	// Extract describes how the downloaded asset is unpacked. "binary" = raw binary file; "tar.gz" = extract member; "zip" = extract member.
	Extract string
	// Member is the in-archive path (for tar.gz/zip) or empty for "binary".
	Member func(os, arch string) string
	// VerifyFlag is the CLI flag to check version, e.g. "--version".
	VerifyFlag string
	// VersionContains, when matched in `--version` output, confirms the version. Substring match.
	VersionContains string
}

// Manifest is the set of deps fs-mcp manages. Updated each release.
func Manifest() []Dep {
	return []Dep{
		{
			Name:     "jq",
			Version:  "1.8.1",
			Required: true,
			URL: func(os, arch string) string {
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
			URL: func(os, arch string) string {
				asset := "yq_" + os + "_" + arch
				return "https://github.com/mikefarah/yq/releases/download/v4.52.5/" + asset
			},
			Extract:         "binary",
			VerifyFlag:      "--version",
			VersionContains: "4.52.5",
		},
		{
			Name:     "rg",
			Version:  "14.1.1",
			Required: true,
			URL: func(os, arch string) string {
				switch os + "-" + arch {
				case "linux-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz"
				case "linux-arm64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-unknown-linux-gnu.tar.gz"
				case "darwin-amd64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-x86_64-apple-darwin.tar.gz"
				case "darwin-arm64":
					return "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-aarch64-apple-darwin.tar.gz"
				}
				return ""
			},
			Extract: "tar.gz",
			Member: func(os, arch string) string {
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
			Version:  "0.37.0",
			Required: false,
			URL: func(os, arch string) string {
				return "https://github.com/rtk-ai/rtk/releases/download/v0.37.0/rtk-" + os + "-" + arch
			},
			Extract:         "binary",
			VerifyFlag:      "--version",
			VersionContains: "0.37.0",
		},
	}
}
