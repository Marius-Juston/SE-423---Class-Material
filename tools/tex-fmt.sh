#!/bin/sh
# Format the LaTeX handouts with tex-fmt (settings: tex-fmt.toml at the repo root).
#
#   sh tools/tex-fmt.sh                 format every handout in place
#   sh tools/tex-fmt.sh FILE.tex ...    format these files
#   sh tools/tex-fmt.sh --check [FILE]  change nothing; exit 1 if a file would change
#
# "Handouts" are the homeworks, the labs and the syllabus (Homeworks/*.tex,
# Labs/*.tex, syllabus.tex). The shared macro files (header.tex, checkoff.tex, ...)
# and the TikZ figures are laid out by hand and are not formatted.
#
# The formatter only changes the layout of the source: indentation, trailing
# spaces, runs of blank lines. The built PDF/HTML keep the same text. You never
# have to run this yourself: the pre-commit hook formats the files you commit, and
# CI points out files that were edited elsewhere (Overleaf) and are not formatted.
#
# tex-fmt is one small program. A pinned release is downloaded once into
# ~/.cache/se423-tools and checked against its SHA-256; a `tex-fmt` of the same
# version on the PATH is used instead when there is one.
set -eu

VERSION=0.5.7  # released 2026-03-25; when changing it, update the four checksums

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

find_tex_fmt() {
  if command -v tex-fmt >/dev/null 2>&1 && [ "$(tex-fmt --version 2>/dev/null)" = "tex-fmt $VERSION" ]; then
    command -v tex-fmt
    return
  fi
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) asset=x86_64-linux sum=d0e30b9b811fdc1e66a9328d5c95e9d8e585019288ca39c07f643e0796bcc4a3 ;;
    Linux-aarch64 | Linux-arm64) asset=aarch64-linux sum=ad5a6c8a84f61de711f2d7659191cd7e813ad1881b384abed60df420e1eabdd1 ;;
    Darwin-x86_64) asset=x86_64-macos sum=e39311252562a3608474639e182782ca51f319fa50a8abfca9cb09e59ed7f7ac ;;
    Darwin-arm64) asset=aarch64-macos sum=f88ad74c446d6dcfec9657ef600d61f65f0ccdcf8401e2909bb3b093d23fff80 ;;
    *)
      echo "tex-fmt.sh: no pinned tex-fmt build for $(uname -s) $(uname -m);" >&2
      echo "  install tex-fmt $VERSION yourself (https://github.com/WGUNDERWOOD/tex-fmt)." >&2
      return 1
      ;;
  esac
  dir="${XDG_CACHE_HOME:-$HOME/.cache}/se423-tools/tex-fmt-$VERSION"
  if [ ! -x "$dir/tex-fmt" ]; then
    mkdir -p "$dir"
    tmp="$dir/download.$$"
    url="https://github.com/WGUNDERWOOD/tex-fmt/releases/download/v$VERSION/tex-fmt-$asset.tar.gz"
    if ! curl -fsSL --retry 3 -o "$tmp" "$url"; then
      rm -f "$tmp"
      echo "tex-fmt.sh: could not download $url" >&2
      return 1
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      got=$(sha256sum "$tmp" | cut -d' ' -f1)
    else
      got=$(shasum -a 256 "$tmp" | cut -d' ' -f1)
    fi
    if [ "$got" != "$sum" ]; then
      rm -f "$tmp"
      echo "tex-fmt.sh: checksum mismatch for $url (got $got)" >&2
      return 1
    fi
    tar -xzf "$tmp" -C "$dir" tex-fmt
    rm -f "$tmp"
    chmod +x "$dir/tex-fmt"
  fi
  echo "$dir/tex-fmt"
}

check=
[ "${1:-}" = "--check" ] && { check=1; shift; }

cd "$root"
if [ "$#" -eq 0 ]; then
  set -- Homeworks/*.tex Labs/*.tex syllabus.tex
fi

exe=$(find_tex_fmt) || exit 2

# tex-fmt turns a tab into one indent step, also inside code blocks, where the
# PDF showed it 8 columns wide: code would shift. Tabs do not belong in the
# handouts' code (they do not paste reliably either), so say so instead.
tabs=$(grep -l "$(printf '\t')" "$@" 2>/dev/null || true)
if [ -n "$tabs" ] && [ -z "$check" ]; then
  for f in $tabs; do
    echo "tex-fmt.sh: $f has tab characters; they become spaces (check code blocks keep their alignment)." >&2
  done
fi

if [ -n "$check" ]; then
  # Quiet unless something is off: one line per file that would change.
  "$exe" --check --config "$root/tex-fmt.toml" "$@" 2>&1 | grep -v 'Indent does not return to zero' >&2 || true
  "$exe" --check --config "$root/tex-fmt.toml" "$@" >/dev/null 2>&1
else
  "$exe" --config "$root/tex-fmt.toml" "$@" 2>&1 | grep -v 'Indent does not return to zero' >&2 || true
fi
