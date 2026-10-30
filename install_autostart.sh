#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point. Keep one canonical installer so runtime files,
# XDG paths, validation, and OS service configuration cannot drift apart.
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SOURCE_DIR/install.sh" --enable
