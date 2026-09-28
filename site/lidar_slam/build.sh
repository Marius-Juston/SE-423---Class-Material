#!/usr/bin/env bash
# Compile the walkthrough's JSX sources into plain browser scripts.
#
#   usage: build.sh <lidar_slam_dir> [<out_dir>]
#
# Reads <lidar_slam_dir>/src/*.jsx and writes <out_dir>/<name>.js
# (default <out_dir> = <lidar_slam_dir>/dist). Each file stays a separate
# classic script (no bundling); JSX becomes React.createElement calls, so
# slam.html only needs the React UMD builds — no in-browser Babel.
set -euo pipefail

ESBUILD_VERSION="0.28.2"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <lidar_slam_dir> [<out_dir>]" >&2
  exit 2
fi

src_dir="$1/src"
out_dir="${2:-$1/dist}"

if [[ ! -d "$src_dir" ]]; then
  echo "error: $src_dir does not exist" >&2
  exit 1
fi

shopt -s nullglob
sources=("$src_dir"/*.jsx)
if [[ ${#sources[@]} -eq 0 ]]; then
  echo "error: no .jsx files in $src_dir" >&2
  exit 1
fi

mkdir -p "$out_dir"
npx --yes "esbuild@${ESBUILD_VERSION}" "${sources[@]}" \
  --outdir="$out_dir" \
  --jsx=transform \
  --target=es2020 \
  --log-level=warning

echo "built ${#sources[@]} scripts into $out_dir"
