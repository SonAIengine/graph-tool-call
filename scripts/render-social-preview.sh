#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT_DIR/assets/social_preview.html"
OUTPUT="$ROOT_DIR/assets/social_preview.png"
CHROMIUM="${CHROMIUM:-$(command -v chromium || command -v chromium-browser || command -v google-chrome)}"
if [[ -z "${CAPTURE:-}" ]]; then
    if [[ "$CHROMIUM" == /snap/* ]]; then
        CAPTURE="$HOME/snap/chromium/common/graph-tool-call-social-preview.png"
    else
        CAPTURE="$(mktemp --suffix=.png)"
    fi
fi

"$CHROMIUM" \
    --headless \
    --no-sandbox \
    --disable-gpu \
    --hide-scrollbars \
    --force-device-scale-factor=1 \
    --window-size=1200,630 \
    --screenshot="$CAPTURE" \
    "file://$SOURCE" >/dev/null 2>&1

cp "$CAPTURE" "$OUTPUT"
cp "$OUTPUT" "$ROOT_DIR/website/static/img/social_preview.png"
rm -f "$CAPTURE"
printf 'Rendered %s and website copy.\n' "$OUTPUT"
