#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0", "python-pptx==1.0.2", "coloraide==8.13", "lxml==6.1.2", "resvg-py==0.5.0"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Build the site's search index: every described image and every slide, searchable.

    uv run tools/a11y/search_index.py --root deploy_target

Writes <root>/search-index.json and web-viewable copies of the images under
<root>/figures/: a small WebP thumbnail of every image (SVGs rendered with resvg) and a
full-size version any browser can show (SVG and GIF as they are; other rasters as WebP,
at most FULL px, which also covers PPM/BMP). Names are content hashes, so unchanged
images are not rewritten.

Entries:
  {"kind": "image", "id", "alt", "title", "where", "link", "thumb", "full", "format", "group"}
      slide pictures with reviewed alt text (Lectures/Slides/figures.toml), images in the
      homeworks and labs (\\AltImg, \\Annotated, \\includegraphics inside \\AltStart..\\AltEnd),
      and the TikZ lecture figures (their `% alt:` description, SVG built by CI)
  {"kind": "slide", "title", "text", "where", "link"}
      every lecture slide's title and text, linking to the slide in the deck's text version
Diagrams drawn directly in a document (TikZ inside \\AltStart) are indexed without a picture.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

REPO = sdf.REPO
THUMB = 480  # longest edge of thumbnails (px)
FULL = 2400  # longest edge of the full-size raster version (px)
SVG_MAX = 1_500_000  # bytes; larger SVGs are published as a FULL-px raster
OFFICIAL_LAB = "https://coecsl.ece.illinois.edu/se423/SE423_Lab{n}.pdf"


def lecture_label(stem):
    m = re.match(r"L(\d+)(?:-(\d+))?", stem)
    return (f"Lectures {m[1]}–{m[2]}" if m[2] else f"Lecture {m[1]}") if m else stem


def doc_label(path):
    stem = path.stem
    if m := re.fullmatch(r"HW(\d+)", stem):
        return f"Homework {m[1]}"
    if m := re.fullmatch(r"LabVIEW(\d+)", stem):
        return f"LabVIEW {m[1]}"
    if m := re.fullmatch(r"Lab(\d+)", stem):
        return f"Lab {m[1]}"
    return stem.replace("_", " ").capitalize()


def doc_link(path):
    """Where a handout is read: the HTML version for documents built here, the
    official course page for the labs (published by the course website)."""
    if m := re.fullmatch(r"Lab(\d+)", path.stem):
        return OFFICIAL_LAB.format(n=m[1])
    rel = path.relative_to(REPO).with_suffix(".html").as_posix()
    return f"site/{rel}"


# ------------------------------------------------------------------ images
class Publisher:
    """Copies images into <root>/figures/ in a form browsers can show."""

    def __init__(self, root):
        self.root = root
        self.dir = root / "figures"
        self.dir.mkdir(parents=True, exist_ok=True)

    def publish(self, src):
        """(thumb url, full url, format) for a repo image, or None if unreadable."""
        from PIL import Image

        data = src.read_bytes()
        digest = hashlib.sha1(data).hexdigest()[:16]
        fmt = src.suffix[1:].lower()
        thumb = self.dir / f"{digest}.thumb.webp"
        if fmt == "svg":
            import resvg_py

            # Very large SVGs (dense matplotlib scatter plots) are published as a sharp
            # raster instead; the rest stay vector.
            heavy = len(data) > SVG_MAX
            full = self.dir / (f"{digest}.webp" if heavy else f"{digest}.svg")
            try:
                if not full.exists():
                    if heavy:
                        png = bytes(resvg_py.svg_to_bytes(svg_path=str(src), width=FULL))
                        Image.open(io.BytesIO(png)).save(full, "WEBP", quality=90)
                    else:
                        full.write_bytes(data)
                if not thumb.exists():
                    png = bytes(resvg_py.svg_to_bytes(svg_path=str(src), width=THUMB))
                    Image.open(io.BytesIO(png)).save(thumb, "WEBP", quality=80)
            except Exception:
                full = self.dir / f"{digest}.svg"  # unrenderable: the browser shows the SVG
                full.write_bytes(data)
                thumb = full
            return self.url(thumb), self.url(full), "svg"
        try:
            img = Image.open(src)
            img.load()
        except Exception:
            return None
        real = (img.format or fmt).lower()
        if real == "gif":
            full = self.dir / f"{digest}.gif"  # keep animation
            if not full.exists():
                full.write_bytes(data)
        else:
            full = self.dir / f"{digest}.webp"
            if not full.exists():
                big = self.rgb(img)
                big.thumbnail((FULL, FULL))
                big.save(full, "WEBP", quality=90)
        if not thumb.exists():
            small = self.rgb(img)
            small.thumbnail((THUMB, THUMB))
            small.save(thumb, "WEBP", quality=80)
        return self.url(thumb), self.url(full), real

    @staticmethod
    def rgb(img):
        img.seek(0)
        return img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")

    def url(self, path):
        return path.relative_to(self.root).as_posix()


def group_of(fmt):
    return {"jpeg": "jpg"}.get(fmt, fmt)


def lecture_images(pub):
    manifest = tomllib.loads((REPO / "Lectures/Slides/figures.toml").read_text())
    seen = {}
    for f in manifest.get("figure", []):
        if f.get("decorative") or not f.get("alt") or f.get("alt_status", "reviewed") != "reviewed":
            continue
        stem = Path(f["deck"]).stem
        key = (f["source"], stem, f["slide"])
        if key in seen:
            continue
        src = REPO / f["source"]
        if not src.exists() or not (published := pub.publish(src)):
            continue
        thumb, full, fmt = published
        seen[key] = {
            "kind": "image",
            "id": f"{stem}-{f['slide']}-{Path(f['source']).stem}",
            "alt": f["alt"],
            "title": f"{lecture_label(stem)}, slide {f['slide']}",
            "where": lecture_label(stem),
            "link": f"Lectures/Slides/{stem}.html#s{f['slide']}",
            "thumb": thumb,
            "full": full,
            "format": group_of(fmt),
            "group": "lecture",
        }
    return list(seen.values())


