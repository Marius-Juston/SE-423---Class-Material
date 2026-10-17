#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Run the accessibility checkers and apply the ratchet (a11y-baseline.json).

    uv run tools/a11y/run_all.py                      # linters only (LaTeX + PPTX)
    uv run tools/a11y/run_all.py --pdf-root build --html-root deploy_target   # as CI
    uv run tools/a11y/run_all.py --update-baseline    # lock in improvements
    uv run tools/a11y/run_all.py --files a.tex b.pptx # only these files (pre-commit)

Checkers run only when their input exists: latex, pptx and cvd (figure colours) always; pdf with --pdf-root
(veraPDF via $VERAPDF, PATH or --docker); epub with --epub-root (epubcheck, Java);
html with --html-root; make4ht with
--make4ht-failures (a file listing the documents whose HTML build failed).

Exit status 1 when an error-severity finding is new or got worse than the baseline.
Writes build/a11y/report.json (all findings) and, on GitHub Actions, a job summary.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import findings as fd  # noqa: E402

HERE = Path(__file__).resolve().parent


def run_tool(script, args):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d, "findings.json")
        r = subprocess.run(
            # --locked: the script's dependencies come from its committed <script>.py.lock
            # (exact versions and hashes); a stale lock is an error, not a silent re-resolve.
            ["uv", "run", "--quiet", "--locked", str(HERE / script), *args, "--json", str(out)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or not out.exists():
            sys.exit(f"{script} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        return fd.read(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="*", help="limit the linters to these files (no baseline update)")
    ap.add_argument("--pdf-root", help="directory of built PDFs (e.g. build)")
    ap.add_argument("--docker", action="store_true", help="run veraPDF from Docker")
    ap.add_argument("--epub-root", help="directory of built EPUBs (e.g. build); needs Java")
    ap.add_argument("--html-root", help="directory served as the site (e.g. deploy_target or site)")
    ap.add_argument("--make4ht-failures", help="file listing documents whose HTML build failed")
    ap.add_argument("--report", default=str(fd.REPO / "build/a11y/report.json"))
    ap.add_argument("--sarif", help="also write the findings as SARIF (GitHub code scanning)")
    ap.add_argument("--update-baseline", action="store_true", help="lower baseline counts to the current state")
    ap.add_argument("--accept-new", action="store_true", help="with --update-baseline: also accept new problems")
    args = ap.parse_args()

    found, tools = [], set()
    files = [str(Path(f).resolve()) for f in args.files] if args.files is not None else None
    tex = [f for f in files if f.endswith(".tex")] if files is not None else []
    pptx = [f for f in files if f.endswith(".pptx")] if files is not None else []

    if files is None or tex:
        found += run_tool("lint_latex.py", tex)
        tools.add("latex")
    if files is None or pptx:
        found += run_tool("lint_pptx.py", pptx)
        tools.add("pptx")
    svgs = [f for f in files if f.endswith(".svg")] if files is not None else []
    if files is None or svgs:
        found += run_tool("cvd_check.py", svgs)  # warnings only: reported, never gating
        tools.add("cvd")
    checked = {}  # tool -> files actually examined (CI builds only what changed)
    if args.pdf_root and Path(args.pdf_root).is_dir():
        found += run_tool("check_pdf.py", ["--root", args.pdf_root] + (["--docker"] if args.docker else []))
        tools.add("pdf")
        root = Path(args.pdf_root)
        checked["pdf"] = {
            p.relative_to(root).as_posix() for p in root.rglob("*.pdf") if "Lectures/Figures" not in p.as_posix()
        }
    if args.epub_root and Path(args.epub_root).is_dir() and any(Path(args.epub_root).rglob("*.epub")):
        found += run_tool("check_epub.py", ["--root", args.epub_root])
        tools.add("epub")
        root = Path(args.epub_root)
        checked["epub"] = {p.relative_to(root).as_posix() for p in root.rglob("*.epub")}
    if args.html_root and Path(args.html_root).is_dir():
        found += run_tool("check_html.py", ["--root", args.html_root])
        tools.add("html")
        root = Path(args.html_root)
        checked["html"] = {p.relative_to(root).as_posix() for p in root.rglob("*.html")}
    if args.make4ht_failures:
        tools.add("make4ht")
        p = Path(args.make4ht_failures)
        for doc in p.read_text().split() if p.exists() else []:
            found.append(fd.Finding("make4ht", doc, "html/not-produced", "the accessible HTML version failed to build"))

    found = fd.merge(found)
    baseline = fd.load_baseline()
    if files is not None:
        touched = {Path(f).relative_to(fd.REPO).as_posix() for f in files}
        baseline = {k: n for k, n in baseline.items() if k.split(" | ")[1] in touched}
    scoped = {
        k: n
        for k, n in baseline.items()
        if k.split(" | ")[0] not in checked or k.split(" | ")[1] in checked[k.split(" | ")[0]]
    }
    regressions, improved = fd.compare(found, scoped, tools)

    if files is None:
        fd.write(found, args.report)
        # Tools that examined only some files this run (CI builds what changed).
        Path(args.report).with_name("checked.json").write_text(
            json.dumps({tool: sorted(names) for tool, names in checked.items()}, indent=1) + "\n"
        )
    if args.sarif:
        Path(args.sarif).parent.mkdir(parents=True, exist_ok=True)
        Path(args.sarif).write_text(json.dumps(fd.sarif(found, baseline), indent=1) + "\n")
    summary = fd.summary_markdown(found, regressions, improved if files is None else [])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as s:
            s.write(summary + "\n")
    if files is None or regressions:
        print(summary)
    else:
        print(f"accessibility: no new problems in {len(files)} file(s)")

    if args.update_baseline:
        if files is not None:
            sys.exit("--update-baseline needs a full run (no --files)")
        fd.save_baseline(fd.updated_baseline(found, fd.load_baseline(), tools, args.accept_new))
        print(f"updated {fd.BASELINE.relative_to(fd.REPO)}")
        return
    if regressions:
        for f in regressions:
            print(
                f"::error file={f.file}::{f.rule} {f.where}: {f.message}" if os.environ.get("GITHUB_ACTIONS") else "",
                end="",
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
