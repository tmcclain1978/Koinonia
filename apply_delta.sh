#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${1:-.}"
echo "[Delta] Applying V18 (charting) into: $TARGET_DIR"
rsync -a --checksum --human-readable --progress "$SRC_DIR"/ "$TARGET_DIR"/
echo "[Delta] Done. Add <link rel=\"stylesheet\" href=\"/static/css/charting.css\"> and <script src=\"/static/js/charting_pro.js\">"
