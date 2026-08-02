#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT_DIR/assets/demo.srt"
OUTPUT="${1:-$ROOT_DIR/assets/demo.gif}"

command -v ffmpeg >/dev/null 2>&1 || {
    printf 'ffmpeg is required to render the demo GIF.\n' >&2
    exit 1
}

ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "color=c=0x0b1020:s=1100x550:d=9:r=12" \
    -filter_complex \
    "[0:v]subtitles='$SOURCE':force_style='FontName=DejaVu Sans Mono,FontSize=19,PrimaryColour=&H00E5E7EB,OutlineColour=&H000B1020,BorderStyle=1,Outline=0,Shadow=0,Alignment=7,MarginL=42,MarginV=38'[rendered];[rendered]split[p0][p1];[p0]palettegen=max_colors=96[p];[p1][p]paletteuse=dither=bayer:bayer_scale=3" \
    "$OUTPUT"

printf 'Rendered %s\n' "$OUTPUT"
