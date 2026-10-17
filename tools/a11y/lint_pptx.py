#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["python-pptx==1.0.2", "coloraide==8.13"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Accessibility lint for the lecture decks (Lectures/Slides/L*.pptx).

    uv run tools/a11y/lint_pptx.py [--json OUT] [DECK.pptx ...]

Rules:
  pptx/picture-no-alt        picture without alt text (descr) that is not marked decorative
  pptx/picture-placeholder-alt  alt text that is a file name, "undefined", "Picture 3", ...
  pptx/template-image-not-decorative  template logos (figures.toml `ignore`) not marked
                             decorative; counted per deck
  pptx/video-no-alt          video/audio placeholder without a description
  pptx/no-document-title     deck without a document title (File > Info > Title); the
                             slide PDF's title and a screen reader's first announcement
  pptx/slide-no-title        slide without a title placeholder (or with an empty one);
                             counted per deck
  pptx/table-no-header       data table (two or more rows) without a header row (tblPr firstRow)
  pptx/low-contrast          text whose colour and background are both known and have a
                             contrast ratio under 4.5:1 (3:1 for large text)
  pptx/duplicate-title       (warning) a slide title repeated in the same deck
  pptx/small-text            (warning) text under 18 pt, counted per deck; template text
                             repeated on many slides (footers) and source links are
                             incidental and not counted
  pptx/embedded-video        (warning) embedded video: check it has captions; a silent
                             video (its description says "no sound" or "silent") needs
                             only its description (WCAG 1.2.1), so it is not flagged
