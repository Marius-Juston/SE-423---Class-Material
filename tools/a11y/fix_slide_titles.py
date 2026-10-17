#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==1.28.2", "pillow==12.3.0"]
# ///
"""Give every slide a real title (a title placeholder), without changing how it looks.

    uv run tools/a11y/fix_slide_titles.py [--dry-run] [DECK.pptx ...]

The decks came from Google Slides, so each slide's title is a plain text box; screen
readers, PowerPoint's navigation and outline, PDF bookmarks and the accessibility
checker all need a title placeholder instead. For each slide that has none:

1. a text box inside the blue header band at the top of the slide becomes the title;
2. otherwise the slide's largest text (title, section and "Questions?" slides);
3. otherwise (picture-only slides, e.g. the closing branding slide) a title is added
   just above the slide, where it is not shown but is read by screen readers.

The text box only gains `<p:ph type="title"/>`; its explicit position, size and
formatting are kept. Every slide is rendered with LibreOffice before and after and
compared pixel by pixel: any slide that changed visibly is reverted and reported.
Decks are written with the byte-faithful zip writer. Needs `soffice` on the PATH.
"""

import argparse
import io
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import lint_pptx as L  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402
from findings import REPO  # noqa: E402

TEMPLATE = REPO / "Lectures/Slides/SE-Deck-Template.pptx"
DIFF_TOLERANCE = 0.002  # share of pixels allowed to differ (anti-aliasing noise)


def lecture_label(deck_name):
    m = re.match(r"L(\d+)(?:-(\d+))?", deck_name)
    if not m:
        return "this lecture"
    return f"Lectures {m[1]}–{m[2]}" if m[2] else f"Lecture {m[1]}"


def slide_size(deck):
    return tuple(map(int, re.search(r'<p:sldSz cx="(\d+)" cy="(\d+)"', deck.data["ppt/presentation.xml"].decode()).groups()))


def header_bands(xml, sw, sh, theme):
    out = []
    for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
        b = L.box(sp)
        sp_pr = re.search(r"<p:spPr\b.*?</p:spPr>", sp, re.S)
        colour = theme.fill(sp_pr[0]) if sp_pr else None
        if b and colour not in (None, L.UNKNOWN) and b[1] <= sh * 0.02 and b[2] >= sw * 0.9 and b[3] <= sh * 0.2:
            out.append(b)
    return out


def text_of(sp):
    return "".join(re.findall(r"<a:t>([^<]*)</a:t>", sp)).strip()


def choose_title(deck, part, theme, sw, sh):
    """Return the <p:sp> string to turn into the title, or None."""
    x = deck.data[part].decode()
    layout = next(t for t in deck.rels(part).values() if "slideLayout" in t)
    master = next(t for t in deck.rels(layout).values() if "slideMaster" in t)
    bands = (
        header_bands(x, sw, sh, theme)
        + header_bands(deck.data[layout].decode(), sw, sh, theme)
        + header_bands(deck.data[master].decode(), sw, sh, theme)
    )
    boxes = [
        (sp, L.box(sp))
        for sp in re.findall(r"<p:sp>.*?</p:sp>", x, re.S)
        if "<p:ph" not in sp and text_of(sp) and L.box(sp)
    ]
    if bands:
        top = bands[0][1] + bands[0][3]
        inside = [(sp, b) for sp, b in boxes if b[1] + b[3] / 2 <= top]
        if inside:
            fully = [(sp, b) for sp, b in inside if b[1] + b[3] <= top + sh * 0.01]
            return min(fully or inside, key=lambda c: c[1][1])[0]
        return None

    def biggest_font(sp):
        sizes = [int(s) for s in re.findall(r'<a:rPr\b[^>]*\bsz="(\d+)"', sp)]
        return max(sizes) if sizes else 0

    if boxes:
        return max(boxes, key=lambda c: (biggest_font(c[0]), -c[1][1]))[0]
    return None


def text_defaults(deck):
    """Per paragraph level (0-8): what an ordinary text box inherits from the
    presentation's default text style. A title placeholder would inherit the title
    style instead (90% line spacing, 44 pt, centred, autofit), so these are written
    into the converted shape explicitly."""
    pres = deck.data["ppt/presentation.xml"].decode()
    style = re.search(r"<p:defaultTextStyle>(.*?)</p:defaultTextStyle>", pres, re.S)
    out = {}
    for lvl in range(9):
        m = re.search(rf"<a:lvl{lvl + 1}pPr\b([^>]*)>(.*?)</a:lvl{lvl + 1}pPr>", style[1], re.S) if style else None
        attrs, body = (m[1], m[2]) if m else ("", "")
        d = {"algn": (re.search(r'algn="(\w+)"', attrs) or [None, "l"])[1]}
        for el in ("lnSpc", "spcBef", "spcAft"):
            e = re.search(rf"<a:{el}>.*?</a:{el}>", body, re.S)
            d[el] = e[0] if e else {"lnSpc": "<a:lnSpc><a:spcPct val=\"100000\"/></a:lnSpc>"}.get(el, f"<a:{el}><a:spcPts val=\"0\"/></a:{el}>")
        r = re.search(r"<a:defRPr\b([^>]*?)(?:/>|>(.*?)</a:defRPr>)", body, re.S)
        rattrs, rbody = (r[1], r[2] or "") if r else ("", "")
        d["sz"] = (re.search(r'\bsz="(\d+)"', rattrs) or [None, "1800"])[1]
        d["b"] = (re.search(r'\bb="(\d)"', rattrs) or [None, "0"])[1]
        d["i"] = (re.search(r'\bi="(\d)"', rattrs) or [None, "0"])[1]
        fill = re.search(r"<a:solidFill>.*?</a:solidFill>", rbody, re.S)
        d["fill"] = fill[0] if fill else '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
        out[lvl] = d
    return out


