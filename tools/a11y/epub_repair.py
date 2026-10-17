#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["lxml==6.1.2"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Repair tex4ebook's EPUB 3 output so it validates (epubcheck) and reads well.

    uv run tools/a11y/epub_repair.py BOOK.epub [...]

EPUB content documents are XHTML checked against a strict schema; tex4ht writes
HTML5-tolerant markup. In every content document this:
  - puts <math> (and everything in it) in the MathML namespace;
  - drops empty MathML rowlines/columnlines (matrices without rules);
  - drops HTML4 table attributes (rules, frame, cellspacing, cellpadding, summary);
  - turns wrappers that hold blocks (span.rotatebox, p around a figure) into divs;
  - makes each <figcaption> the first or last child of its <figure> (label anchors
    that precede it move into it; a caption nested deeper moves up to its figure,
    and a caption outside any figure makes its wrapper the figure);
  - percent-encodes spaces in link URLs;
  - turns the non-breaking spaces tex4ht writes in code (blocks and \\verb) into plain spaces
    (copied code compiles).
The book is rewritten in place with the mimetype entry first and uncompressed.
"""

import argparse
import sys
import urllib.parse
import zipfile
from pathlib import Path

from lxml import etree

XHTML = "http://www.w3.org/1999/xhtml"
MATHML = "http://www.w3.org/1998/Math/MathML"
X = f"{{{XHTML}}}"
M = f"{{{MATHML}}}"
BLOCKS = {"div", "figure", "figcaption", "p", "table", "ul", "ol", "dl", "pre", "blockquote", "section", "hr"}
TABLE_ATTRS = ("rules", "frame", "cellspacing", "cellpadding", "summary")


def local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def repair(root):
    changes = 0
    # MathML namespace: tex4ht's <math> is in the XHTML namespace, with its children.
    for math in root.iter(X + "math"):
        for el in math.iter():
            if isinstance(el.tag, str) and el.tag.startswith(X):
                el.tag = M + local(el)
                changes += 1
    for tbl in root.iter(M + "mtable"):
        for attr in ("rowlines", "columnlines"):
            if attr in tbl.attrib and not tbl.get(attr).strip():
                del tbl.attrib[attr]
                changes += 1
    for tbl in root.iter(X + "table"):
        for attr in TABLE_ATTRS:
            if attr in tbl.attrib:
                del tbl.attrib[attr]
                changes += 1
    # Wrappers holding blocks (span, p) become divs (repeat: wrappers can nest).
    again = True
    while again:
        again = False
        for span in [*root.iter(X + "span"), *root.iter(X + "p")]:
            if any(local(c) in BLOCKS for c in span):
                span.tag = X + "div"
                changes += 1
                again = True
    # Captions: a direct child of their figure, first or last.
    for cap in list(root.iter(X + "figcaption")):
        fig = next((a for a in cap.iterancestors() if a.tag == X + "figure"), None)
        if fig is None:
            # A caption outside any figure (tex4ht's rotated figures): its wrapper is the figure.
            fig = cap.getparent()
            fig.tag = X + "figure"
            changes += 1
        if cap.getparent() is not fig:
            cap.getparent().remove(cap)
            fig.append(cap)
            changes += 1
            continue
        kids = [c for c in fig if isinstance(c.tag, str)]
        if kids[0] is cap or kids[-1] is cap:
            continue
        for k in kids[: kids.index(cap)]:
            if local(k) in ("span", "a") and not "".join(k.itertext()).strip() and not len(k):
                tail = k.tail
                fig.remove(k)
                k.tail = None
                cap.insert(0, k)
                if tail:
                    prev = cap.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or "") + tail
                changes += 1
        kids = [c for c in fig if isinstance(c.tag, str)]
        if kids[0] is not cap and kids[-1] is not cap:
            fig.remove(cap)
            fig.append(cap)
            changes += 1
    # Code (blocks and inline): tex4ht writes every space as U+00A0, which breaks copied code
    # (compilers reject it); plain spaces copy cleanly and still render in <pre>.
    for pre in root.iter(X + "pre", X + "code"):
        for el in pre.iter():
            for attr in ("text", "tail"):
                value = getattr(el, attr)
                if el is not pre or attr == "text":
                    if value and "\u00a0" in value:
                        setattr(el, attr, value.replace("\u00a0", " "))
                        changes += 1
    for a in root.iter(X + "a"):
        href = a.get("href")
        if href and " " in href:
            a.set("href", urllib.parse.quote(href, safe=":/?#[]@!$&'()*+,;=%~"))
            changes += 1
    return changes


def repair_book(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        data = {i.filename: z.read(i.filename) for i in infos}
    total = 0
    for name, content in data.items():
        if not name.endswith((".xhtml", ".html")):
            continue
        parser = etree.XMLParser(resolve_entities=False, remove_blank_text=False)
        root = etree.fromstring(content, parser)
        n = repair(root)
        if n:
            data[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>")
            total += n
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as out:
        # OCF: "mimetype" first and stored, then everything else compressed.
        out.writestr(zipfile.ZipInfo("mimetype"), data.pop("mimetype", b"application/epub+zip"), zipfile.ZIP_STORED)
        for info in infos:
            if info.filename in data:
                out.writestr(info.filename, data[info.filename], zipfile.ZIP_DEFLATED)
    tmp.replace(path)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books", nargs="+")
    args = ap.parse_args()
    for book in args.books:
        n = repair_book(Path(book))
        print(f"{book}: {n} repair(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
