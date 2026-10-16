#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Keep the pictures in the lecture decks and their source files in step.

Every picture on a slide in Lectures/Slides/L*.pptx is listed in
Lectures/Slides/figures.toml with a source file under Lectures/Figures/. The
deck keeps an embedded copy so it works offline and in any viewer; the source
file can be edited outside PowerPoint (or regenerated, e.g. by SE423Animations).
Either side may change: `auto` works out which one did from git history.

    uv run tools/sync_deck_figures.py extract          # register new pictures, drop deleted ones
    uv run tools/sync_deck_figures.py auto --base REF  # copy each change the way it was made since REF
    uv run tools/sync_deck_figures.py sync             # force sources -> decks
    uv run tools/sync_deck_figures.py pull             # force decks -> sources
    uv run tools/sync_deck_figures.py check            # exit 1 if any picture differs from its source
    uv run tools/sync_deck_figures.py decks FILE...    # decks that use any FILE (used by CI)

`auto`, per picture that differs from its source, compared with REF:
deck changed only -> the source is updated (an edit made in PowerPoint);
source changed only -> the deck is updated (a regenerated or edited file);
both changed -> conflict, nothing is touched and the exit status is 1.
The pre-commit hook (tools/git-hooks, enable with tools/install-hooks.sh) runs
`extract` and `auto --base HEAD` and stages what they write; CI runs
`auto --base <commit before the push>` before exporting the slide PDFs.

