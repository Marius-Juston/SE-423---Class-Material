#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["python-pptx==1.0.2", "coloraide==8.13", "pypandoc-binary==1.17", "pillow==12.3.0"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Accessible HTML version of each lecture deck.

    uv run tools/a11y/pptx_to_html.py --out build/Lectures/Slides [DECK.pptx ...]

Writes <out>/<deck>.html (+ <deck>_files/ with the pictures): one section per slide
with the slide title as a heading, text in reading order (bullets as nested lists),
pictures with their alt text (decorative ones left out), tables with header cells,
equations as MathML (pandoc's OMML reader), videos as links, and the lecture notes.
A slide PDF is a picture of the slides; this page is the version screen readers,
reflow and zoom work best with.
"""

import argparse
import hashlib
import html
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

ESC = html.escape
WEB_IMAGES = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
# Content signatures: a part's name can lie (PowerPoint keeps e.g. BMPs as .png).
SIGNATURES = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp"}


def real_ext(data, ext):
    """Format by content for raster images; the name's extension for SVG."""
    if ext == "svg":
        return ext
    return next((e for sig, e in SIGNATURES.items() if data.startswith(sig)), "bmp")


YOUTUBE_EMBED = re.compile(r"youtube(?:-nocookie)?\.com/embed/([\w-]{11}).*")


def choice(el):
    """For mc:AlternateContent, the mc:Choice content (equations, newer shapes); else el."""
    if dr.local(el) == "AlternateContent":
        found = dr.xp(el, "./mc:Choice")
        return list(found[0]) if found else []
    return [el]


def flat_text(el):
    return " ".join(dr.text_of(el).split())


class SlidePage:
    """HTML for the content of one slide."""

    def __init__(self, deck, slide, maths):
        self.deck, self.slide, self.part = deck, slide, slide.part
        self.maths = maths  # XPath of an equation in this slide -> MathML

    # ---------------------------------------------------------------- text
    def runs(self, p):
        out = []
        for child in p:
            for el in choice(child):
                kind = dr.local(el)
                if kind == "r":
                    text = ESC(dr.text_of(el))
                    rpr = el.find(dr.q("a:rPr"))
                    if rpr is not None and text.strip():
                        if rpr.get("b") == "1":
                            text = f"<strong>{text}</strong>"
                        if rpr.get("i") == "1":
                            text = f"<em>{text}</em>"
                        link = dr.xp(rpr, "./a:hlinkClick/@r:id")
                        target, external = dr.rel_target(self.part, link[0]) if link else (None, False)
                        if external and target:
                            text = f"<a href='{ESC(target, quote=True)}'>{text}</a>"
                    out.append(text)
                elif kind == "br":
                    out.append("<br>")
                elif kind == "fld":
                    out.append(ESC(dr.text_of(el)))
                elif kind == "m":
                    for m in dr.xp(el, "./m:oMathPara | ./m:oMath"):
                        out.append(self.maths.get(m.getroottree().getpath(m), ""))
        return "".join(out).strip()

    def text_body(self, body, bulleted):
        """Paragraphs as <p>, bullets as nested <ul>/<ol> (by level)."""
        out, stack = [], []  # stack of open list tags
        for p in dr.xp(body, "./a:p"):
            content = self.runs(p)
            ppr = p.find(dr.q("a:pPr"))
            lvl = int(ppr.get("lvl", "0")) if ppr is not None else 0
            if ppr is not None and dr.xp(ppr, "./a:buNone"):
                is_item = False
            elif ppr is not None and dr.xp(ppr, "./a:buChar | ./a:buAutoNum"):
                is_item = True
            else:
                is_item = bulleted
            numbered = ppr is not None and bool(dr.xp(ppr, "./a:buAutoNum"))
            if not is_item:
                while stack:
                    out.append(f"</li></{stack.pop()}>")
                if content:
                    out.append(f"<p>{content}</p>")
                continue
            if not content:
                continue
            # Close deeper lists (and their parent items), open new ones inside the
            # current item, so a nested list is always a child of an <li>.
            while len(stack) > lvl + 1:
                out.append(f"</li></{stack.pop()}>")
            if len(stack) == lvl + 1 and out and out[-1] != f"<{stack[-1]}>":
                out.append("</li>")
            while len(stack) < lvl + 1:
                tag = "ol" if numbered else "ul"
                if stack and out[-1] == "</li>":
                    out.pop()  # reopen the previous item to hold the nested list
                elif stack:
                    out.append("<li>")
                stack.append(tag)
                out.append(f"<{tag}>")
            out.append(f"<li>{content}")
        while stack:
            out.append(f"</li></{stack.pop()}>")
        return "\n".join(out)

    # ---------------------------------------------------------------- shapes
    def picture(self, pic):
        if dr.is_decorative(pic):
            return ""
        descr = (dr.cnvpr(pic).get("descr") or "").strip()
        if dr.is_media(pic):
            label = ESC(descr or "Video")
            link = dr.xp(pic, "./p:nvPicPr/p:nvPr/a:videoFile/@r:link")
            target, external = dr.rel_target(self.part, link[0]) if link else (None, False)
            if external and target:
                watch = YOUTUBE_EMBED.sub(r"youtube.com/watch?v=\1", target)
                return f"<p class='video'><a href='{ESC(watch, quote=True)}'>{label}</a></p>"
            return f"<p class='video'>{label} (embedded video, in the slide deck)</p>"
        rid = dr.picture_rid(pic, prefer_svg=True)
        target, external = dr.rel_target(self.part, rid) if rid else (None, True)
        if external or target is None:
            return ""
        src = self.deck.media_file(target)
        alt = descr or "Picture without a description"
        return f"<figure><img src='{src}' alt='{ESC(alt, quote=True)}' loading='lazy'></figure>"

    def table(self, tbl):
        header = bool(dr.xp(tbl, "./a:tblPr[@firstRow='1']"))
        rows = []
        for i, tr in enumerate(dr.xp(tbl, "./a:tr")):
            cells = []
            for tc in dr.xp(tr, "./a:tc"):
                if tc.get("hMerge") == "1" or tc.get("vMerge") == "1":
                    continue
                span = f" colspan='{tc.get('gridSpan')}'" if tc.get("gridSpan") else ""
                text = "<br>".join(self.runs(p) for p in dr.xp(tc, "./a:txBody/a:p"))
                tag = "th" if header and i == 0 else "td"
                scope = " scope='col'" if tag == "th" else ""
                cells.append(f"<{tag}{span}{scope}>{text}</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        if header and rows:
            return f"<table><thead>{rows[0]}</thead><tbody>{''.join(rows[1:])}</tbody></table>"
        return f"<table><tbody>{''.join(rows)}</tbody></table>"

    def shapes(self, tree, skip):
        out = []
        for child in tree:
            for el in choice(child):
                kind = dr.local(el)
                if kind == "sp":
                    if el is skip or flat_text(el) in self.deck.boilerplate:
                        continue
                    ph = dr.ph_type(el)
                    if ph in dr.TITLE_TYPES or ph in ("sldNum", "dt", "ftr"):
                        continue
                    body = el.find(dr.q("p:txBody"))
                    if body is not None:
                        out.append(self.text_body(body, bulleted=ph in ("body", "obj", "subTitle")))
                elif kind == "pic":
                    out.append(self.picture(el))
                elif kind == "graphicFrame":
                    for tbl in dr.xp(el, ".//a:tbl"):
                        out.append(self.table(tbl))
                elif kind == "grpSp":
                    out.append(self.shapes(el, skip))
        return "\n".join(x for x in out if x)


class DeckPage:
    def __init__(self, path, out_dir):
        self.path, self.out_dir = path, out_dir
        self.prs = dr.open_deck(path)
        self.files = f"{path.stem}_files"
        self.slides = dr.slides(self.prs)
        # Text repeated on many slides (template footers like "SYSTEMS ENGINEERING")
        # is decoration, not content.
        seen = {}
        for _no, slide in self.slides:
            for t in {flat_text(sp) for sp in dr.xp(slide._element, ".//p:sp")} - {""}:
                seen[t] = seen.get(t, 0) + 1
        self.boilerplate = frozenset(t for t, n in seen.items() if n >= max(3, len(self.slides) // 3) and len(t) < 60)

    def media_file(self, part):
        """Copy a picture part next to the page (content-addressed name); its URL.
        Formats browsers cannot show (PPM, BMP, TIFF) are converted to PNG."""
        data = part.blob
        ext = real_ext(data, part.partname.ext.lower())
        name = f"{hashlib.sha1(data).hexdigest()[:12]}.{ext if ext in WEB_IMAGES else 'png'}"
        path = self.out_dir / self.files / name
        if not path.exists():
            if ext not in WEB_IMAGES:
                from PIL import Image

                out = io.BytesIO()
                Image.open(io.BytesIO(data)).save(out, "PNG", optimize=True)
                data = out.getvalue()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return f"{self.files}/{name}"

    def equations(self):
        """MathML for every equation of the deck, keyed by slide number and XPath."""
        found = [(no, m) for no, slide in self.slides for m in dr.math_elements(slide._element)]
        mathml = dr.omml_to_mathml([m for _, m in found])
        out = {}
        for (no, m), html_ in zip(found, mathml, strict=True):
            out.setdefault(no, {})[m.getroottree().getpath(m)] = html_
        return out

    def render(self):
        maths = self.equations()
        sections, toc = [], []
        for no, slide in self.slides:
            title_sp = dr.title_shape(slide)
            title = " ".join(dr.text_of(title_sp).split()) if title_sp is not None else ""
            tree = dr.xp(slide._element, "./p:cSld/p:spTree")[0]
            body = SlidePage(self, slide, maths.get(no, {})).shapes(tree, title_sp)
            notes = dr.notes_text(slide)
            notes_html = (
                "<details><summary>Lecture notes</summary>" + "".join(f"<p>{ESC(n)}</p>" for n in notes) + "</details>"
                if notes
                else ""
            )
            heading = ESC(title or f"Slide {no}")
            toc.append(f"<li><a href='#s{no}'>{heading}</a></li>")
            sections.append(
                f"<section id='s{no}' aria-labelledby='h{no}'>\n"
                f"<h2 id='h{no}'><span class='num'>{no}.</span> {heading}</h2>\n{body}\n{notes_html}\n</section>"
            )
        stem = ESC(self.path.stem)
        first = re.sub(r"<[^>]+>", "", toc[0]) if toc else stem
        doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{stem}: {first} (accessible slides)</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:ital,wght@0,200..800;1,200..800&display=swap">
<style>{STYLE}</style></head>
<body><a class="skip" href="#main">Skip to the slides</a>
<header><h1>{stem}: {first}</h1>
<p>Text version of the lecture slides, one section per slide.
<a href="{stem}.pdf">PDF</a> · <a href="{ESC(self.path.name)}">PowerPoint</a></p></header>
<nav aria-label="Slides"><details><summary>All slides ({len(toc)})</summary><ol>{"".join(toc)}</ol></details></nav>
<main id="main">
{chr(10).join(sections)}
</main></body></html>
"""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{self.path.stem}.html").write_text(doc)
        return len(sections)


STYLE = """
:root { --bg:#fff; --fg:#1a1a1a; --muted:#555; --accent:#13294B; --link:#0b3d91; --rule:#d9d9d9; }
@media (prefers-color-scheme: dark) { :root { --bg:#121212; --fg:#eee; --muted:#bbb; --accent:#9db7e8; --link:#9db7e8; --rule:#333; } }
body { margin:0 auto; max-width:60rem; padding:1rem; background:var(--bg); color:var(--fg);
       font: 1.125rem/1.6 'Atkinson Hyperlegible Next', system-ui, sans-serif; }
a { color:var(--link); } :focus-visible { outline:3px solid #FF5F05; outline-offset:2px; }
.skip { position:absolute; left:-999px; } .skip:focus { left:1rem; top:1rem; background:var(--bg); padding:.5rem; }
h1 { color:var(--accent); } h2 { color:var(--accent); border-top:1px solid var(--rule); padding-top:1rem; }
.num { color:var(--muted); font-size:.9em; font-weight:normal; }
figure { margin:1rem 0; } img { max-width:100%; height:auto; background:#fff; }
table { border-collapse:collapse; margin:1rem 0; } th, td { border:1px solid var(--rule); padding:.3rem .6rem; text-align:left; }
details { margin:.5rem 0 1rem; } summary { cursor:pointer; color:var(--muted); }
math[display=block] { margin:.5rem 0; max-width:100%; }
nav ol { columns: 2 18rem; }
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--out", required=True, help="output directory (e.g. build/Lectures/Slides)")
    args = ap.parse_args()
    out = Path(args.out)
    paths = [Path(p).resolve() for p in args.decks if Path(p).name.startswith("L")] if args.decks else sdf.decks()
    for path in paths:
        n = DeckPage(path, out).render()
        print(f"{path.name}: {n} slides -> {out / (path.stem + '.html')}")


if __name__ == "__main__":
    main()