def pin_formatting(sp, defaults):
    """Write the text box's effective defaults explicitly, so becoming a title
    placeholder cannot change line spacing, size, alignment, anchoring or autofit."""

    def body_pr(m):
        tag = m[0]
        if "anchor=" not in tag:
            tag = tag.replace("<a:bodyPr", '<a:bodyPr anchor="t"', 1)
        if tag.endswith("/>"):
            tag = tag[:-2] + "><a:noAutofit/></a:bodyPr>"
        return tag

    sp = re.sub(r"<a:bodyPr\b[^>]*/>", body_pr, sp, count=1)
    if not re.search(r"<a:bodyPr\b[^>]*>(?:(?!</a:bodyPr>).)*<a:(?:noAutofit|normAutofit|spAutoFit)\b", sp, re.S):
        sp = re.sub(r"(<a:bodyPr\b[^>]*[^/]>)", r"\1<a:noAutofit/>", sp, count=1)
    sp = re.sub(r"<a:bodyPr(?![^>]*anchor=)", '<a:bodyPr anchor="t"', sp, count=1)

    def paragraph(pm):
        para = pm[0]
        ppr = re.search(r"<a:pPr\b[^>]*?(?:/>|>.*?</a:pPr>)", para, re.S)
        lvl = int((re.search(r'\blvl="(\d)"', ppr[0]) or [None, "0"])[1]) if ppr else 0
        d = defaults.get(lvl, defaults[0])
        if ppr:
            tag = ppr[0]
            if "algn=" not in tag:
                tag = tag.replace("<a:pPr", f'<a:pPr algn="{d["algn"]}"', 1)
            if tag.endswith("/>"):
                tag = tag[:-2] + "></a:pPr>"
            head, rest = tag.split(">", 1)
            inner = rest[: -len("</a:pPr>")]
            # lnSpc, spcBef and spcAft come first in a:pPr, in that order: keep the
            # ones present, fill in the missing ones from the defaults.
            spacing = [re.search(rf"<a:{el}>.*?</a:{el}>", inner, re.S) for el in ("lnSpc", "spcBef", "spcAft")]
            for m in spacing:
                if m:
                    inner = inner.replace(m[0], "", 1)
            merged = "".join(m[0] if m else d[el] for el, m in zip(("lnSpc", "spcBef", "spcAft"), spacing))
            new_ppr = head + ">" + merged + inner + "</a:pPr>"
            para = para.replace(ppr[0], new_ppr, 1)
        else:
            para = para.replace(
                "<a:p>", f'<a:p><a:pPr algn="{d["algn"]}">{d["lnSpc"]}{d["spcBef"]}{d["spcAft"]}</a:pPr>', 1
            )

        def run_pr(rm):
            tag = rm[0]
            name = "endParaRPr" if tag.startswith("<a:endParaRPr") else "rPr"
            for attr in ("sz", "b", "i"):
                if not re.search(rf'\b{attr}="', tag.split(">", 1)[0]):
                    tag = tag.replace(f"<a:{name}", f'<a:{name} {attr}="{d[attr]}"', 1)
            if "<a:solidFill>" not in tag and "<a:gradFill" not in tag and "<a:noFill" not in tag:
                if tag.endswith("/>"):
                    tag = tag[:-2] + f">{d['fill']}</a:{name}>"
                else:
                    head, rest = tag.split(">", 1)
                    ln = re.match(r"\s*<a:ln\b.*?(?:/>|</a:ln>)", rest, re.S)  # a:ln precedes the fill
                    tag = head + ">" + (ln[0] + d["fill"] + rest[len(ln[0]) :] if ln else d["fill"] + rest)
            return tag

        para = re.sub(r"<a:r>(?!<a:rPr)", '<a:r><a:rPr lang="en-US"/>', para)
        para = re.sub(r"<a:(?:rPr|endParaRPr)\b[^>]*?(?:/>|>.*?</a:(?:rPr|endParaRPr)>)", run_pr, para, flags=re.S)
        return para

    return re.sub(r"<a:p>.*?</a:p>", paragraph, sp, flags=re.S)


