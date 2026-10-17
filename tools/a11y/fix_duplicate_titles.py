#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["python-pptx==1.0.2", "coloraide==8.13", "lxml==6.1.2", "pillow==12.3.0"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Make slide titles unique within each deck by numbering repeated titles.

    uv run tools/a11y/fix_duplicate_titles.py [--dry-run] [DECK.pptx ...]

Screen-reader users move through a deck by slide title, so a run of slides all titled
"Dead-Reckoning" is a list of identical entries. Every slide whose title occurs more
than once in its deck gets " (k/N)" appended (k-th of N in slide order), as
accessibility guidance recommends for content continued over several slides. The
suffix is added to the title's last text run, so it keeps the title's formatting.

A slide is left unnumbered when the numbered title would not fit its title box on the
same line (measured with the course font at the run's size); at most one slide per
group, so titles stay unique. Titles that already end in "(k/N)" are left alone.
Only the title text of each changed slide part changes; render and compare afterwards.
"""

import argparse
import re
import sys
from pathlib import Path

from lxml import etree
from PIL import ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

NUMBERED = re.compile(r"\(\d+/\d+\)\s*$")
FONTS = sdf.REPO / "fonts"
_fonts = {}


def font(bold, pt):
    key = (bold, pt)
    if key not in _fonts:
        name = "Bold" if bold else "Regular"
        _fonts[key] = ImageFont.truetype(str(FONTS / f"AtkinsonHyperlegibleNext-{name}.otf"), int(pt * 100))
    return _fonts[key]


def fits(title_shape, slide_part_root, new_last_line):
    """Whether the title's last line, with the suffix, fits the title box width."""
    runs = dr.xp(title_shape, ".//a:r")
    sizes = [
        int(r.find(dr.q("a:rPr")).get("sz")) / 100
        for r in runs
        if r.find(dr.q("a:rPr")) is not None and r.find(dr.q("a:rPr")).get("sz")
    ]
    if not sizes:
        return True  # inherited size: titles are pinned by fix_slide_titles, so rare; assume it fits
    bold = any((r.find(dr.q("a:rPr")) is not None and r.find(dr.q("a:rPr")).get("b") == "1") for r in runs)
    width_pt = font(bold, max(sizes)).getlength(new_last_line) / 100
    box = dr.box(title_shape)
    body_pr = dr.xp(title_shape, "./p:txBody/a:bodyPr")
    insets = 0
    if body_pr:
        insets = int(body_pr[0].get("lIns", 91440)) + int(body_pr[0].get("rIns", 91440))
    else:
        insets = 2 * 91440
    available_pt = (box[2] - insets) / 12700 if box else 1e9
    return width_pt <= available_pt * 0.97


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    paths = [Path(p).resolve() for p in args.decks] or sdf.decks()
    for path in paths:
        prs = dr.open_deck(path)
        deck = sdf.Deck(path)
        groups = {}
        for no, slide in dr.slides(prs):
            title = " ".join((dr.title_text(slide) or "").split())
            if title and not NUMBERED.search(title):
                groups.setdefault(title, []).append((no, slide))
        numbered = skipped = 0
        for title, items in groups.items():
            if len(items) < 2:
                continue
            n = len(items)
            plan = []
            for k, (no, slide) in enumerate(items, 1):
                part = str(slide.part.partname).lstrip("/")
                root = etree.fromstring(deck.data[part])
                shape = next(sp for sp in dr.xp(root, ".//p:sp") if dr.ph_type(sp) in dr.TITLE_TYPES)
                last_line = re.split(r"\n", dr.text_of(shape).replace("\v", "\n"))[-1]
                lines = []
                for p in dr.xp(shape, "./p:txBody/a:p"):
                    segs = [[]]
                    for el in p:
                        if dr.local(el) == "br":
                            segs.append([])
                        elif dr.local(el) == "r":
                            segs[-1].append(dr.text_of(el))
                    lines += ["".join(s) for s in segs]
                last_line = next((ln for ln in reversed(lines) if ln.strip()), last_line)
                suffix = f" ({k}/{n})"
                plan.append((no, part, root, shape, fits(shape, root, last_line.rstrip() + suffix), suffix))
            misfits = [p for p in plan if not p[4]]
            if len(misfits) > 1:
                print(f"{path.name}: '{title}' does not fit numbered on {len(misfits)} slides; left as is")
                skipped += len(plan)
                continue
            for no, part, root, shape, ok, suffix in plan:
                if not ok:
                    print(f"{path.name} slide {no}: '{title}' left unnumbered (would wrap)")
                    skipped += 1
                    continue
                runs = [r for r in dr.xp(shape, ".//a:r") if dr.text_of(r).strip()]
                t = runs[-1].find(dr.q("a:t"))
                t.text = t.text.rstrip() + suffix
                deck.data[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                deck.changed = True
                numbered += 1
        print(f"{path.name}: {numbered} title(s) numbered, {skipped} left")
        if deck.changed and not args.dry_run:
            deck.save()


if __name__ == "__main__":
    main()