Pictures are identified by the slide's id and the picture's creationId, which
PowerPoint keeps across saves (unlike the ppt/media/imageN names, which it
renumbers). Re-rendering the PNG fallback that PowerPoint stores next to an
SVG needs `mutool` (mupdf-tools); without it the old fallback is kept.
Only the standard library is used.
"""

import argparse
import hashlib
import html
import io
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
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SLIDES = REPO / "Lectures" / "Slides"
FIGURES = REPO / "Lectures" / "Figures"
MANIFEST = SLIDES / "figures.toml"
FOLDER = {"svg": "svg", "png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif", "ppm": "ppm"}
SAME_FORMAT = {"jpeg": "jpg"}
ASPECT_TOLERANCE = 0.003
# Pictures that stand in for a video or sound (online/YouTube or embedded): their image is a
# poster frame or thumbnail chosen by PowerPoint, not a figure, so they are never tracked.
MEDIA = re.compile(
    r"<p:nvPr\b(?:(?!</p:nvPr>).)*<(?:a:videoFile|a:audioFile|a:wavAudioFile|a:quickTimeFile|a:audioCd|p14:media)\b",
    re.S,
)
WRITTEN = set()  # repo-relative paths this run created, changed or deleted (for the pre-commit hook)


def written(path):
    WRITTEN.add(Path(path).resolve().relative_to(REPO).as_posix())


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


# ------------------------------------------------------------------ faithful zip writing
def _central_records(raw):
    """{name: raw central-directory record} of a zip file, plus the archive comment."""
    eocd = raw.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise ValueError("not a zip file")
    count, cd_size, cd_offset, comment_len = struct.unpack("<HII H".replace(" ", ""), raw[eocd + 10 : eocd + 22])
    if cd_offset == 0xFFFFFFFF or count == 0xFFFF:
        raise ValueError("ZIP64 archives are not supported")
    records, pos = {}, cd_offset
    for _ in range(count):
        fn, ex, cm = struct.unpack("<HHH", raw[pos + 28 : pos + 34])
        end = pos + 46 + fn + ex + cm
        records[raw[pos + 46 : pos + 46 + fn].decode("utf8")] = raw[pos:end]
        pos = end
    return records, raw[eocd + 22 : eocd + 22 + comment_len]


def write_faithful_zip(raw, infos, data):
    """Rebuild a zip so that every entry whose content is unchanged is copied verbatim
    (local header, compressed bytes and central record), and changed or new entries are
    recompressed with their original header fields. PowerPoint is sensitive to how its
    packages are written, so decks are never repacked wholesale."""
    orig = {i.filename: i for i in zipfile.ZipFile(io.BytesIO(raw)).infolist()}
    central, comment = _central_records(raw)
    first = next(iter(orig.values()), None)
    out, records = io.BytesIO(), []
    for info in infos:
        name, content = info.filename, data[info.filename]
        o, offset = orig.get(name), out.tell()
        crc = zlib.crc32(content)
        if o is not None and o.CRC == crc and o.file_size == len(content):
            h = o.header_offset
            fn, ex = struct.unpack("<HH", raw[h + 26 : h + 30])
            end = h + 30 + fn + ex + o.compress_size
            if o.flag_bits & 0x08:  # data descriptor follows the data
                end += 16 if raw[end : end + 4] == b"PK\x07\x08" else 12
            out.write(raw[h:end])
            rec = central[name]
            records.append(rec[:42] + struct.pack("<I", offset) + rec[46:])
            continue
        method = o.compress_type if o is not None else zipfile.ZIP_DEFLATED
        if method == zipfile.ZIP_DEFLATED:
            c = zlib.compressobj(6, zlib.DEFLATED, -15)
            comp = c.compress(content) + c.flush()
        else:
            method, comp = zipfile.ZIP_STORED, content
        fname = name.encode("utf8")
        if o is not None:
            h = o.header_offset
            fn, ex = struct.unpack("<HH", raw[h + 26 : h + 30])
            local_extra = raw[h + 30 + fn : h + 30 + fn + ex]
            rec = central[name]
            version_needed, flags, _, mtime, mdate = struct.unpack("<HHHHH", rec[6:16])
            flags &= ~0x08
            records.append(
                rec[:8]
                + struct.pack("<HHHHIII", flags, method, mtime, mdate, crc, len(comp), len(content))
                + rec[28:42]
                + struct.pack("<I", offset)
                + rec[46:]
            )
        else:
            local_extra, version_needed, flags = b"", 20, 0
            mtime, mdate = struct.unpack("<HH", central[first.filename][12:16]) if first else (0, 0x21)
            records.append(
                struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    20,
                    20,
                    0,
                    method,
                    mtime,
                    mdate,
                    crc,
                    len(comp),
                    len(content),
                    len(fname),
                    0,
                    0,
                    0,
                    0,
                    0,
                    offset,
                )
                + fname
            )
        out.write(
            struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                version_needed,
                flags,
                method,
                mtime,
                mdate,
                crc,
                len(comp),
                len(content),
                len(fname),
                len(local_extra),
            )
            + fname
            + local_extra
            + comp
        )
    cd_offset = out.tell()
    for rec in records:
        out.write(rec)
    cd_size = out.tell() - cd_offset
    out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(records), len(records), cd_size, cd_offset, len(comment)))
    out.write(comment)
    return out.getvalue()


class Deck:
    def __init__(self, path, content=None):
        self.path = path
        self.raw = content if content is not None else Path(path).read_bytes()
        with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
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
                if MEDIA.search(m[0]):
                    continue  # a video/audio placeholder (e.g. a YouTube embed's thumbnail), not a figure
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
        """Write the deck back, touching only the entries whose content changed."""
        content = write_faithful_zip(self.raw, self.infos, self.data)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if z.testzip() is not None or any(z.read(i.filename) != self.data[i.filename] for i in self.infos):
                raise SystemExit(f"{self.path.name}: failed to write a valid package, original kept")
        tmp = self.path.with_suffix(".pptx.tmp")
        tmp.write_bytes(content)
        tmp.replace(self.path)
        self.raw = content
        written(self.path)


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


# ------------------------------------------------------------------ alt text
DECORATIVE_EXT = (
    '<a:ext uri="{C183D7F6-B498-43B3-948B-1728B52AA6E4}"><adec:decorative '
    'xmlns:adec="http://schemas.microsoft.com/office/drawing/2017/decorative" val="1"/></a:ext>'
)


def _cnvpr(deck, pic):
    x = deck.data[pic.slide_part].decode()
    a, b = pic.span
    m = re.search(r"<p:cNvPr\b[^>]*?(?:/>|>.*?</p:cNvPr>)", x[a:b], re.S)
    return x, a + m.start(), a + m.end(), m[0]


def get_alt(deck, pic):
    """(description, decorative) of a picture."""
    _, _, _, el = _cnvpr(deck, pic)
    descr = re.search(r'\bdescr="([^"]*)"', el.split(">", 1)[0])
    return html.unescape(descr[1]) if descr else "", "adec:decorative" in el and 'val="1"' in el


def set_alt(deck, pic, descr, decorative):
    """Set a picture's description and decorative flag (None leaves the description as is)."""
    x, a, b, el = _cnvpr(deck, pic)
    head, rest = (el[:-2], "") if el.endswith("/>") else el.split(">", 1)
    if descr is not None:
        head = re.sub(r'\sdescr="[^"]*"', "", head)
        if descr:
            head += f' descr="{html.escape(descr, quote=True)}"'
    rest = re.sub(r'<a:ext uri="\{C183D7F6-B498-43B3-948B-1728B52AA6E4\}">.*?</a:ext>', "", rest, flags=re.S)
    if decorative:
        if "<a:extLst>" in rest:
            rest = rest.replace("<a:extLst>", "<a:extLst>" + DECORATIVE_EXT, 1)
        else:
            rest = "<a:extLst>" + DECORATIVE_EXT + "</a:extLst>" + (rest or "</p:cNvPr>")
    rest = rest.replace("<a:extLst></a:extLst>", "")
    new = head + "/>" if not rest or rest == "</p:cNvPr>" else head + ">" + rest
    if new != el:
        deck.data[pic.slide_part] = (x[:a] + new + x[b:]).encode()
        deck.changed = True


