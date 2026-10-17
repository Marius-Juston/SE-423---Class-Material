#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Accessibility lint for the LaTeX documents (the files listed in pdf-list.txt).

    uv run tools/a11y/lint_latex.py [--json OUT] [FILE.tex ...]

Also checks the TikZ figures in Lectures/Figures/*.tex (published as SVGs and in the
figure gallery).

Rules (counted per file, so the keys survive edits):
  latex/tikz-figure-no-alt  a Lectures/Figures/*.tex without a `% alt: ...` description
                            (becomes the SVG's <desc> and the gallery's alt text)
  latex/figure-no-alt       tikzpicture or \\includegraphics outside \\AltStart..\\AltEnd,
                            \\AltImg or \\Annotated (screen readers get nothing)
  latex/figure-no-caption   a figure environment without \\caption
  latex/no-document-metadata  no \\DocumentMetadata (the PDF is not tagged)
  latex/code-typographic-char  curly quotes, dashes, ellipses or invisible spaces inside
                            code (minted/lstlisting/verbatim blocks, \\verb, \\lstinline,
                            \\mintinline): code copied from the PDF or HTML must paste
                            into an editor and compile
  latex/table-header-undeclared  (warning) tables in a document that never declares
                            table header rows for tagging (\\SETableHeaders{1}, header.tex)
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from findings import REPO, Finding, write  # noqa: E402


def strip_comments(tex):
    return re.sub(r"(?<!\\)%.*", "", tex)


def documents():
    files = [line.strip() for line in (REPO / "pdf-list.txt").read_text().splitlines() if line.strip()]
    return [REPO / f for f in files]


def figures():
    return sorted((REPO / "Lectures/Figures").glob("*.tex"))


def lint_figure(path):
    """A TikZ figure needs a `% alt:` comment (tools/a11y/svg_gallery.py publishes it)."""
    if re.search(r"^\s*%\s*alt:\s*\S", path.read_text(), re.M):
        return []
    rel = path.relative_to(REPO).as_posix()
    return [Finding("latex", rel, "latex/tikz-figure-no-alt", "TikZ figure without a `% alt: ...` description")]


# Characters that look like ASCII in print but break code when pasted into an editor.
TYPOGRAPHIC = re.compile("[\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00a0\u200b\u2212\ufeff]")
CODE_BLOCK = re.compile(r"\\begin\{(minted|lstlisting|verbatim|Verbatim)\}(?:\{[^}]*\})?(.*?)\\end\{\1\}", re.S)
CODE_INLINE = re.compile(
    r"\\(?:verb|lstinline)(.)(.*?)\1|\\(?:mintinline|lstinline)(?:\[[^\]]*\])?(?:\{[a-zA-Z]*\})?\{([^}]*)\}"
)


def typographic_in_code(raw):
    """Lines of code (blocks and inline) holding typographic characters."""
    hits = [ln for m in CODE_BLOCK.finditer(raw) for ln in m[2].splitlines() if TYPOGRAPHIC.search(ln)]
    hits += [m[0] for m in CODE_INLINE.finditer(raw) if TYPOGRAPHIC.search(m[2] or m[3] or "")]
    return hits


def lint(path):
    rel = path.relative_to(REPO).as_posix()
    raw = path.read_text()
    tex = strip_comments(raw)
    out = []

    if "\\DocumentMetadata" not in tex:
        out.append(Finding("latex", rel, "latex/no-document-metadata", "no \\DocumentMetadata, so the PDF is untagged"))

    # Pictures outside an alt-text wrapper. \AltImg/\Annotated take the image as an
    # argument, so only bare \includegraphics and tikzpicture are checked, while
    # tracking \AltStart ... \AltEnd nesting.
    depth = 0
    bare = 0
    for m in re.finditer(r"\\(AltStart|AltEnd|includegraphics|begin\{tikzpicture\})", tex):
        tok = m[1]
        if tok == "AltStart":
            depth += 1
        elif tok == "AltEnd":
            depth = max(0, depth - 1)
        elif depth == 0:
            bare += 1
    if bare:
        out.append(
            Finding(
                "latex",
                rel,
                "latex/figure-no-alt",
                "picture without alt text: wrap it in \\AltStart{description} ... \\AltEnd or use \\AltImg",
                count=bare,
            )
        )

    no_caption = sum(
        1 for body in re.findall(r"\\begin\{figure\}(.*?)\\end\{figure\}", tex, re.S) if "\\caption" not in body
    )
    if no_caption:
        out.append(
            Finding(
                "latex",
                rel,
                "latex/figure-no-caption",
                "figure without \\caption (no accessible name in the tagged PDF)",
                count=no_caption,
            )
        )

    typo = typographic_in_code(raw)
    if typo:
        out.append(
            Finding(
                "latex",
                rel,
                "latex/code-typographic-char",
                f"code with curly quotes, dashes or special spaces (breaks when pasted): {typo[0].strip()[:60]}",
                count=len(typo),
            )
        )

    tables = len(re.findall(r"\\begin\{(tabular\*?|tabularx|tblr|longtable)\}", tex))
    declared = "\\SETableHeaders" in tex or "table/header-rows" in tex
    if tables and not declared:
        out.append(
            Finding(
                "latex",
                rel,
                "latex/table-header-undeclared",
                "tables without declared header rows (\\SETableHeaders{1}, see header.tex)",
                severity="warning",
                count=tables,
            )
        )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="documents to lint (default: pdf-list.txt and Lectures/Figures)")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    paths = [Path(f).resolve() for f in args.files] or documents() + figures()
    listed = {p.resolve() for p in documents()}
    tikz = {p.resolve() for p in figures()}
    findings = [f for p in paths if p in listed for f in lint(p)]
    findings += [f for p in paths if p in tikz for f in lint_figure(p)]
    if args.json:
        write(findings, args.json)
    for f in findings:
        print(f"{f.severity:7s} {f.file}: {f.rule} x{f.count}  {f.message}")


if __name__ == "__main__":
    main()
