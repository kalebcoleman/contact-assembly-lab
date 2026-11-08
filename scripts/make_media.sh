#!/usr/bin/env bash
# Make the README/catalog media from a captured run (1080p, 30 fps of sim time).
#
#   scripts/make_media.sh <video.mp4> <out-stem> [speed] [crop] [still-crop]
#   scripts/make_media.sh --closeup <closeup.png> <out.jpg> [crop]
#
# Video mode writes <out-stem>.mp4 (960 wide, `speed`x, default 8),
# <out-stem>.gif (720 wide, 12 fps, 2*speed x) and <out-stem>_final.png (last
# frame, cropped on the baseplate). Crops are ffmpeg w:h:x:y in the 1920x1080
# frame and default to the work area of the capture camera in run.py.
# Close-up mode crops a close-up still (from run_sweep.py --capture) to a
# 1280x720 JPEG.
set -euo pipefail

if [[ "${1:-}" == "--closeup" ]]; then
  in=$2 out=$3 crop=${4:-1280:720:260:300}
  ffmpeg -nostdin -loglevel error -y -i "$in" -vf "crop=$crop" -q:v 3 "$out"
  du -h "$out"
  exit 0
fi

in=$1 out=$2 speed=${3:-8} crop=${4:-1280:720:340:280} still=${5:-640:480:895:230}
ffmpeg -nostdin -loglevel error -y -i "$in" \
  -vf "crop=$crop,setpts=PTS/$speed,fps=30,scale=960:-2:flags=lanczos" \
  -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p -movflags +faststart -an "$out.mp4"
# Denoise before the palette: per-frame render noise otherwise triples the GIF size.
ffmpeg -nostdin -loglevel error -y -i "$in" -filter_complex \
  "crop=$crop,setpts=PTS/$((speed * 2)),hqdn3d=4:4:8:8,fps=12,scale=720:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  "$out.gif"
ffmpeg -nostdin -loglevel error -y -sseof -0.2 -i "$in" -vf "crop=$still" \
  -frames:v 1 -update 1 "${out}_final.png"
du -h "$out.mp4" "$out.gif" "${out}_final.png"