PLACEHOLDER_ALT = re.compile(
    r"^\s*(undefined|image|picture|graphic|photo|screenshot|figure|untitled)?\s*\d*\s*$"
    r"|\.(png|jpe?g|gif|svg|bmp|tiff?|emf|wmf)\s*$",
    re.I,
)


def importable_alt(descr):
    """A description worth keeping (not empty, "undefined", a file name, ...)."""
    return descr.strip() if descr.strip() and not PLACEHOLDER_ALT.search(descr.strip()) else ""


def wanted_alt(entry):
    """(description to publish or None, decorative) from a manifest entry; drafts are not published."""
    alt = entry.get("alt") if entry.get("alt_status", "reviewed") == "reviewed" else None
    return alt, bool(entry.get("decorative"))


# ------------------------------------------------------------------ manifest
HEADER = """\
# Pictures in the lecture decks and the source file each one is copied from.
# Maintained by tools/sync_deck_figures.py (`extract` adds new pictures and drops
# deleted ones); `source` may be edited by hand to point a picture at another file.
#
# Edit a figure either in PowerPoint or in its source file; the pre-commit hook
# (tools/install-hooks.sh) and CI copy the change to the other side.
#   picture:    "<slide id>/<creationId>" (both kept by PowerPoint across saves)
#   slide:      position in the deck when the entry was made (for humans only)
#   alt:        the picture's description for screen readers (alt text)
#   alt_status: "reviewed" (written into the deck) or "draft" (AI suggestion, kept
#               here until a person approves it with tools/a11y/review_alt.py)
#   decorative: true for purely decorative pictures (no description needed)
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
        ]
        if f.get("alt"):
            out += [f"alt = {q(f['alt'])}", f"alt_status = {q(f.get('alt_status', 'reviewed'))}"]
        if f.get("decorative"):
            out.append("decorative = true")
        out.append("")
    text = "\n".join(out)
    if not MANIFEST.exists() or MANIFEST.read_text() != text:
        MANIFEST.write_text(text)
        written(MANIFEST)


def decks():
    return sorted(SLIDES.glob("L*.pptx"), key=lambda p: natural(p.name))


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower()


def same_format(a, b):
    return SAME_FORMAT.get(a, a) == SAME_FORMAT.get(b, b)


def new_source_path(deck_name, slide_no, ext):
    """A free path for a picture's own source file: Lectures/Figures/<kind>/<deck>/slideNNN_k.<ext>."""
    k = 1
    while True:
        rel = f"Lectures/Figures/{FOLDER.get(ext, ext)}/{Path(deck_name).stem}/slide{slide_no:03d}_{k}.{ext}"
        if not (REPO / rel).exists():
            return rel
        k += 1


def generated_dirs():
    """Per-deck folders that `extract` owns (files there may be removed when unused)."""
    return [d for kind in set(FOLDER.values()) for d in (FIGURES / kind).glob("L*") if d.is_dir()]


# ------------------------------------------------------------------ git
def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True)


def resolve_base(base):
    if not base or set(base) <= {"0"} or git("rev-parse", "--verify", "-q", f"{base}^{{commit}}").returncode:
        return None
    return base


def at_base(base, rel):
    r = git("show", f"{base}:{rel}")
    return r.stdout if r.returncode == 0 else None


