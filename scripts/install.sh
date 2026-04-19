#!/usr/bin/env sh
# fs-mcp installer. Downloads a release tarball for the current OS/arch into
# $HOME/.local/bin. Linux + macOS only.
#
# Usage:
#   install.sh             # latest, future cold-starts auto-update
#   install.sh v2.0.3      # pin to v2.0.3 (writes pinned-version marker)
#   FS_MCP_VERSION=v2.0.3 install.sh   # equivalent to the above

set -e

REPO="luutuankiet/fs-mcp"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/fs-mcp"

case "$(uname -s)" in
  Linux)  OS=linux ;;
  Darwin) OS=darwin ;;
  *) echo "unsupported OS: $(uname -s). fs-mcp supports linux and darwin only." >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64)  ARCH=amd64 ;;
  arm64|aarch64) ARCH=arm64 ;;
  *) echo "unsupported arch: $(uname -m). fs-mcp supports amd64 and arm64 only." >&2; exit 1 ;;
esac

mkdir -p "$BIN_DIR" "$STATE_DIR"

PIN_ARG="${1:-}"
VERSION="${FS_MCP_VERSION:-$PIN_ARG}"
if [ -z "$VERSION" ]; then
  VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p')"
fi
if [ -z "$VERSION" ]; then
  echo "could not resolve a version (pass an arg, set FS_MCP_VERSION, or check network)" >&2
  exit 1
fi

ASSET="fs-mcp_${VERSION#v}_${OS}_${ARCH}.tar.gz"
URL="https://github.com/$REPO/releases/download/$VERSION/$ASSET"

TMP="$(mktemp -d)"
trap "rm -rf $TMP" EXIT

echo "fs-mcp installer: $VERSION $OS/$ARCH"
echo "  -> $URL"

curl -fsSL "$URL" -o "$TMP/fs-mcp.tar.gz"
tar -xzf "$TMP/fs-mcp.tar.gz" -C "$TMP"
install -m 0755 "$TMP/fs-mcp" "$BIN_DIR/fs-mcp"

# Pin marker: presence freezes auto-update on cold-start. Explicit pin → write;
# tracking-latest install → remove.
if [ -n "$PIN_ARG" ] || [ -n "$FS_MCP_VERSION" ]; then
  echo "$VERSION" > "$STATE_DIR/pinned-version"
  echo "fs-mcp pinned to $VERSION (auto-update disabled until you re-install without a version)"
else
  rm -f "$STATE_DIR/pinned-version"
fi

echo
echo "fs-mcp installed -> $BIN_DIR/fs-mcp"
echo

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your PATH. Add it with:" ; echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

"$BIN_DIR/fs-mcp" --version