def tikz_images(root):
    out = []
    for tex in sorted((REPO / "Lectures/Figures").glob("*.tex")):
        m = re.search(r"^\s*%\s*alt:\s*(.+)$", tex.read_text(), re.M)
        svg = f"Lectures/Figures/{tex.stem}.svg"
        if not m or not (root / svg).exists():
            continue
        out.append(
            {
                "kind": "image",
                "id": f"tikz-{tex.stem}",
                "alt": m[1].strip(),
                "title": " ".join(w[:1].upper() + w[1:] for w in re.split(r"[_\-]+", tex.stem)),
                "where": "Lecture figure",
                "link": svg,
                "thumb": svg,
                "full": svg,
                "format": "svg",
                "group": "lecture",
            }
        )
    return out


def brace_arg(s, i):
    """(content, end) of the {...} group starting at s[i] (which must be '{')."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
    return s[i + 1 :], len(s)


def skip_ws(s, i):
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def plain(tex):
    """LaTeX alt text -> plain text."""
    t = re.sub(r"%\n\s*", "", tex)
    t = re.sub(r"(?<!\\)%.*", "", t)
    t = re.sub(r"\\(?:textit|textbf|emph|texttt|mbox|text)\{([^{}]*)\}", r"\1", t)
    t = t.replace("~", " ").replace("\\%", "%").replace("\\&", "&").replace("``", '"').replace("''", '"')
    t = re.sub(r"\\[a-zA-Z]+\s*", "", t)
    return " ".join(t.replace("{", "").replace("}", "").split())


def handout_images(pub):
    docs = [REPO / line.strip() for line in (REPO / "pdf-list.txt").read_text().splitlines() if line.strip()]
    docs += sorted((REPO / "Labs").glob("Lab[0-9]*.tex"))
    out = []
    for doc in docs:
        tex = re.sub(r"(?<!\\)%[^\n]*", lambda m: "%" if m[0].strip() == "%" else m[0], doc.read_text())
        found = []  # (image path or None, alt)
        for m in re.finditer(r"\\(AltImg|Annotated)\s*(\[[^\]]*\])?\s*\{", tex):
            path, end = brace_arg(tex, m.end() - 1)
            end = skip_ws(tex, end)
            alt, _ = brace_arg(tex, end) if end < len(tex) and tex[end] == "{" else ("", end)
            found.append((path.strip(), plain(alt)))
        for m in re.finditer(r"\\AltStart\s*\{", tex):
            alt, end = brace_arg(tex, m.end() - 1)
            block = tex[end : tex.find("\\AltEnd", end)]
            img = re.search(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", block)
            if "\\Annotated" in tex[max(0, m.start() - 200) : m.start()]:
                continue  # \Annotated's own \AltStart (already indexed above)
            found.append((img[1].strip() if img else None, plain(alt)))
        for k, (path, alt) in enumerate(found):
            if not alt:
                continue
            entry = {
                "kind": "image",
                "id": f"{doc.stem}-{k + 1}",
                "alt": alt,
                "title": f"{doc_label(doc)}, figure {k + 1}",
                "where": doc_label(doc),
                "link": doc_link(doc),
                "group": "lab" if doc.parent.name == "Labs" else "homework",
            }
            src = next(
                (
                    REPO / (path + ext)
                    for ext in ("", ".png", ".jpg", ".pdf")
                    if path and (REPO / (path + ext)).is_file()
                ),
                None,
            )
            if src is not None and src.suffix.lower() != ".pdf" and (published := pub.publish(src)):
                entry.update(thumb=published[0], full=published[1], format=group_of(published[2]))
            else:
                entry.update(format="diagram")  # drawn in the document (TikZ): no picture file
            out.append(entry)
    return out


def slide_entries():
    out = []
    for path in sdf.decks():
        prs = dr.open_deck(path)
        for no, slide in dr.slides(prs):
            title = dr.title_text(slide) or f"Slide {no}"
            texts = []
            for sp in dr.xp(slide._element, ".//p:sp"):
                if dr.ph_type(sp) in (*dr.TITLE_TYPES, "sldNum", "dt", "ftr"):
                    continue
                t = " ".join(dr.text_of(sp).split())
                if t and t not in ("GRAINGER ENGINEERING", "SYSTEMS ENGINEERING"):
                    texts.append(t)
            out.append(
                {
                    "kind": "slide",
                    "title": title,
                    "text": " ".join(texts)[:600],
                    "where": f"{lecture_label(path.stem)}, slide {no}",
                    "link": f"Lectures/Slides/{path.stem}.html#s{no}",
                }
            )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="published site directory (e.g. deploy_target)")
    args = ap.parse_args()
    root = Path(args.root)
    pub = Publisher(root)
    entries = lecture_images(pub) + tikz_images(root) + handout_images(pub) + slide_entries()
    (root / "search-index.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False, separators=(",", ":")))
    images = [e for e in entries if e["kind"] == "image"]
    by = {}
    for e in images:
        by[e["format"]] = by.get(e["format"], 0) + 1
    print(
        f"{len(images)} images {by}, {len(entries) - len(images)} slides -> {root / 'search-index.json'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