# ------------------------------------------------------------------ deck edits
def push(deck, pic, entry, new, source_of):
    """Copy a source file's bytes into the picture's embedded media. Returns (ok, notes)."""
    part, old = deck.media(pic)
    old_ext, new_ext = ext_of(part), ext_of(entry["source"])
    if not same_format(old_ext, new_ext):
        return False, [f"source is .{new_ext} but the slide holds .{old_ext}; replace the picture in PowerPoint"]
    # Media shared with a picture that has a different source gets its own copy (and fallback).
    if deck.references(part) > 1 and any(
        source_of.get(o.key) != entry["source"]
        for o in deck.pictures()
        if o.media_rid and deck.rels(o.slide_part).get(o.media_rid) == part and o.key != pic.key
    ):
        new_part = deck.new_media_part(old_ext)
        deck.repoint(pic, pic.media_rid, new_part)
        deck.data[new_part] = old
        pic = deck.find(pic.key)[0]
        part = new_part
        if pic.fallback_rid:
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
    return True, notes


def pull(pic, entry, data, media_ext):
    """Write a picture's embedded media to its source file. Returns a note."""
    note = ""
    if not same_format(media_ext, ext_of(entry["source"])):
        # Replaced in PowerPoint with another format: give it its own file of the right type.
        old = entry["source"]
        entry["source"] = new_source_path(entry["deck"], pic.slide_no, media_ext)
        note = f" (was {old}; the slide now holds .{media_ext})"
    dest = REPO / entry["source"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    written(dest)
    return note


# ------------------------------------------------------------------ commands
def cmd_extract(args):
    m = load_manifest()
    ignore = set(m["ignore"])

    # Drop entries whose picture was deleted (or whose deck is gone).
    present = {}
    for path in decks():
        present[path.name] = {pic.key for pic in Deck(path).pictures()}
    kept = [f for f in m["figure"] if f["picture"] in present.get(f["deck"], ())]
    for f in m["figure"]:
        if f not in kept:
            print(f"removed  {f['deck']} slide {f['slide']}: picture deleted ({f['source']})")
    removed = len(m["figure"]) - len(kept)
    m["figure"] = kept
    known = {(f["deck"], f["picture"]) for f in m["figure"]}

    have = {}  # content hash -> existing repo file (reuse instead of duplicating)
    for p in sorted(FIGURES.rglob("*")):
        if p.is_file() and p.suffix[1:].lower() in FOLDER:
            have.setdefault(sha1(p.read_bytes()), p.relative_to(REPO).as_posix())

    found, deck_of = [], {}
    for path in decks():
        deck = deck_of[path.name] = Deck(path)
        for pic in deck.pictures():
            if pic.media_rid:
                part, data = deck.media(pic)
                found.append((path.name, pic, part, data, sha1(data)))
    uses = {}
    for *_, h in found:
        uses[h] = uses.get(h, 0) + 1
    for h, n in uses.items():
        if n > args.ignore_repeated and h not in ignore:
            ignore.add(h)
            m["ignore"].append(h)

    added = 0
    for name, pic, part, data, h in found:
        if h in ignore or (name, pic.key) in known:
            continue
        if h not in have:
            rel = new_source_path(name, pic.slide_no, ext_of(part))
            (REPO / rel).parent.mkdir(parents=True, exist_ok=True)
            (REPO / rel).write_bytes(data)
            written(REPO / rel)
            have[h] = rel
        entry = {"deck": name, "slide": pic.slide_no, "picture": pic.key, "source": have[h]}
        descr, decorative = get_alt(deck_of[name], pic)
        if importable_alt(descr):
            entry.update(alt=importable_alt(descr), alt_status="reviewed")
        if decorative:
            entry["decorative"] = True
        m["figure"].append(entry)
        known.add((name, pic.key))
        print(f"added    {name} slide {pic.slide_no}: {have[h]}")
        added += 1
    save_manifest(m)

    # Files `extract` wrote for pictures that no longer exist.
    used = {f["source"] for f in m["figure"]}
    pruned = 0
    for d in generated_dirs():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.relative_to(REPO).as_posix() not in used:
                p.unlink()
                written(p)
                pruned += 1
        if not any(d.iterdir()):
            d.rmdir()
    print(f"extract: {added} added, {removed} removed, {pruned} unused file(s) deleted")


def cmd_sync(mode, base=None):
    """mode: check | sync (sources -> decks) | pull (decks -> sources) | auto (by git history)."""
    m = load_manifest()
    if mode == "auto":
        base = resolve_base(base)
        if base is None:
            print("auto: no usable --base; nothing is copied, differences are only reported")
    by_deck = {}
    for f in m["figure"]:
        by_deck.setdefault(f["deck"], []).append(f)

    errors = conflicts = unresolved = stale = 0
    manifest_changed = False
    for name in sorted(by_deck, key=natural):
        path = SLIDES / name
        if not path.exists():
            print(f"ERROR    {name}: deck not found (run extract)")
            errors += 1
            continue
        deck = Deck(path)
        base_deck = None
        if mode == "auto" and base:
            content = at_base(base, path.relative_to(REPO).as_posix())
            base_deck = Deck(path, content) if content is not None else None
        source_of = {f["picture"]: f["source"] for f in by_deck[name]}

        # Work out what to do with every picture that differs from its source.
        plan = []  # (action, entry, pic)
        for f in by_deck[name]:
            pics = deck.find(f["picture"])
            if not pics:
                print(f"ERROR    {name}: picture {f['picture']} (was slide {f['slide']}) not found (run extract)")
                errors += 1
                continue
            src = REPO / f["source"]
            current_src = src.read_bytes() if src.exists() else None
            for pic in pics:
                _, current = deck.media(pic)
                if current == current_src:
                    continue
                stale += 1
                if mode in ("check", "sync", "pull"):
                    plan.append(({"check": "stale", "sync": "push", "pull": "pull"}[mode], f, pic))
                    continue
                if base is None:
                    plan.append(("unresolved", f, pic))
                    continue
                old = base_deck.find(pic.key) if base_deck else []
                deck_changed = not old or base_deck.media(old[0])[1] != current
                source_changed = at_base(base, f["source"]) != current_src
                if deck_changed and source_changed:
                    plan.append(("conflict", f, pic))
                elif deck_changed:
                    plan.append(("pull", f, pic))
                elif source_changed:
                    plan.append(("push", f, pic))
                else:
                    plan.append(("unresolved", f, pic))

        # Edits made in PowerPoint first, so other pictures sharing the source then follow them.
        pulled = {}
        for action, f, pic in plan:
            if action != "pull":
                continue
            part, data = deck.media(pic)
            if f["source"] in pulled and pulled[f["source"]] != data:
                print(f"CONFLICT {name} slide {pic.slide_no}: {f['source']} was edited differently on several slides")
                conflicts += 1
                continue
            before = f["source"]
            note = pull(pic, f, data, ext_of(part))
            pulled[f["source"]] = data
            manifest_changed |= f["source"] != before
            print(f"pull     {name} slide {pic.slide_no}: slide -> {f['source']}{note}")
        if pulled and mode == "auto":
            # Other pictures using a source that was just updated from a slide.
            for f in by_deck[name]:
                if f["source"] not in pulled:
                    continue
                for pic in deck.find(f["picture"]):
                    if deck.media(pic)[1] != pulled[f["source"]] and not any(
                        p is not None and p.key == pic.key and a in ("pull", "conflict") for a, _, p in plan
                    ):
                        plan.append(("push", f, pic))

        for action, f, pic in plan:
            if action == "stale":
                print(f"stale    {name} slide {pic.slide_no}: {f['source']}")
            elif action == "conflict":
                print(
                    f"CONFLICT {name} slide {pic.slide_no}: both the slide and {f['source']} changed; "
                    f"keep one with `sync` (file wins) or `pull` (slide wins)"
                )
                conflicts += 1
            elif action == "unresolved":
                print(
                    f"differs  {name} slide {pic.slide_no}: {f['source']} (no change since the base to tell "
                    f"which side is newer; run `sync` or `pull`)"
                )
                unresolved += 1
            elif action == "push":
                src = REPO / f["source"]
                if not src.exists():
                    print(f"ERROR    {name} slide {pic.slide_no}: source {f['source']} missing")
                    errors += 1
                    continue
                ok, notes = push(deck, deck.find(pic.key)[0], f, src.read_bytes(), source_of)
                if not ok:
                    errors += 1
                tag = "push    " if ok else "ERROR   "
                print(
                    f"{tag} {name} slide {pic.slide_no}: {f['source']} -> slide"
                    + (f" ({'; '.join(notes)})" if notes else "")
                )
        # Alt text and decorative flags: the manifest and the deck, in the same directions.
        base_alts = {}
        if mode == "auto" and base:
            text = at_base(base, MANIFEST.relative_to(REPO).as_posix())
            for e in tomllib.loads(text.decode()).get("figure", []) if text else []:
                if e["deck"] == name:
                    base_alts[e["picture"]] = wanted_alt(e)
        for f in by_deck[name]:
            for pic in deck.find(f["picture"]):
                have_alt = get_alt(deck, pic)
                want, want_deco = wanted_alt(f)
                if have_alt[1] == want_deco and have_alt[0] == (want or ""):
                    continue
                if want is None and have_alt[0] and (mode == "sync" or f.get("alt") or not importable_alt(have_alt[0])):
                    # The deck's text stays until a reviewed description replaces it: either
                    # figures.toml holds an unreviewed draft, or the text is a placeholder
                    # (lint_pptx reports those), or this is a forced sync.
                    continue
                if mode == "check":
                    stale += 1
                    what = "not in figures.toml (run pull)" if want is None else "differs from figures.toml"
                    print(f"stale    {name} slide {pic.slide_no}: alt text {what}")
                    continue
                direction = {"sync": "push", "pull": "pull"}.get(mode)
                if mode == "auto":
                    if base is None:
                        direction = "unresolved"
                    else:
                        old = base_deck.find(pic.key) if base_deck else []
                        deck_changed = not old or get_alt(base_deck, old[0]) != have_alt
                        man_changed = base_alts.get(pic.key, (None, False)) != (want, want_deco)
                        direction = (
                            "conflict"
                            if deck_changed and man_changed
                            else "pull"
                            if deck_changed
                            else "push"
                            if man_changed
                            else "unresolved"
                        )
                if direction == "push":
                    set_alt(deck, pic, want, want_deco)
                    print(f"alt      {name} slide {pic.slide_no}: figures.toml -> slide")
                elif direction == "pull":
                    if importable_alt(have_alt[0]):
                        f.update(alt=importable_alt(have_alt[0]), alt_status="reviewed")
                    f["decorative"] = have_alt[1]
                    if not f["decorative"]:
                        f.pop("decorative")
                    manifest_changed = True
                    print(f"alt      {name} slide {pic.slide_no}: slide -> figures.toml")
                elif direction == "conflict":
                    print(f"CONFLICT {name} slide {pic.slide_no}: alt text changed in both the slide and figures.toml")
                    conflicts += 1
                else:
                    print(f"differs  {name} slide {pic.slide_no}: alt text (run `sync` or `pull`)")
                    unresolved += 1

        # Template images (logos, figures.toml `ignore`) are decorative.
        ignore = set(m["ignore"])
        tracked = set(source_of)
        for pic in list(deck.pictures()):
            if pic.key in tracked or not pic.media_rid:
                continue
            if sha1(deck.media(pic)[1]) in ignore and not get_alt(deck, pic)[1]:
                if mode == "check":
                    stale += 1
                    continue
                if mode in ("sync", "auto"):
                    set_alt(deck, deck.find(pic.key)[0], None, True)

        if deck.changed:
            deck.save()
    if manifest_changed:
        save_manifest(m)

    summary = []
    if mode == "check":
        summary.append(f"{stale} picture(s) differ from their sources" if stale else "all decks match their sources")
    if conflicts:
        summary.append(f"{conflicts} conflict(s)")
    if unresolved:
        summary.append(f"{unresolved} unresolved difference(s)")
    if errors:
        summary.append(f"{errors} error(s)")
    if summary:
        print("; ".join(summary))
    return 1 if errors or conflicts or (mode == "check" and stale) else 0


def cmd_decks(args):
    m = load_manifest()
    files = {Path(f).as_posix().lstrip("./") for f in args.files}
    print(" ".join(sorted({f"Lectures/Slides/{f['deck']}" for f in m["figure"] if f["source"] in files}, key=natural)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--written", metavar="FILE", help="append the repo paths this run changed to FILE (for hooks)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="register new pictures (writing their files) and drop deleted ones")
    ex.add_argument(
        "--ignore-repeated",
        type=int,
        default=15,
        metavar="N",
        help="treat images placed on more than N slides as template branding (default 15)",
    )
    au = sub.add_parser("auto", help="copy each change in the direction it was made since --base")
    au.add_argument("--base", required=True, help="git revision to compare with (e.g. HEAD)")
    sub.add_parser("sync", help="force: copy sources into the decks")
    sub.add_parser("pull", help="force: copy the decks' pictures into their sources")
    sub.add_parser("check", help="exit 1 if any picture differs from its source")
    dk = sub.add_parser("decks", help="print the decks that use any of FILES")
    dk.add_argument("files", nargs="*")
    args = ap.parse_args()
    status = 0
    if args.cmd == "extract":
        cmd_extract(args)
    elif args.cmd == "decks":
        cmd_decks(args)
    else:
        status = cmd_sync(args.cmd, getattr(args, "base", None))
    if args.written and WRITTEN:
        with open(args.written, "a") as out:
            out.writelines(p + "\n" for p in sorted(WRITTEN))
    sys.exit(status)


if __name__ == "__main__":
    main()
