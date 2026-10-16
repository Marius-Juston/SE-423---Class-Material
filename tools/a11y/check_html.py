#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.64.0"]
# ///
"""Check HTML pages with axe-core (WCAG 2.2 A/AA) in light and dark mode.

    uv run tools/a11y/check_html.py --root DIR [--json OUT] [PAGE.html ...]

Pages are served from --root over a local HTTP server (some tools fetch JSON), opened
in headless Chromium with prefers-color-scheme light and dark, and scanned with a
pinned, hash-checked axe-core. One finding per (page, rule, colour scheme), counting
the offending elements. critical/serious violations are errors; moderate/minor are
warnings. First run: `uv run --with playwright==1.64.0 playwright install chromium`.
"""

import argparse
import functools
import hashlib
import http.server
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from findings import Finding, write  # noqa: E402

AXE_VERSION = "4.13.0"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
AXE_SHA256 = "c24f097bd2f451d4f933e8bc7d8d539f8672a2ebcb5cc9f9f3eec8ca9470a0c1"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


def axe_source():
    cache = Path.home() / ".cache" / "se423-a11y" / f"axe-{AXE_VERSION}.min.js"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(AXE_URL, timeout=60) as r:
            cache.write_bytes(r.read())
    data = cache.read_bytes()
    if hashlib.sha256(data).hexdigest() != AXE_SHA256:
        cache.unlink()
        sys.exit(f"axe-core download does not match the pinned SHA-256 ({AXE_URL})")
    return data.decode()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(root):
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def check(pages, root):
    from playwright.sync_api import sync_playwright

    axe = axe_source()
    server = serve(root)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = browser.new_context(color_scheme=scheme, reduced_motion="reduce")
            for page_path in pages:
                rel = page_path.relative_to(root).as_posix()
                page = ctx.new_page()
                try:
                    page.goto(f"{base}/{rel}", wait_until="load", timeout=60000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    page.add_script_tag(content=axe)
                    result = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS)
                except Exception as e:
                    out.append(
                        Finding(
                            "html", rel, "html/not-checked", f"page could not be checked: {str(e)[:160]}", where=scheme
                        )
                    )
                    page.close()
                    continue
                for v in result["violations"]:
                    sev = "error" if v.get("impact") in ("critical", "serious") else "warning"
                    out.append(
                        Finding(
                            "html", rel, f"axe/{v['id']}", v["help"], where=scheme, severity=sev, count=len(v["nodes"])
                        )
                    )
                page.close()
            ctx.close()
        browser.close()
    server.shutdown()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--root", required=True, help="directory served as the site root")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    pages = [Path(p).resolve() for p in args.pages] or sorted(root.rglob("*.html"))
    findings = check(pages, root)
    if args.json:
        write(findings, args.json)
    for f in findings:
        print(f"{f.severity:7s} {f.file} [{f.where}] {f.rule} x{f.count}: {f.message}")


if __name__ == "__main__":
    main()
