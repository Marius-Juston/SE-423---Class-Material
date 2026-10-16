#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Accessibility lint for the lecture decks (Lectures/Slides/L*.pptx).

    uv run tools/a11y/lint_pptx.py [--json OUT] [DECK.pptx ...]

Rules:
  pptx/picture-no-alt        picture without alt text (descr) that is not marked decorative
  pptx/picture-placeholder-alt  alt text that is a file name, "undefined", "Picture 3", ...
  pptx/template-image-not-decorative  template logos (figures.toml `ignore`) not marked
                             decorative; counted per deck
  pptx/video-no-alt          video/audio placeholder without a description
  pptx/slide-no-title        slide without a title placeholder (or with an empty one);
                             counted per deck
  pptx/table-no-header       table without a header row (tblPr firstRow)
  pptx/low-contrast          text whose colour and background are both known and have a
                             contrast ratio under 4.5:1 (3:1 for large text)
  pptx/duplicate-title       (warning) a slide title repeated in the same deck
  pptx/small-text            (warning) text under 18 pt, counted per deck
  pptx/embedded-video        (warning) embedded video: check it has captions
"""

import argparse
import colorsys
import hashlib
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import sync_deck_figures as sdf  # noqa: E402
from findings import REPO, Finding, write  # noqa: E402

PLACEHOLDER_ALT = re.compile(
    r"^\s*(undefined|image|picture|graphic|photo|screenshot|figure|untitled)?\s*\d*\s*$"
    r"|\.(png|jpe?g|gif|svg|bmp|tiff?|emf|wmf)\s*$"
    r"|^(picture|graphic|image|google shape)[\s;_-]*\d",
    re.I,
)
DECORATIVE = re.compile(r'<adec:decorative\b[^>]*val="1"')
UNKNOWN = "?"  # a background we cannot reduce to one colour (picture, gradient, ...)


# ------------------------------------------------------------------ colours
def relative_luminance(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(int(rgb[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Theme:
    """Resolves DrawingML colours (srgbClr / schemeClr with lumMod/lumOff/tint/shade)."""

    def __init__(self, deck):
        theme_part = next(n for n in deck.data if re.match(r"ppt/theme/theme\d+\.xml$", n))
        theme = deck.data[theme_part].decode()
        scheme = re.search(r"<a:clrScheme\b.*?</a:clrScheme>", theme, re.S)[0]
        self.scheme = {}
        for name, body in re.findall(r"<a:(dk1|lt1|dk2|lt2|accent\d|hlink|folHlink)>(.*?)</a:\1>", scheme, re.S):
            m = re.search(r'(?:srgbClr val|lastClr)="([0-9A-Fa-f]{6})"', body)
            if m:
                self.scheme[name] = m[1].upper()
        styles = re.search(r"<a:bgFillStyleLst>(.*?)</a:bgFillStyleLst>", theme, re.S)
        self.bg_styles = re.findall(r"<a:(solidFill|gradFill|blipFill|pattFill|noFill)\b", styles[1]) if styles else []
        master = next(n for n in deck.data if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", n))
        cmap = re.search(r"<p:clrMap\b([^>]*)/>", deck.data[master].decode())
        self.map = dict(re.findall(r'(\w+)="(\w+)"', cmap[1])) if cmap else {}
        self.master_bg = self.fill(deck.data[master].decode(), bg=True)

    def resolve(self, el):
        """el: the XML of one colour element; returns RRGGBB or None."""
        m = re.match(r'<a:(srgbClr|schemeClr|sysClr|prstClr)\b[^>]*?(?:val|lastClr)="(\w+)"', el)
        if not m:
            return None
        kind, val = m[1], m[2]
        if kind == "srgbClr":
            rgb = val.upper()
        elif kind == "sysClr":
            last = re.search(r'lastClr="([0-9A-Fa-f]{6})"', el)
            rgb = last[1].upper() if last else None
        elif kind == "prstClr":
            rgb = {"black": "000000", "white": "FFFFFF", "red": "FF0000"}.get(val)
        else:
            rgb = self.scheme.get(self.map.get(val, val))
        if not rgb:
            return None
        h, lum, s = colorsys.rgb_to_hls(*(int(rgb[i : i + 2], 16) / 255 for i in (0, 2, 4)))
        mods = dict(re.findall(r'<a:(lumMod|lumOff|tint|shade)\s+val="(\d+)"', el))
        if "lumMod" in mods or "lumOff" in mods:
            lum = lum * int(mods.get("lumMod", 100000)) / 100000 + int(mods.get("lumOff", 0)) / 100000
        r, g, b = colorsys.hls_to_rgb(h, min(max(lum, 0), 1), s)
        if "tint" in mods:
            t = int(mods["tint"]) / 100000
            r, g, b = (c * t + (1 - t) for c in (r, g, b))
        if "shade" in mods:
            t = int(mods["shade"]) / 100000
            r, g, b = (c * t for c in (r, g, b))
        return "".join(f"{round(c * 255):02X}" for c in (r, g, b))

    def fill(self, xml, bg=False):
        """Fill colour of a shape's spPr (or a slide/master background): RRGGBB,
        UNKNOWN for picture/gradient/pattern fills, or None when there is no fill."""
        if bg:
            m = re.search(r"<p:bg>.*?</p:bg>", xml, re.S)
            if not m:
                return None
            xml = m[0]
            ref = re.search(r'<p:bgRef\b[^>]*idx="(\d+)"[^>]*>(.*?)</p:bgRef>', xml, re.S)
            if ref:
                i = int(ref[1]) - 1001
                if 0 <= i < len(self.bg_styles) and self.bg_styles[i] == "solidFill":
                    return self.resolve(ref[2].strip())
                return UNKNOWN
        else:
            xml = re.sub(r"<a:ln\b.*?</a:ln>", "", xml, flags=re.S)  # outline colour is not a fill
        if re.search(r"<a:(gradFill|blipFill|pattFill)\b", xml):
            return UNKNOWN
        m = re.search(r"<a:solidFill>\s*(<a:\w+Clr\b.*?(?:/>|</a:\w+Clr>))", xml, re.S)
        return (self.resolve(m[1]) or UNKNOWN) if m else None


# ------------------------------------------------------------------ geometry
def box(sp):
    m = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>', sp)
    return tuple(map(int, m.groups())) if m else None


def layer_of(el, theme):
    """(box, colour) for a shape or picture that hides what is behind it, else None."""
    b = box(el)
    if not b:
        return None
    if el.startswith("<p:pic"):
        return b, UNKNOWN
    sp_pr = re.search(r"<p:spPr\b.*?</p:spPr>", el, re.S)
    colour = theme.fill(sp_pr[0]) if sp_pr else None
    return (b, colour) if colour else None


def filled_shapes(xml, theme):
    """[(box, colour)] of shapes and pictures in z-order (back to front)."""
    return [lay for el in re.findall(r"<p:sp>.*?</p:sp>|<p:pic>.*?</p:pic>", xml, re.S) if (lay := layer_of(el, theme))]


def background_under(b, layers, default):
    """Colour of the topmost filled shape containing the centre of box b."""
    cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
    for (x, y, w, h), colour in reversed(layers):
        if x <= cx <= x + w and y <= cy <= y + h:
            return colour
    return default


# ------------------------------------------------------------------ lint
def ignored_hashes():
    m = (
        tomllib.loads((REPO / "Lectures/Slides/figures.toml").read_text())
        if (REPO / "Lectures/Slides/figures.toml").exists()
        else {}
    )
    return set(m.get("ignore", []))


def title_text(slide_xml):
    """Text of the slide's title placeholder, or None if there is none."""
    for sp in re.findall(r"<p:sp>.*?</p:sp>", slide_xml, re.S):
        if re.search(r'<p:ph\b[^>]*type="(?:title|ctrTitle)"', sp):
            return "".join(re.findall(r"<a:t>([^<]*)</a:t>", sp)).strip()
    return None


