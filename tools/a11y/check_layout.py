#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pdfplumber==0.11.10"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Find text that spills out of place in the built handouts (normal and large print).

    uv run tools/a11y/check_layout.py --root build [--json OUT] [PDF ...]

Large print (1.3x fonts, 1.5 spacing) is where layouts break first: tables taller than
the page run over the footer, code runs out of its table cell, long words run into the
margin. Checked on each PDF's pages, and in the LaTeX log next to it:

  layout/text-overlap      characters drawn over other characters (e.g. table rows over the footer)
  layout/text-crosses-rule a word crossing a vertical rule (text out of its table cell)
  layout/text-off-page     text within 0.25 in of the paper edge
  layout/page-overflow     content taller than the page (LaTeX "Overfull \\vbox ... while
                           \\output is active")
  layout/overfull-line     (warning) a line wider than the text block by 3 pt or more

Findings are counted per document; the message lists the pages (or source lines).
Slide PDFs (Lectures/) are not checked: slides are laid out by hand, not by LaTeX.
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from findings import Finding, write  # noqa: E402

EDGE = 18  # pt: text closer than this to the paper edge is off the page
OVERFULL_PT = 3.0  # overfull lines narrower than this are invisible in practice


def overlaps(page):
    """Pairs of characters drawn over each other (rows over a footer, lines over lines).

    Characters, not words: text drawn on the same baseline as other text gets merged
    into one garbled word by word extraction."""
    chars = sorted(
        (c["x0"], c["x1"], c["top"], c["bottom"], c["text"])
        for c in page.chars
        if c["text"].strip() and c.get("upright", True) and not unicodedata.combining(c["text"][0])
    )
    hits = []
    for i, (x0, x1, t0, b0, a) in enumerate(chars):
        w0 = x1 - x0
        for u0, u1, s0, c0, b in chars[i + 1 :]:
            if u0 >= x1:
                break
            dx = min(x1, u1) - max(x0, u0)
            dy = min(b0, c0) - max(t0, s0)
            # Most of the narrower glyph covered, and the boxes' ink cores cross.
            if dx > 0.6 * min(w0, u1 - u0) and dy > 0.5 * min(b0 - t0, c0 - s0):
                hits.append(a + b)
    return hits


def crossings(page):
    """Words cut by a vertical rule (a table border, a code frame)."""
    rules = [
        e
        for e in page.edges
        if e["orientation"] == "v"
        and abs(e["x1"] - e["x0"]) < 0.5  # truly vertical (diagonal lines are reported as "v" too)
        and e["bottom"] - e["top"] >= 12
        and e.get("object_type") != "curve"
    ]
    if not rules:
        return []
    hits = []
    for w in page.extract_words():
        mid = (w["top"] + w["bottom"]) / 2
        for e in rules:
            if w["x0"] + 1.5 < e["x0"] < w["x1"] - 1.5 and e["top"] <= mid <= e["bottom"]:
                hits.append(w["text"])
                break
    return hits


def off_page(page):
    return [
        c["text"]
        for c in page.chars
        if c["text"].strip() and (c["x0"] < EDGE or c["x1"] > page.width - EDGE or c["bottom"] > page.height - EDGE / 2)
    ]


def log_findings(log):
    """(page overflows, [(width, lines)] overfull lines) from a LaTeX log."""
    if not log.exists():
        return 0, []
    text = log.read_text(errors="replace")
    vbox = len(re.findall(r"Overfull \\vbox \([\d.]+pt too high\) has occurred while \\output is active", text))
    lines = [
        (float(w), ln)
        for w, ln in re.findall(
            r"Overfull \\hbox \(([\d.]+)pt too wide\) in (?:paragraph|alignment) at lines (\d+--\d+)", text
        )
        if float(w) >= OVERFULL_PT
    ]
    return vbox, lines


def check(pdf, root):
    rel = pdf.relative_to(root).as_posix()
    out = []
    per_rule = {}
    with pdfplumber.open(pdf) as doc:
        for no, page in enumerate(doc.pages, 1):
            for rule, hits in (
                ("layout/text-overlap", overlaps(page)),
                ("layout/text-crosses-rule", crossings(page)),
                ("layout/text-off-page", off_page(page)),
            ):
                if hits:
                    per_rule.setdefault(rule, []).append((no, hits))
    what = {
        "layout/text-overlap": "text drawn over other text",
        "layout/text-crosses-rule": "text crossing a table or frame border",
        "layout/text-off-page": "text running off the page",
    }
    for rule, pages in per_rule.items():
        sample = "; ".join(f"p. {no}: {' '.join(map(str, hits[:3]))[:60]}" for no, hits in pages[:6])
        out.append(Finding("layout", rel, rule, f"{what[rule]} ({sample})", count=len(pages)))
    vbox, lines = log_findings(pdf.with_suffix(".log"))
    if vbox:
        out.append(Finding("layout", rel, "layout/page-overflow", "content taller than the page", count=vbox))
    if lines:
        sample = ", ".join(f"lines {ln} ({w:.0f} pt)" for w, ln in lines[:6])
        out.append(
            Finding(
                "layout",
                rel,
                "layout/overfull-line",
                f"lines wider than the text block: {sample}",
                severity="warning",
                count=len(lines),
            )
        )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--root", default="build", help="directory the PDF paths are reported relative to")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    root = Path(args.root)
    pdfs = [Path(p) for p in args.pdfs] or sorted(
        p
        for p in root.rglob("*.pdf")
        if not p.relative_to(root).as_posix().startswith("Lectures/") and "_minted" not in p.as_posix()
    )
    findings = []
    for pdf in pdfs:
        found = check(pdf, root)
        findings += found
        rel = pdf.relative_to(root).as_posix()
        print(f"{'FAIL' if any(f.severity == 'error' for f in found) else 'ok  '} {rel}")
        for f in found:
            print(f"       {f.rule} x{f.count}: {f.message}")
    if args.json:
        write(findings, args.json)


if __name__ == "__main__":
    main()
