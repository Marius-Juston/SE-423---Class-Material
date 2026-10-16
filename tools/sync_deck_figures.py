#!/usr/bin/env python3
"""Keep the pictures in the lecture decks in sync with their source files.

Every picture on a slide in Lectures/Slides/L*.pptx is listed in
Lectures/Slides/figures.toml together with its source file. The source file is
the copy you edit; the deck keeps an embedded copy so it works offline and in
any viewer (PowerPoint, Keynote, Google Slides, LibreOffice).

    python3 tools/sync_deck_figures.py extract         # list new pictures, writing their files
    python3 tools/sync_deck_figures.py sync            # copy changed sources into the decks
    python3 tools/sync_deck_figures.py check           # exit 1 if any deck is out of date
    python3 tools/sync_deck_figures.py decks FILE...   # decks that use any FILE (used by CI)

Pictures are identified by the slide's id and the picture's creationId, which
PowerPoint keeps across saves (unlike the ppt/media/imageN names, which it
renumbers). Re-rendering the PNG fallback that PowerPoint stores next to an
SVG needs `mutool` (mupdf-tools); without it the old fallback is kept.
Only the standard library is used.
"""

import argparse
import hashlib
import json
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SLIDES = REPO / "Lectures" / "Slides"
FIGURES = REPO / "Lectures" / "Figures"
MANIFEST = SLIDES / "figures.toml"
FOLDER = {"svg": "svg", "png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif", "ppm": "ppm"}
SAME_FORMAT = {"jpeg": "jpg"}
ASPECT_TOLERANCE = 0.003


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def sha1(data):
    return hashlib.sha1(data).hexdigest()


# ------------------------------------------------------------------ image sizes
def image_size(data, ext):
    """(width, height) of an image, in its own units; None if unknown."""
    ext = SAME_FORMAT.get(ext, ext)
    if ext == "png" and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if ext == "gif" and data[:3] == b"GIF":
        return struct.unpack("<HH", data[6:10])
    if ext == "jpg":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2 : i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return w, h
            i += 2 + length
        return None
    if ext == "svg":
        root = re.search(rb"<svg\b[^>]*>", data)
        if not root:
            return None
        vb = re.search(rb'viewBox="\s*[-\d.e]+[\s,]+[-\d.e]+[\s,]+([\d.e]+)[\s,]+([\d.e]+)', root[0])
        if vb:
            return float(vb[1]), float(vb[2])
        wh = [re.search(rb"\s" + k + rb'="([\d.]+)', root[0]) for k in (b"width", b"height")]
        return (float(wh[0][1]), float(wh[1][1])) if all(wh) else None
    if ext == "ppm":
        tokens = re.sub(rb"#[^\n]*", b"", data[:200]).split()
        return int(tokens[1]), int(tokens[2])
    return None


# ------------------------------------------------------------------ decks
class Picture:
    def __init__(self, deck, slide_part, slide_no, slide_id, xml_span, pic):
        self.deck, self.slide_part, self.slide_no, self.slide_id = deck, slide_part, slide_no, slide_id
        self.span = xml_span
        cid = re.search(r'a16:creationId [^>]*id="(\{[^"]+\})"', pic)
        shape = re.search(r'<p:cNvPr [^>]*id="(\d+)"', pic)
        self.key = f"{slide_id}/{cid[1] if cid else 'shape-' + shape[1]}"
        svg = re.search(r'<asvg:svgBlip [^>]*r:embed="(rId\d+)"', pic)
        blip = re.search(r'<a:blip\b[^>]*r:embed="(rId\d+)"', pic)
        self.media_rid = svg[1] if svg else (blip[1] if blip else None)
        self.fallback_rid = blip[1] if (svg and blip) else None