def lint(path, ignore):
    deck = sdf.Deck(path)
    rel = path.relative_to(REPO).as_posix()
    theme = Theme(deck)
    out = []
    no_title = template_not_decorative = small = 0
    seen_titles = {}

    for no, sid, part in deck.slides():
        x = deck.data[part].decode()
        title = title_text(x)
        if not title:
            no_title += 1
        else:
            if title in seen_titles:
                out.append(
                    Finding(
                        "pptx",
                        rel,
                        "pptx/duplicate-title",
                        f"title '{title[:50]}' also on slide {seen_titles[title]}",
                        where=f"slide {sid}",
                        severity="warning",
                    )
                )
            seen_titles.setdefault(title, no)
        slide_bg = theme.fill(x, bg=True)
        layout = deck.rels(part)
        layout_part = next((t for t in layout.values() if "slideLayout" in t), None)
        layout_bg = theme.fill(deck.data[layout_part].decode(), bg=True) if layout_part else None
        page_bg = slide_bg or layout_bg or theme.master_bg
        master_part = (
            next((t for t in deck.rels(layout_part).values() if "slideMaster" in t), None) if layout_part else None
        )
        under = (filled_shapes(deck.data[master_part].decode(), theme) if master_part else []) + (
            filled_shapes(deck.data[layout_part].decode(), theme) if layout_part else []
        )

        # Pictures (including video/audio placeholders, which Deck.pictures() skips).
        rels = deck.rels(part)
        for m in re.finditer(r"<p:pic>.*?</p:pic>", x, re.S):
            pic = m[0]
            cnv = re.search(r"<p:cNvPr\b[^>]*>", pic)[0]
            descr = re.search(r'descr="([^"]*)"', cnv)
            descr = descr[1] if descr else ""
            cid = re.search(r'a16:creationId [^>]*id="(\{[^"]+\})"', pic)
            shape_id = re.search(r'\bid="(\d+)"', cnv)[1]
            where = f"slide {sid} / {cid[1] if cid else 'shape-' + shape_id}"
            if DECORATIVE.search(pic):
                continue
            if sdf.MEDIA.search(pic):
                if not descr.strip():
                    out.append(
                        Finding(
                            "pptx", rel, "pptx/video-no-alt", f"video on slide {no} has no description", where=where
                        )
                    )
                if "<p14:media" in pic:
                    out.append(
                        Finding(
                            "pptx",
                            rel,
                            "pptx/embedded-video",
                            f"embedded video on slide {no}: check it has captions",
                            where=where,
                            severity="warning",
                        )
                    )
                continue
            blip = re.search(r'<a:blip\b[^>]*r:embed="(rId\d+)"', pic) or re.search(
                r'svgBlip [^>]*r:embed="(rId\d+)"', pic
            )
            if blip and rels.get(blip[1]) in deck.data and hashlib.sha1(deck.data[rels[blip[1]]]).hexdigest() in ignore:
                template_not_decorative += 1
                continue
            if not descr.strip():
                out.append(
                    Finding("pptx", rel, "pptx/picture-no-alt", f"picture on slide {no} has no alt text", where=where)
                )
            elif PLACEHOLDER_ALT.search(descr.strip()):
                out.append(
                    Finding(
                        "pptx",
                        rel,
                        "pptx/picture-placeholder-alt",
                        f"picture on slide {no} has placeholder alt text '{descr[:40]}'",
                        where=where,
                    )
                )

        # Tables.
        for gf in re.findall(r"<p:graphicFrame>.*?</p:graphicFrame>", x, re.S):
            if "<a:tbl>" in gf:
                tbl_pr = re.search(r"<a:tblPr\b[^>]*>", gf)
                if not tbl_pr or 'firstRow="1"' not in tbl_pr[0]:
                    gid = re.search(r'<p:cNvPr\b[^>]*\bid="(\d+)"', gf)[1]
                    out.append(
                        Finding(
                            "pptx",
                            rel,
                            "pptx/table-no-header",
                            f"table on slide {no} has no header row",
                            where=f"slide {sid} / table {gid}",
                        )
                    )

        # Text: size and contrast, wherever colours are known.
        layers = list(under)
        for el in re.findall(r"<p:sp>.*?</p:sp>|<p:pic>.*?</p:pic>", x, re.S):
            lay = layer_of(el, theme)
            if el.startswith("<p:pic"):
                if lay:
                    layers.append(lay)
                continue
            sp = el
            b = box(sp)
            own = lay[1] if lay else None
            bg = own or (background_under(b, layers, page_bg) if b else page_bg)
            if lay:
                layers.append(lay)  # shapes later in the slide sit on top of this one
            if re.search(r'<p:ph\b[^>]*type="(?:sldNum|dt|ftr)"', sp) or bg in (None, UNKNOWN):
                continue
            low = False
            for run in re.findall(r"<a:r>.*?</a:r>", sp, re.S):
                text = "".join(re.findall(r"<a:t>([^<]*)</a:t>", run)).strip()
                if not text:
                    continue
                rpr = re.search(r"<a:rPr\b[^>]*?(?:/>|>.*?</a:rPr>)", run, re.S)
                rpr = rpr[0] if rpr else ""
                sz = re.search(r'\bsz="(\d+)"', rpr)
                size = int(sz[1]) / 100 if sz else None
                if size is not None and size < 18:
                    small += 1
                fg_el = re.search(r"<a:solidFill>\s*(<a:\w+Clr\b.*?(?:/>|</a:\w+Clr>))", rpr, re.S)
                fg = theme.resolve(fg_el[1]) if fg_el else None
                if fg and fg != UNKNOWN:
                    bold = 'b="1"' in rpr
                    large = size is not None and (size >= 24 or (bold and size >= 18.66))
                    if contrast(fg, bg) < (3.0 if large else 4.5):
                        low = True
            if low:
                sid_sp = re.search(r'<p:cNvPr\b[^>]*\bid="(\d+)"', sp)[1]
                out.append(
                    Finding(
                        "pptx",
                        rel,
                        "pptx/low-contrast",
                        f"low-contrast text on slide {no}",
                        where=f"slide {sid} / shape {sid_sp}",
                    )
                )

    if no_title:
        out.append(Finding("pptx", rel, "pptx/slide-no-title", "slides without a title placeholder", count=no_title))
    if template_not_decorative:
        out.append(
            Finding(
                "pptx",
                rel,
                "pptx/template-image-not-decorative",
                "template logos not marked decorative",
                count=template_not_decorative,
            )
        )
    if small:
        out.append(Finding("pptx", rel, "pptx/small-text", "text runs under 18 pt", severity="warning", count=small))
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
