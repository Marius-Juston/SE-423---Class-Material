#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pikepdf==10.16.0"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Finish the PDF/UA tagging of LibreOffice's slide PDFs, in place.

    uv run tools/a11y/tag_slide_pdf.py DECK.pdf [...]

LibreOffice's tagged export (UseTaggedPDF + PDFUACompliance) leaves four gaps that
veraPDF reports on every deck; each is closed here without touching what is drawn:

- Figures without alternative text (the decorative UIUC logo and footer line on every
  slide: LibreOffice ignores PowerPoint's "decorative" flag; real pictures all carry
  alt text, which lint_pptx enforces) become artifacts: their marked content is
  re-marked /Artifact and the element leaves the structure tree. (PDF/UA 7.3)
- Painting outside any marked content (the slide background) is wrapped in /Artifact.
  (PDF/UA 7.1)
- Link annotations get a Link structure element (with an object reference to the
  annotation) and their URL as /Contents. (PDF/UA 7.18.5)
- The viewer shows the document title (DisplayDocTitle), when the deck has one. (7.1)
"""

import argparse
import sys
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator

# Operators that put marks on the page (the rest only set state or build paths).
PAINT = {"f", "F", "f*", "S", "s", "B", "B*", "b", "b*", "Do", "sh", "BI", "INLINE IMAGE", "Tj", "TJ", "'", '"'}


def kids(el):
    k = el.get("/K")
    if k is None:
        return []
    return list(k) if isinstance(k, Array) else [k]


def parent_tree(root):
    """The ParentTree's flat /Nums array (LibreOffice writes one), or None."""
    tree = root.StructTreeRoot.get("/ParentTree")
    return tree.get("/Nums") if tree is not None else None


def page_mcid_parents(nums, page):
    """The ParentTree array of the page's marked content (index = MCID)."""
    key = page.obj.get("/StructParents")
    if key is None or nums is None:
        return None
    for i in range(0, len(nums), 2):
        if int(nums[i]) == int(key):
            return nums[i + 1]
    return None


def figures_without_alt(root):
    """[(element, [(page objgen, mcid)], [structure children])] for Figures with no alt.

    A Figure holding text (a labelled box or arrow) keeps its paragraphs: they move up
    to the Figure's place in its parent, and only the drawing becomes an artifact."""
    out = []

    def walk(el):
        if not isinstance(el, Dictionary) or "/S" not in el:
            return
        children = kids(el)
        if el.S == Name.Figure and "/Alt" not in el and "/ActualText" not in el:
            mcids, structure, ok = [], [], True
            for c in children:
                if isinstance(c, int):
                    if "/Pg" not in el:
                        ok = False
                        break
                    mcids.append((el.Pg.objgen, int(c)))
                elif isinstance(c, Dictionary) and c.get("/Type") == Name.MCR:
                    pg = c.get("/Pg", el.get("/Pg"))
                    if pg is None:
                        ok = False
                        break
                    mcids.append((pg.objgen, int(c.MCID)))
                elif isinstance(c, Dictionary) and "/S" in c:
                    structure.append(c)
                else:
                    ok = False  # an annotation or something unexpected: leave it alone
                    break
            if ok:  # an empty Figure (no content at all) is simply dropped
                out.append((el, mcids, structure))
            return
        for c in children:
            walk(c)

    for c in kids(root.StructTreeRoot):
        walk(c)
    return out


def replace_in_parent(el, root, children):
    """Put children (possibly none) in el's place in its parent's /K."""
    parent = el.get("/P", root.StructTreeRoot)
    for c in children:
        c.P = parent
    k = parent.get("/K")
    items = list(k) if isinstance(k, Array) else ([k] if k is not None else [])
    new = []
    for c in items:
        if isinstance(c, Dictionary) and c.objgen == el.objgen:
            new.extend(children)
        else:
            new.append(c)
    if new:
        parent.K = Array(new)
    elif "/K" in parent:
        del parent["/K"]


def balanced_pieces(ops, lo, hi):
    """Split ops[lo:hi] at its unmatched q/Q: [(start, end)] pieces with balanced q/Q."""
    stack, cuts = [], []
    for i in range(lo, hi):
        name = str(ops[i][1])
        if name == "q":
            stack.append(i)
        elif name == "Q":
            if stack:
                stack.pop()
            else:
                cuts.append(i)
    cuts = sorted(cuts + stack)
    pieces, start = [], lo
    for c in cuts:
        pieces.append((start, c))
        start = c + 1
    pieces.append((start, hi))
    return pieces, cuts