"""

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402
from findings import REPO, Finding, write  # noqa: E402

PLACEHOLDER_ALT = re.compile(
    r"^\s*(undefined|image|picture|graphic|photo|screenshot|figure|untitled)?\s*\d*\s*$"
    r"|\.(png|jpe?g|gif|svg|bmp|tiff?|emf|wmf)\s*$"
    r"|^(picture|graphic|image|google shape)[\s;_-]*\d",
    re.I,
)


def ignored_hashes():
    manifest = REPO / "Lectures/Slides/figures.toml"
    return set(tomllib.loads(manifest.read_text()).get("ignore", [])) if manifest.exists() else set()


def lint(path, ignore):
    prs = dr.open_deck(path)
    rel = path.relative_to(REPO).as_posix()
    theme = dr.Theme(prs)
    out = []
    no_title = template_not_decorative = small = 0
    seen_titles = {}

    def finding(rule, message, where="", **kw):
        out.append(Finding("pptx", rel, rule, message, where=where, **kw))

    if not (prs.core_properties.title or "").strip():
        finding("pptx/no-document-title", "deck has no document title (File > Info > Title)")

    # Template text repeated on many slides (footers such as "SYSTEMS ENGINEERING"):
    # incidental, like a logotype, so not held to the size guideline.
    seen = {}
    all_slides = dr.slides(prs)
    for _no, sl in all_slides:
        for t in {" ".join(dr.text_of(sp).split()) for sp in dr.xp(sl._element, ".//p:sp")} - {""}:
            seen[t] = seen.get(t, 0) + 1
    boilerplate = {t for t, n in seen.items() if n >= max(3, len(all_slides) // 3) and len(t) < 60}

    for no, slide in all_slides:
        sid = slide.slide_id
        root = slide._element
        title = dr.title_text(slide)
        if not title:
            no_title += 1
        else:
            if title in seen_titles:
                finding(
                    "pptx/duplicate-title",
                    f"title '{title[:50]}' also on slide {seen_titles[title]}",
                    f"slide {sid}",
                    severity="warning",
                )
            seen_titles.setdefault(title, no)
        layout = slide.slide_layout
        master = layout.slide_master
        page_bg = theme.background(root) or theme.background(layout._element) or theme.master_bg
        layers = theme.layers(master._element) + theme.layers(layout._element)

        # Pictures (including video/audio placeholders, which are not figures).
        for pic in dr.xp(root, ".//p:pic"):
            if dr.is_decorative(pic):
                continue
            descr = (dr.cnvpr(pic).get("descr") or "").strip()
            where = f"slide {sid} / {dr.locator(pic)}"
            if dr.is_media(pic):
                if not descr:
                    finding("pptx/video-no-alt", f"video on slide {no} has no description", where)
                silent = re.search(r"\bno sound\b|\bsilent\b", descr, re.I)
                if dr.xp(pic, ".//p14:media") and not silent:
                    finding(
                        "pptx/embedded-video",
                        f"embedded video on slide {no}: check it has captions",
                        where,
                        severity="warning",
                    )
                continue
            data = dr.blob(slide.part, dr.picture_rid(pic))
            if data is not None and hashlib.sha1(data).hexdigest() in ignore:
                template_not_decorative += 1
                continue
            if not descr:
                finding("pptx/picture-no-alt", f"picture on slide {no} has no alt text", where)
            elif PLACEHOLDER_ALT.search(descr):
                finding(
                    "pptx/picture-placeholder-alt",
                    f"picture on slide {no} has placeholder alt text '{descr[:40]}'",
                    where,
                )

        # Tables.
        # Data tables need a header row; a single-row table (a list of fields, e.g. a
        # packet format) has no data under it, so it is described with alt text instead.
        for frame in dr.xp(root, ".//p:graphicFrame[.//a:tbl]"):
            if len(dr.xp(frame, ".//a:tbl/a:tr")) > 1 and not dr.xp(frame, ".//a:tbl/a:tblPr[@firstRow='1']"):
                finding(
                    "pptx/table-no-header",
                    f"table on slide {no} has no header row",
                    f"slide {sid} / table {dr.cnvpr(frame).get('id')}",
                )

        # Text: size and contrast, wherever both colours are known. Shapes are visited
        # back to front, so each one sees the filled shapes below it.
        for el in dr.xp(root, ".//p:sp | .//p:pic"):
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
            low = False
            incidental = " ".join(dr.text_of(el).split()) in boilerplate
            for run in dr.xp(el, ".//a:r"):
                text = dr.text_of(run).strip()
                if not text:
                    continue
                rpr = run.find(dr.q("a:rPr"))
                sz = rpr.get("sz") if rpr is not None else None
                size = int(sz) / 100 if sz else None
                source_link = text.startswith(("http://", "https://", "www.")) or (
                    rpr is not None and dr.xp(rpr, "./a:hlinkClick")
                )
                if size is not None and size < 18 and not incidental and not source_link:
                    small += 1
                fg = theme.run_colour(rpr)
                if fg and fg != dr.UNKNOWN:
                    bold = rpr.get("b") == "1"
                    large = size is not None and (size >= 24 or (bold and size >= 18.66))
                    if dr.contrast(fg, bg) < (3.0 if large else 4.5):
                        low = True
            if low:
                finding(
                    "pptx/low-contrast",
                    f"low-contrast text on slide {no}",
                    f"slide {sid} / shape {dr.cnvpr(el).get('id')}",
                )

    if no_title:
        finding("pptx/slide-no-title", "slides without a title placeholder", count=no_title)
    if template_not_decorative:
        finding(
            "pptx/template-image-not-decorative", "template logos not marked decorative", count=template_not_decorative
        )
    if small:
        finding("pptx/small-text", "text runs under 18 pt", severity="warning", count=small)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*", help="decks to lint (default: Lectures/Slides/L*.pptx)")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    paths = [Path(p).resolve() for p in args.decks if Path(p).name.startswith("L")] if args.decks else sdf.decks()
    ignore = ignored_hashes()
    findings = [f for p in paths for f in lint(p, ignore)]
    if args.json:
        write(findings, args.json)
    totals = {}
    for f in findings:
        totals[(f.severity, f.rule)] = totals.get((f.severity, f.rule), 0) + f.count
    for (sev, rule), n in sorted(totals.items()):
        print(f"{sev:7s} {rule:36s} {n}")


if __name__ == "__main__":
    main()