def make_title(sp, defaults):
    """Turn a text box into a title placeholder, keeping its look."""
    sp = pin_formatting(sp, defaults)
    sp2 = re.sub(r'<p:cNvSpPr txBox="1"/>', "<p:cNvSpPr/>", sp, count=1)
    sp2 = re.sub(r'(<p:cNvSpPr) txBox="1"', r"\1", sp2, count=1)
    if "<p:nvPr/>" in sp2:
        return sp2.replace("<p:nvPr/>", '<p:nvPr><p:ph type="title"/></p:nvPr>', 1)
    return re.sub(r"<p:nvPr>", '<p:nvPr><p:ph type="title"/>', sp2, count=1)


def hidden_title(xml, text, sw):
    ids = [int(i) for i in re.findall(r'<p:cNvPr\b[^>]*\bid="(\d+)"', xml)]
    sid = max(ids, default=1) + 1
    shape = (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Title {sid}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="-914400"/>'
        f'<a:ext cx="{sw}" cy="685800"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p>'
        f'<a:r><a:rPr lang="en-US" dirty="0"/><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    )
    # First in the shape tree (after the group properties) so it is read first.
    return re.sub(r"(</p:grpSpPr>)", r"\1" + shape, xml, count=1)


def convert(path):
    """Return (new deck bytes, {slide no: action}) with titles added; the file is not written."""
    deck = sdf.Deck(path)
    theme = L.Theme(deck)
    sw, sh = slide_size(deck)
    defaults = text_defaults(deck)
    actions = {}
    for no, _sid, part in deck.slides():
        x = deck.data[part].decode()
        if L.title_text(x):
            continue
        sp = choose_title(deck, part, theme, sw, sh)
        if sp:
            x = x.replace(sp, make_title(sp, defaults), 1)
            actions[no] = f"title: {text_of(sp)[:50]!r}"
        elif not re.search(r'<p:ph\b[^>]*type="(?:title|ctrTitle)"', x):
            label = f"End of {lecture_label(path.name)}" if no == len(deck.slides()) else f"{lecture_label(path.name)}, slide {no}"
            x = hidden_title(x, label, sw)
            actions[no] = f"hidden title: {label!r}"
        deck.data[part] = x.encode()
    content = sdf.write_faithful_zip(deck.raw, deck.infos, deck.data)
    return content, actions


def render(pptx_bytes, workdir, name):
    import pymupdf

    src = Path(workdir, name)
    src.write_bytes(pptx_bytes)
    profile = Path(workdir, "lo-profile").as_uri()
    subprocess.run(
        ["soffice", f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", str(workdir), str(src)],
        check=True,
        capture_output=True,
        timeout=900,
    )
    return pymupdf.open(src.with_suffix(".pdf"))


def changed_slides(before, after):
    from PIL import Image, ImageChops

    out = []
    for i in range(min(len(before), len(after))):
        a, b = (
            Image.open(io.BytesIO(doc[i].get_pixmap(dpi=40).tobytes("png"))).convert("L") for doc in (before, after)
        )
        diff = ImageChops.difference(a, b).point(lambda v: 255 if v > 40 else 0)
        share = sum(diff.histogram()[255:]) / (a.width * a.height)
        if share > DIFF_TOLERANCE:
            out.append(i + 1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*", help="decks (default: all lecture decks and the template)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()
    if not shutil.which("soffice"):
        sys.exit("soffice (LibreOffice) is needed to verify that slides still look the same")
    paths = [Path(p).resolve() for p in args.decks] or [*sdf.decks(), TEMPLATE]
    total = reverted_total = 0
    for path in paths:
        original = path.read_bytes()
        content, actions = convert(path)
        if not actions:
            print(f"{path.name}: every slide already has a title")
            continue
        with tempfile.TemporaryDirectory() as d:
            before = render(original, d, "before.pptx")
            after = render(content, d, "after.pptx")
            changed = [n for n in changed_slides(before, after) if n in actions]
        if changed:
            # Revert just those slides: rebuild from the original with the other slides converted.
            deck = sdf.Deck(path)
            new = sdf.Deck(path, content)
            for no, _sid, part in deck.slides():
                if no in changed:
                    new.data[part] = deck.data[part]
            content = sdf.write_faithful_zip(original, new.infos, new.data)
        done = {n: a for n, a in actions.items() if n not in changed}
        total += len(done)
        reverted_total += len(changed)
        print(f"{path.name}: {len(done)} slide(s) titled" + (f", {len(changed)} reverted (looked different): {changed}" if changed else ""))
        if not args.dry_run:
            path.write_bytes(content)
    print(f"done: {total} slides titled, {reverted_total} left for manual review")


if __name__ == "__main__":
    main()