class Deck:
    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.infos = z.infolist()
            self.data = {i.filename: z.read(i.filename) for i in self.infos}
        self.changed = False

    def rels_part(self, part):
        d, f = posixpath.split(part)
        return f"{d}/_rels/{f}.rels"

    def rels(self, part):
        """{rId: target part path} for a part's relationships (internal ones only)."""
        out = {}
        for r in re.findall(r"<Relationship [^>]*>", self.data[self.rels_part(part)].decode()):
            if 'TargetMode="External"' in r:
                continue
            rid, target = re.search(r'Id="([^"]+)"', r)[1], re.search(r'Target="([^"]+)"', r)[1]
            out[rid] = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        return out

    def slides(self):
        """[(position, slide id, slide part)] in presentation order."""
        pres = self.data["ppt/presentation.xml"].decode()
        rels = self.rels("ppt/presentation.xml")
        return [
            (i + 1, sid, rels[rid])
            for i, (sid, rid) in enumerate(re.findall(r'<p:sldId [^>]*id="(\d+)"[^>]*r:id="(rId\d+)"', pres))
        ]

    def pictures(self):
        for no, sid, part in self.slides():
            x = self.data[part].decode()
            for m in re.finditer(r"<p:pic>.*?</p:pic>", x, re.S):
                yield Picture(self, part, no, sid, m.span(), m[0])

    def find(self, key):
        return [p for p in self.pictures() if p.key == key]

    def media(self, pic, rid=None):
        part = self.rels(pic.slide_part)[rid or pic.media_rid]
        return part, self.data[part]

    def references(self, media_part):
        """How many picture references (in any slide) point at a media part."""
        n = 0
        for _, _, part in self.slides():
            for rid, target in self.rels(part).items():
                if target == media_part:
                    n += len(re.findall(r'r:embed="' + rid + '"', self.data[part].decode()))
        return n

    def new_media_part(self, ext):
        used = {int(m[1]) for n in self.data if (m := re.match(r"ppt/media/image(\d+)\.", n))}
        return f"ppt/media/image{max(used, default=0) + 1}.{ext}"

    def repoint(self, pic, rid, new_part):
        """Give this picture its own copy of a media part (copy-on-write for shared media)."""
        rels_part = self.rels_part(pic.slide_part)
        rels = self.data[rels_part].decode()
        ids = {int(i) for i in re.findall(r'Id="rId(\d+)"', rels)}
        new_rid = f"rId{max(ids) + 1}"
        rel_type = re.search(r'<Relationship [^>]*Id="' + rid + r'"[^>]*>', rels)
        rel_type = re.search(r'Type="([^"]+)"', rel_type[0])[1]
        target = posixpath.relpath(new_part, posixpath.dirname(pic.slide_part))
        rels = rels.replace(
            "</Relationships>", f'<Relationship Id="{new_rid}" Type="{rel_type}" Target="{target}"/></Relationships>'
        )
        self.data[rels_part] = rels.encode()
        x = self.data[pic.slide_part].decode()
        a, b = pic.span
        x = x[:a] + x[a:b].replace(f'r:embed="{rid}"', f'r:embed="{new_rid}"') + x[b:]
        self.data[pic.slide_part] = x.encode()
        if f'"{rid}"' not in x:  # nothing else on the slide used the old relationship
            rels = re.sub(r'<Relationship [^>]*Id="' + rid + r'"[^>]*/>', "", rels)
            self.data[rels_part] = rels.encode()
        self.infos.append(zipfile.ZipInfo(new_part, date_time=self.infos[0].date_time))
        self.infos[-1].compress_type = zipfile.ZIP_DEFLATED
        return new_rid

    def resize_frame(self, pic, ratio):
        """Scale the picture frame's width by `ratio`, keeping it centred. Returns a note."""
        x = self.data[pic.slide_part].decode()
        a, b = pic.span
        block = x[a:b]
        if re.search(r"<a:srcRect [^/]", block):
            return "cropped picture: frame left as is, check the slide"
        ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"/>', block)
        off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>', block)
        if not ext or not off:
            return "no frame size found: check the slide"
        cx = int(ext[1])
        ncx = round(cx * ratio)
        block = block.replace(ext[0], f'<a:ext cx="{ncx}" cy="{ext[2]}"/>', 1)
        block = block.replace(off[0], f'<a:off x="{int(off[1]) - (ncx - cx) // 2}" y="{off[2]}"/>', 1)
        self.data[pic.slide_part] = (x[:a] + block + x[b:]).encode()
        return f"frame width x{ratio:.3f}"

    def save(self):
        tmp = self.path.with_suffix(".pptx.tmp")
        with zipfile.ZipFile(tmp, "w") as z:
            for info in self.infos:
                z.writestr(info, self.data[info.filename], compress_type=info.compress_type)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise SystemExit(f"{self.path.name}: wrote a corrupt file, original kept")
        tmp.replace(self.path)


