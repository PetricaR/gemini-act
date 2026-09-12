#!/usr/bin/env bash
# ==============================================================================
# Obscura Installer Script
# ==============================================================================
# Downloads and installs the latest obscura headless browser binary for the
# current operating system and CPU architecture.
#
# Supported platforms:
#   - Linux x86_64 (amd64)
#   - Linux aarch64 (arm64)
#   - macOS Apple Silicon (arm64)
#   - macOS Intel (x86_64)
# ==============================================================================

set -euo pipefail

DEST_DIR="${1:-/usr/local/bin}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)
    case "$ARCH" in
      x86_64|amd64)
        TAR_NAME="obscura-x86_64-linux.tar.gz"
        ;;
      aarch64|arm64)
        TAR_NAME="obscura-aarch64-linux.tar.gz"
        ;;
      *)
        echo "Error: Unsupported Linux architecture: $ARCH" >&2
        exit 1
        ;;
    esac
    ;;
  Darwin)
    case "$ARCH" in
      arm64)
        TAR_NAME="obscura-aarch64-macos.tar.gz"
        ;;
      x86_64)
        TAR_NAME="obscura-x86_64-macos.tar.gz"
        ;;
      *)
        echo "Error: Unsupported macOS architecture: $ARCH" >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "Error: Unsupported operating system: $OS" >&2
    exit 1
    ;;
esac

URL="https://github.com/h4ckf0r0day/obscura/releases/latest/download/$TAR_NAME"

echo "Downloading Obscura for $OS ($ARCH) from $URL..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL "$URL" -o "$TMP_DIR/$TAR_NAME"
tar -xzf "$TMP_DIR/$TAR_NAME" -C "$TMP_DIR"

# Check if target destination directory is writable without sudo
if [ ! -d "$DEST_DIR" ]; then
  mkdir -p "$DEST_DIR" 2>/dev/null || sudo mkdir -p "$DEST_DIR"
fi

if [ -w "$DEST_DIR" ]; then
  cp "$TMP_DIR/obscura" "$DEST_DIR/"
  [ -f "$TMP_DIR/obscura-worker" ] && cp "$TMP_DIR/obscura-worker" "$DEST_DIR/"
  chmod +x "$DEST_DIR/obscura"*
else
  echo "Target directory $DEST_DIR is not writable by current user, copying to $PROJECT_ROOT instead..."
  cp "$TMP_DIR/obscura" "$PROJECT_ROOT/"
  [ -f "$TMP_DIR/obscura-worker" ] && cp "$TMP_DIR/obscura-worker" "$PROJECT_ROOT/"
  chmod +x "$PROJECT_ROOT/obscura"*
  DEST_DIR="$PROJECT_ROOT"
fi

echo "Obscura successfully installed to $DEST_DIR/obscura"
"$DEST_DIR/obscura" --version || true
