#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Validate the EPUB handouts with W3C epubcheck.

    uv run tools/a11y/check_epub.py --root build [--json OUT] [BOOK.epub ...]

epubcheck (pinned release, SHA-256 checked, cached in ~/.cache/se423-a11y; needs
Java) validates each book against the EPUB 3 specification, including its XHTML,
CSS and MathML. One finding per (book, message id): ERROR/FATAL are errors,
WARNING are warnings.
"""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from findings import Finding, write  # noqa: E402

VERSION = "5.4.0"
URL = f"https://github.com/w3c/epubcheck/releases/download/v{VERSION}/epubcheck-{VERSION}.zip"
SHA256 = "33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c"
CACHE = Path.home() / ".cache" / "se423-a11y" / f"epubcheck-{VERSION}"


def epubcheck_jar():
    jar = CACHE / f"epubcheck-{VERSION}" / "epubcheck.jar"
    if not jar.exists():
        with urllib.request.urlopen(URL, timeout=120) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            sys.exit(f"epubcheck download does not match the pinned SHA-256 ({URL})")
        CACHE.mkdir(parents=True, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(CACHE)
    return jar


def check(books, root):
    if not shutil.which("java"):
        sys.exit("epubcheck needs Java (java on the PATH)")
    jar = epubcheck_jar()
    findings = []
    for book in books:
        rel = book.resolve().relative_to(root.resolve()).as_posix()
        r = subprocess.run(["java", "-jar", str(jar), "--json", "-", str(book)], capture_output=True, text=True)
        try:
            report = json.loads(r.stdout)
        except json.JSONDecodeError:
            findings.append(Finding("epub", rel, "epub/unreadable", (r.stderr or r.stdout)[-300:]))
            continue
        counts = {}
        for m in report.get("messages", []):
            sev = "error" if m["severity"] in ("ERROR", "FATAL") else "warning" if m["severity"] == "WARNING" else None
            if not sev:
                continue
            key = (m["ID"], sev)
            n = len(m.get("locations") or [None])
            counts[key] = (counts.get(key, (0, m["message"]))[0] + n, m["message"])
        for (mid, sev), (n, message) in sorted(counts.items()):
            findings.append(Finding("epub", rel, f"epub/{mid}", message[:200], severity=sev, count=n))
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books", nargs="*")
    ap.add_argument("--root", required=True, help="directory the books are published from (e.g. build)")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    root = Path(args.root)
    books = [Path(b) if Path(b).is_absolute() else root / b for b in args.books] or sorted(root.rglob("*.epub"))
    findings = check(books, root)
    if args.json:
        write(findings, args.json)
    for f in findings:
        print(f"{f.severity:7s} {f.file}: {f.rule} x{f.count}  {f.message}")


if __name__ == "__main__":
    main()