def render_png(svg_bytes, width):
    mutool = shutil.which("mutool")
    if not mutool:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d, "in.svg"), Path(d, "out.png")
        src.write_bytes(svg_bytes)
        subprocess.run(
            [mutool, "draw", "-q", "-c", "rgba", "-w", str(width), "-o", str(out), str(src)],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        return out.read_bytes()


# ------------------------------------------------------------------ manifest
HEADER = """\
# Pictures in the lecture decks and the source file each one is copied from.
# Generated by `python3 tools/sync_deck_figures.py extract`; maintained by hand.
#
# Edit the source file, never the picture inside PowerPoint, then run
# `python3 tools/sync_deck_figures.py sync` (CI does this before exporting PDFs).
# To point a picture at another file, change its `source`.
#   picture: "<slide id>/<creationId>" (both kept by PowerPoint across saves)
#   slide:   position in the deck when the entry was made (for humans only)
"""


def load_manifest():
    if not MANIFEST.exists():
        return {"ignore": [], "figure": []}
    m = tomllib.loads(MANIFEST.read_text())
    m.setdefault("ignore", [])
    m.setdefault("figure", [])
    return m


def save_manifest(m):
    q = json.dumps
    out = [HEADER, "# Images placed on many slides by the template (UIUC logos); never synced.", "ignore = ["]
    out += [f"  {q(h)}," for h in m["ignore"]] + ["]", ""]
    figs = sorted(m["figure"], key=lambda f: (natural(f["deck"]), f["slide"], f["picture"]))
    for f in figs:
        out += [
            "[[figure]]",
            f"deck = {q(f['deck'])}",
            f"slide = {f['slide']}",
            f"picture = {q(f['picture'])}",
            f"source = {q(f['source'])}",
            "",
        ]
    MANIFEST.write_text("\n".join(out))


def decks():
    return sorted(SLIDES.glob("L*.pptx"), key=lambda p: natural(p.name))


# ------------------------------------------------------------------ commands
def cmd_extract(args):
    m = load_manifest()
    known = {(f["deck"], f["picture"]) for f in m["figure"]}
    ignore = set(m["ignore"])
    have = {}  # content hash -> existing repo file (reuse instead of duplicating)
    for p in sorted(FIGURES.rglob("*")):
        if p.is_file() and p.suffix[1:].lower() in FOLDER:
            have.setdefault(sha1(p.read_bytes()), p.relative_to(REPO).as_posix())

    found = []
    for path in decks():
        deck = Deck(path)
        for pic in deck.pictures():
            if pic.media_rid:
                part, data = deck.media(pic)
                found.append((path.name, pic, part, data, sha1(data)))
    uses = {}
    for _, _, _, _, h in found:
        uses[h] = uses.get(h, 0) + 1
    for h, n in uses.items():
        if n > args.ignore_repeated and h not in ignore:
            ignore.add(h)
            m["ignore"].append(h)

    added = written = 0
    per_slide = {}
    for name, pic, part, data, h in found:
        if h in ignore or (name, pic.key) in known:
            continue
        if h not in have:
            ext = part.rsplit(".", 1)[-1].lower()
            k = per_slide[(name, pic.slide_no)] = per_slide.get((name, pic.slide_no), 0) + 1
            rel = f"Lectures/Figures/{FOLDER.get(ext, ext)}/{Path(name).stem}/slide{pic.slide_no:03d}_{k}.{ext}"
            (REPO / rel).parent.mkdir(parents=True, exist_ok=True)
            (REPO / rel).write_bytes(data)
            have[h] = rel
            written += 1
        m["figure"].append({"deck": name, "slide": pic.slide_no, "picture": pic.key, "source": have[h]})
        known.add((name, pic.key))
        added += 1
    save_manifest(m)
    print(
        f"{added} pictures added to {MANIFEST.relative_to(REPO)}, {written} files written, "
        f"{len(m['ignore'])} template images ignored"
    )


def sync(write):
    m = load_manifest()
    by_deck = {}
    for f in m["figure"]:
        by_deck.setdefault(f["deck"], []).append(f)
    stale = errors = 0
    for name in sorted(by_deck, key=natural):
        path = SLIDES / name
        if not path.exists():
            print(f"ERROR {name}: deck not found")
            errors += 1
            continue
        deck = Deck(path)
        source_of = {f["picture"]: f["source"] for f in by_deck[name]}
        for f in by_deck[name]:
            src = REPO / f["source"]
            pics = deck.find(f["picture"])
            if not src.exists():
                print(f"ERROR {name} slide {f['slide']}: source {f['source']} missing")
                errors += 1
                continue
            if not pics:
                print(
                    f"ERROR {name}: picture {f['picture']} (was slide {f['slide']}) not found; "
                    f"it was deleted or re-inserted, so update or remove its entry"
                )
                errors += 1
                continue
            new = src.read_bytes()
            for pic in pics:
                part, old = deck.media(pic)
                if old == new:
                    continue
                stale += 1
                old_ext, new_ext = part.rsplit(".", 1)[-1].lower(), src.suffix[1:].lower()
                if SAME_FORMAT.get(old_ext, old_ext) != SAME_FORMAT.get(new_ext, new_ext):
                    print(
                        f"ERROR {name} slide {pic.slide_no}: source is .{new_ext} but the slide holds .{old_ext}; "
                        f"insert the new file in PowerPoint once, then run extract"
                    )
                    errors += 1
                    continue
                print(f"{'update' if write else 'stale '} {name} slide {pic.slide_no}: {f['source']}", end="")
                if not write:
                    print()
                    continue
                # Media shared with a picture that has a different source gets its own copy.
                if deck.references(part) > 1 and any(
                    source_of.get(o.key) != f["source"]
                    for o in deck.pictures()
                    if o.media_rid and deck.rels(o.slide_part).get(o.media_rid) == part and o.key != pic.key
                ):
                    new_part = deck.new_media_part(old_ext)
                    deck.repoint(pic, pic.media_rid, new_part)
                    deck.data[new_part] = old
                    pic = deck.find(pic.key)[0]
                    part = new_part
                    if pic.fallback_rid:  # the PNG fallback is shared too: split it as well
                        _, fb = deck.media(pic, pic.fallback_rid)
                        new_fb = deck.new_media_part("png")
                        deck.repoint(pic, pic.fallback_rid, new_fb)
                        deck.data[new_fb] = fb
                        pic = deck.find(pic.key)[0]
                deck.data[part] = new
                notes = []
                a, b = image_size(old, old_ext), image_size(new, new_ext)
                if a and b and abs((b[0] / b[1]) / (a[0] / a[1]) - 1) > ASPECT_TOLERANCE:
                    notes.append(deck.resize_frame(pic, (b[0] / b[1]) / (a[0] / a[1])))
                    pic = deck.find(pic.key)[0]
                if pic.fallback_rid:
                    fb_part, fb = deck.media(pic, pic.fallback_rid)
                    png = render_png(new, image_size(fb, "png")[0])
                    if png is None:
                        notes.append("mutool not found, PNG fallback not refreshed")
                    else:
                        deck.data[fb_part] = png
                deck.changed = True
                print(f" ({'; '.join(notes)})" if notes else "")
        if write and deck.changed:
            deck.save()
    if errors:
        print(f"{errors} error(s)")
    if not write:
        print(f"{stale} picture(s) out of date" if stale else "all decks match their sources")
    return 1 if errors or (stale and not write) else 0


def cmd_decks(args):
    m = load_manifest()
    files = {Path(f).as_posix().lstrip("./") for f in args.files}
    print(" ".join(sorted({f"Lectures/Slides/{f['deck']}" for f in m["figure"] if f["source"] in files}, key=natural)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="add pictures not yet in the manifest, writing their files")
    ex.add_argument(
        "--ignore-repeated",
        type=int,
        default=15,
        metavar="N",
        help="treat images placed on more than N slides as template branding (default 15)",
    )
    sub.add_parser("sync", help="copy changed sources into the decks")
    sub.add_parser("check", help="exit 1 if any deck is out of date with its sources")
    dk = sub.add_parser("decks", help="print the decks that use any of FILES")
    dk.add_argument("files", nargs="*")
    args = ap.parse_args()
    if args.cmd == "extract":
        cmd_extract(args)
    elif args.cmd == "decks":
        cmd_decks(args)
    else:
        sys.exit(sync(write=args.cmd == "sync"))


if __name__ == "__main__":
    main()
