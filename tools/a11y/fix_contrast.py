#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["python-pptx==1.0.2", "coloraide==8.13", "lxml==6.1.2"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Fix low-contrast coloured text on the slides with the smallest colour change.

    uv run tools/a11y/fix_contrast.py [--dry-run] [DECK.pptx ...]

Finds the same runs as lint_pptx.py's pptx/low-contrast rule (a run colour and the
background behind it both known, contrast under 4.5:1, or 3:1 for large text) and moves
the run's colour in OKLCh lightness only, keeping hue and chroma, until it reaches 4.6:1
against that background: darker on light backgrounds, lighter on dark ones. Only the
colour attribute of the flagged runs changes; each changed slide part is rewritten and
the deck saved with the byte-faithful writer. Render and compare the slides afterwards.
"""

import argparse
import sys
from pathlib import Path

from coloraide import Color
from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

TARGET = 4.6


def accessible(fg, bg):
    """fg (RRGGBB) moved in lightness until it has TARGET contrast with bg."""
    c = Color(f"#{fg}").convert("oklch")
    step = -0.005 if Color(f"#{bg}").luminance() > 0.18 else 0.005
    for _ in range(200):
        if c.convert("srgb").fit().contrast(f"#{bg}", method="wcag21") >= TARGET:
            break
        c["lightness"] = min(max(c["lightness"] + step, 0), 1)
    return c.convert("srgb").fit().to_string(hex=True).upper().lstrip("#")


def low_contrast_runs(theme, slide):
    """[(run element, fg, bg)] of the slide's runs failing the contrast rule."""
    out = []
    layout = slide.slide_layout
    page_bg = theme.background(slide._element) or theme.background(layout._element) or theme.master_bg
    layers = theme.layers(layout.slide_master._element) + theme.layers(layout._element)
    for el in dr.xp(slide._element, ".//p:sp | .//p:pic"):
        lay = theme.layer(el)
        if dr.local(el) == "pic":
            if lay:
                layers.append(lay)
            continue
        b = dr.box(el)
        bg = lay[1] if lay else (dr.background_under(b, layers, page_bg) if b else page_bg)
        if lay:
            layers.append(lay)
        if dr.ph_type(el) in ("sldNum", "dt", "ftr") or bg in (None, dr.UNKNOWN):
            continue
        for run in dr.xp(el, ".//a:r"):
            if not dr.text_of(run).strip():
                continue
            rpr = run.find(dr.q("a:rPr"))
            fg = theme.run_colour(rpr)
            if not fg or fg == dr.UNKNOWN:
                continue
            sz = rpr.get("sz")
            size = int(sz) / 100 if sz else None
            large = size is not None and (size >= 24 or (rpr.get("b") == "1" and size >= 18.66))
            if dr.contrast(fg, bg) < (3.0 if large else 4.5):
                out.append((run, fg, bg))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    paths = [Path(p).resolve() for p in args.decks] or sdf.decks()
    for path in paths:
        prs = dr.open_deck(path)
        theme = dr.Theme(prs)
        deck = sdf.Deck(path)
        fixed = []
        for no, slide in dr.slides(prs):
            runs = low_contrast_runs(theme, slide)
            if not runs:
                continue
            part = str(slide.part.partname).lstrip("/")
            root = etree.fromstring(deck.data[part])
            for run, fg, bg in runs:
                new = accessible(fg, bg)
                # The same run in the deck's own copy of the part (same document position).
                ns = {k: v for k, v in run.nsmap.items() if k}
                target = root.xpath(run.getroottree().getpath(run), namespaces=ns)[0]
                fill = dr.xp(target, "./a:rPr/a:solidFill")[0]
                for child in list(fill):
                    fill.remove(child)
                etree.SubElement(fill, dr.q("a:srgbClr"), val=new)
                fixed.append((no, dr.text_of(run).strip()[:30], fg, new, bg))
            deck.data[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            deck.changed = True
        for no, text, fg, new, bg in fixed:
            print(f"{path.name} slide {no}: #{fg} -> #{new} on #{bg}  {text!r}")
        if deck.changed and not args.dry_run:
            deck.save()


if __name__ == "__main__":
    main()
