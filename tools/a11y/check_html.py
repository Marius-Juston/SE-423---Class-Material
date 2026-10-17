#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.63.0"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Check HTML pages with axe-core (WCAG 2.2 A/AA) in light and dark mode, and reflow.

    uv run tools/a11y/check_html.py --root DIR [--json OUT] [PAGE.html ...]

Pages are served from --root over a local HTTP server (some tools fetch JSON), opened
in headless Chromium with prefers-color-scheme light and dark, and scanned with a
pinned, hash-checked axe-core. One finding per (page, rule, colour scheme), counting
the offending elements. critical/serious violations are errors; moderate/minor are
warnings.

Reflow (WCAG 1.4.10): each page is also opened 320 CSS px wide (a 1280 px window at
400 % zoom) and checked for content that spills (html/reflow-*). Code and tables may
scroll inside their own box; text may not run off the screen or out of its box. Code
(<pre>, <code>) must not hold non-breaking spaces (html/code-nbsp): copied, it breaks.

First run: `uv run tools/a11y/check_html.py --install-browser` (the Chromium
build matching the locked Playwright version; add --with-deps on a fresh CI machine).
"""

import argparse
import functools
import hashlib
import http.server
import subprocess
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
REFLOW_WIDTH = 320  # CSS px: a 1280 px wide window at 400 % zoom

# Content that spills at the current width: the page's sideways scroll, visible text
# outside the viewport (not inside a scrollable box), and text running out of its own
# box (a long word through a table cell). Visually hidden text (sr-only) is skipped.
REFLOW_JS = """() => {
  const W = document.documentElement.clientWidth;
  const hidden = el => {
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === 'none' || cs.visibility === 'hidden') return true;
      if (cs.position === 'absolute' && (cs.clip !== 'auto' || cs.clipPath !== 'none')) return true;
      const r = a.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) return true;
      if (a.closest('details:not([open])') && a.tagName !== 'SUMMARY' && !a.closest('summary')) return true;
    }
    return false;
  };
  const scrolls = el => {
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const o = getComputedStyle(a).overflowX;
      if (o === 'auto' || o === 'scroll') return true;
    }
    return false;
  };
  const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/)[0] : '');
  function* ancestors(el) { for (let a = el; a && a !== document.body; a = a.parentElement) yield a; }
  const ownText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  // Box of an element's own visible characters (spaces that hang past the edge in
  // pre-wrap code, such as alignment padding, are invisible and do not count).
  const ink = el => {
    let box = null;
    for (const n of el.childNodes) {
      if (n.nodeType !== 3) continue;
      const t = n.textContent, a = t.search(/\\S/);
      if (a < 0) continue;
      const range = document.createRange();
      range.setStart(n, a);
      range.setEnd(n, t.length - (t.length - t.trimEnd().length));
      for (const q of range.getClientRects()) {
        box = box ? {left: Math.min(box.left, q.left), right: Math.max(box.right, q.right)}
                  : {left: q.left, right: q.right};
      }
    }
    return box;
  };
  const offScreen = [], spills = [];
  for (const el of document.body.querySelectorAll('*')) {
    const media = ['IMG', 'svg', 'CANVAS', 'VIDEO', 'math'].includes(el.tagName);
    if (!ownText(el) && !media) continue;
    if (hidden(el)) continue;
    const r = media ? el.getBoundingClientRect() : ink(el);
    if (!r) continue;
    // Entirely off the screen and positioned there: hidden on purpose (skip links).
    const parked = (r.right <= 0 || r.left >= W) &&
      [...ancestors(el)].some(a => ['absolute', 'fixed'].includes(getComputedStyle(a).position));
    if ((r.right > W + 1 || r.left < -1) && !scrolls(el) && !parked) offScreen.push(name(el));
    const cs = getComputedStyle(el);
    if (!media && cs.overflowX === 'visible' && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0
        && cs.display !== 'inline' && !scrolls(el)) spills.push(name(el));
  }
  // Code holding non-breaking spaces: copied into an editor, it does not compile.
  const nbsp = [...document.querySelectorAll('pre, code')].filter(el => el.textContent.includes('\\u00a0')).length;
  return {scroll: document.documentElement.scrollWidth - W, offScreen, spills, nbsp};
}"""


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
        ctx = browser.new_context(viewport={"width": REFLOW_WIDTH, "height": 640}, reduced_motion="reduce")
        for page_path in pages:
            rel = page_path.relative_to(root).as_posix()
            page = ctx.new_page()
            try:
                page.goto(f"{base}/{rel}", wait_until="load", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                r = page.evaluate(REFLOW_JS)
            except Exception:
                page.close()
                continue  # already reported as html/not-checked
            page.close()
            where = f"{REFLOW_WIDTH}px"
            if r["scroll"] > 1:
                out.append(
                    Finding(
                        "html",
                        rel,
                        "html/reflow-page-scroll",
                        f"page scrolls sideways by {r['scroll']} px at {REFLOW_WIDTH} px wide",
                        where=where,
                    )
                )
            if r["nbsp"]:
                out.append(
                    Finding(
                        "html",
                        rel,
                        "html/code-nbsp",
                        "code with non-breaking spaces (copied code does not compile; tools/a11y/fix_code_spaces.py)",
                        count=r["nbsp"],
                    )
                )
            for rule, items, what in (
                ("html/reflow-off-screen", r["offScreen"], "text or images outside the screen"),
                ("html/reflow-spill", r["spills"], "text running out of its box"),
            ):
                if items:
                    sample = ", ".join(sorted(set(items))[:5])
                    out.append(
                        Finding(
                            "html",
                            rel,
                            rule,
                            f"{what} at {REFLOW_WIDTH} px wide ({sample})",
                            where=where,
                            count=len(items),
                        )
                    )
        ctx.close()
        browser.close()
    server.shutdown()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--root", help="directory served as the site root")
    ap.add_argument("--json", help="write findings here")
    ap.add_argument("--install-browser", action="store_true", help="install the matching Chromium and exit")
    ap.add_argument("--with-deps", action="store_true", help="with --install-browser: also its system libraries")
    args = ap.parse_args()
    if args.install_browser:
        cmd = [sys.executable, "-m", "playwright", "install", *(["--with-deps"] if args.with_deps else []), "chromium"]
        sys.exit(subprocess.run(cmd).returncode)
    if not args.root:
        ap.error("--root is required")
    root = Path(args.root).resolve()
    # Page arguments are relative to --root (or absolute).
    pages = [(root / p).resolve() for p in args.pages] or sorted(root.rglob("*.html"))
    findings = check(pages, root)
    if args.json:
        write(findings, args.json)
    for f in findings:
        print(f"{f.severity:7s} {f.file} [{f.where}] {f.rule} x{f.count}: {f.message}")


if __name__ == "__main__":
    main()