def retag_page(pdf, page, artifact_mcids):
    """Re-mark the given MCIDs as artifacts and wrap untagged painting in /Artifact."""
    ops = list(pikepdf.parse_content_stream(page))
    out, depth, run_start, changed = [], 0, None, False

    def flush(end):
        nonlocal changed
        if run_start is None:
            return
        pieces, cuts = balanced_pieces(ops, run_start, end)
        for n, (a, b) in enumerate(pieces):
            if any(str(op) in PAINT for _, op in ops[a:b]):
                out.append(([Name.Artifact], Operator("BMC")))
                out.extend(ops[a:b])
                out.append(([], Operator("EMC")))
                changed = True
            else:
                out.extend(ops[a:b])
            if n < len(cuts):
                out.append(ops[cuts[n]])

    for i, (operands, op) in enumerate(ops):
        name = str(op)
        if depth == 0 and name not in ("BDC", "BMC"):
            if run_start is None:
                run_start = i
            continue
        if depth == 0:
            flush(i)
            run_start = None
        if name == "BDC":
            props = operands[1] if len(operands) > 1 else None
            if isinstance(props, Dictionary) and "/MCID" in props and int(props.MCID) in artifact_mcids:
                out.append(([Name.Artifact], Operator("BMC")))
                changed = True
            else:
                out.append((operands, op))
            depth += 1
        elif name == "BMC":
            out.append((operands, op))
            depth += 1
        elif name == "EMC":
            out.append((operands, op))
            depth -= 1
        else:
            out.append((operands, op))
    if run_start is not None:
        flush(len(ops))
    if changed:
        page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
    return changed


def tag_links(pdf, nums):
    """Give every untagged Link annotation a Link structure element; return the count."""
    root = pdf.Root.StructTreeRoot
    top = kids(root)
    next_key = int(root.get("/ParentTreeNextKey", 0))
    if nums is not None:
        next_key = max([next_key] + [int(nums[i]) + 1 for i in range(0, len(nums), 2)])
    done = 0
    for page in pdf.pages:
        for annot in page.obj.get("/Annots", []):
            if annot.get("/Subtype") != Name.Link or "/StructParent" in annot:
                continue
            uri = annot.get("/A", {}).get("/URI")
            label = str(uri) if uri is not None else "Link"
            link = pdf.make_indirect(
                Dictionary(
                    Type=Name.StructElem,
                    S=Name.Link,
                    P=root,
                    Pg=page.obj,
                    Alt=pikepdf.String(label),
                    K=Array([Dictionary(Type=Name.OBJR, Obj=annot, Pg=page.obj)]),
                )
            )
            annot.Contents = pikepdf.String(label)
            annot.StructParent = next_key
            if nums is not None:
                nums.append(next_key)
                nums.append(link)
            next_key += 1
            # Reading order: after the last top-level element of the same page.
            at = (
                max(
                    (i for i, el in enumerate(top) if el.get("/Pg") is not None and el.Pg.objgen == page.obj.objgen),
                    default=len(top) - 1,
                )
                + 1
            )
            top.insert(at, link)
            done += 1
        if page.obj.get("/Annots") and page.obj.get("/Tabs") != Name.S:
            page.obj.Tabs = Name.S
    if done:
        root.K = Array(top)
        root.ParentTreeNextKey = next_key
    return done


def fix(path):
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            print(f"{path}: not tagged, skipped")
            return
        nums = parent_tree(pdf.Root)
        figures = figures_without_alt(pdf.Root)
        by_page = {}
        for el, mcids, structure in figures:
            for pg, mcid in mcids:
                by_page.setdefault(pg, set()).add(mcid)
            replace_in_parent(el, pdf.Root, structure)
        wrapped = 0
        for page in pdf.pages:
            mcids = by_page.get(page.obj.objgen, set())
            if retag_page(pdf, page, mcids):
                wrapped += 1
            parents = page_mcid_parents(nums, page)
            if parents is not None:
                for m in mcids:
                    if m < len(parents):
                        parents[m] = pikepdf.Object.parse(b"null")
        links = tag_links(pdf, nums)
        title = pdf.open_metadata().get("dc:title") or pdf.docinfo.get("/Title")
        if title:
            prefs = pdf.Root.get("/ViewerPreferences") or Dictionary()
            prefs.DisplayDocTitle = True
            pdf.Root.ViewerPreferences = prefs
        pdf.save(path)
        print(
            f"{path}: {len(figures)} decorative figure(s) made artifacts, "
            f"{wrapped} page(s) retagged, {links} link(s) tagged, title {'shown' if title else 'missing'}"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    for p in ap.parse_args().pdfs:
        fix(p)


if __name__ == "__main__":
    sys.exit(main())
