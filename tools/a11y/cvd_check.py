#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["coloraide==8.13"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Colour-vision-deficiency check for the figure SVGs.

    uv run tools/a11y/cvd_check.py [--json OUT] [FIGURE.svg ...]

For each SVG in Lectures/Figures/svg/ (default), collects the saturated colours used
for fills and strokes (series colours, not greys), simulates protanopia, deuteranopia
and tritanopia (Machado et al. 2009, full severity) and reports colour pairs that are
clearly different in normal vision (ΔE2000 >= 15) but nearly the same for one of
those viewers (ΔE2000 < 8). Such a figure needs a second cue (line style, markers,
labels) or different colours.

Rule:
  cvd/confusable-colours   (warning) per figure and deficiency, counting confusable pairs
"""

import argparse
import itertools
import re
import sys
from pathlib import Path

from coloraide import Color

sys.path.insert(0, str(Path(__file__).resolve().parent))
from findings import REPO, Finding, write  # noqa: E402

FIGURES = REPO / "Lectures/Figures/svg"
DISTINCT = 15.0  # ΔE2000 between two colours that are meant to be told apart
CONFUSED = 8.0  # ΔE2000 below which they look alike
MIN_CHROMA = 0.05  # OKLCh chroma: greys and near-greys carry no hue information
MIN_USES = 2  # ignore colours used only once (often a single annotation)
MAX_CATEGORICAL = 12  # more distinct colours than this is a colour map (viridis, ...), not categories
DEFICIENCIES = ("protan", "deutan", "tritan")
NAMES = {"protan": "protanopia", "deutan": "deuteranopia", "tritan": "tritanopia"}
COLOUR = re.compile(
    r"""(?:fill|stroke|stop-color|color)\s*[:=]\s*["']?\s*(#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgb\([^)]*\))"""
)


def colours(svg_text):
    """Saturated colours used at least MIN_USES times: {hex: uses}."""
    counts = {}
    for raw in COLOUR.findall(svg_text):
        try:
            c = Color(raw).convert("srgb")
        except ValueError:
            continue
        if c.convert("oklch")["chroma"] < MIN_CHROMA:
            continue
        key = c.to_string(hex=True)
        counts[key] = counts.get(key, 0) + 1
    return {k: n for k, n in counts.items() if n >= MIN_USES}


def confusable(palette):
    """{deficiency: [(a, b), ...]} of pairs distinct normally but alike under it.
    A continuous colour map's neighbouring shades are not meant to be told apart, so
    figures with more than MAX_CATEGORICAL colours are not checked."""
    out = {}
    if len(palette) > MAX_CATEGORICAL:
        return out
    for a, b in itertools.combinations(sorted(palette), 2):
        ca, cb = Color(a), Color(b)
        if ca.delta_e(cb, method="2000") < DISTINCT:
            continue
        for d in DEFICIENCIES:
            sa, sb = ca.clone().filter(d, method="machado"), cb.clone().filter(d, method="machado")
            if sa.delta_e(sb, method="2000") < CONFUSED:
                out.setdefault(d, []).append((a, b))
    return out


def check(paths):
    findings = []
    for path in paths:
        rel = path.relative_to(REPO).as_posix()
        for d, pairs in confusable(colours(path.read_text(errors="replace"))).items():
            shown = ", ".join(f"{a}/{b}" for a, b in pairs[:4])
            findings.append(
                Finding(
                    "cvd",
                    rel,
                    "cvd/confusable-colours",
                    f"colours that look alike with {NAMES[d]}: {shown}; add a second cue (line style, marker, label)",
                    where=d,
                    severity="warning",
                    count=len(pairs),
                )
            )
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("figures", nargs="*")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    paths = [Path(p).resolve() for p in args.figures] or sorted(FIGURES.glob("*.svg"))
    findings = check(paths)
    if args.json:
        write(findings, args.json)
    for f in findings:
        print(f"{f.severity:7s} {f.file} [{f.where}] x{f.count}: {f.message}")


if __name__ == "__main__":
    main()
