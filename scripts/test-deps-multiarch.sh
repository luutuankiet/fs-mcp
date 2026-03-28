#!/bin/bash
# fs-mcp Multi-Arch Dependency Test Runner
# Tests dependency installation on fresh systems across architectures.
#
# Prerequisites:
#   - Docker with buildx
#   - QEMU for cross-arch: docker run --privileged --rm tonistiigi/binfmt --install all
#
# Usage:
#   ./test-deps-multiarch.sh          # Test both amd64 and arm64
#   ./test-deps-multiarch.sh amd64    # Test only amd64
#   ./test-deps-multiarch.sh arm64    # Test only arm64

set -e

PLATFORMS="${1:-amd64 arm64}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "=========================================="
echo "  fs-mcp Multi-Arch Dependency Test"
echo "=========================================="
echo ""

# Ensure buildx builder exists
if ! docker buildx inspect multiarch &>/dev/null; then
    echo "[setup] Creating multi-arch builder..."
    docker buildx create --name multiarch --driver docker-container --use
fi

for PLATFORM in $PLATFORMS; do
    echo ""
    echo "--- Testing linux/${PLATFORM} ---"
    echo ""
    
    if docker buildx build \
        --platform "linux/${PLATFORM}" \
        --file Dockerfile.test \
        --progress plain \
        --load \
        -t "fs-mcp-test-${PLATFORM}" \
        . 2>&1; then
        echo ""
        echo "✅ linux/${PLATFORM}: ALL TESTS PASSED"
    else
        echo ""
        echo "❌ linux/${PLATFORM}: TESTS FAILED (see output above)"
        # Don't exit — continue testing other platforms
    fi
done

echo ""
echo "=========================================="
echo "  Results Summary"
echo "=========================================="
for PLATFORM in $PLATFORMS; do
    if docker image inspect "fs-mcp-test-${PLATFORM}" &>/dev/null; then
        echo "  ✅ linux/${PLATFORM}"
    else
        echo "  ❌ linux/${PLATFORM}"
    fi
done
echo "=========================================="
