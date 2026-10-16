#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Publish the accessibility status of the course material as a web page.

    uv run tools/a11y/report_page.py --report build/a11y/report.json --site deploy_target

Writes <site>/accessibility.html: an accessibility statement (what is provided, how
to ask for something in another format), open problems per checker and per file, and
a trend of open errors over time (<site>/a11y/history.json, one entry per run; the
deploy branch keeps it).

CI rebuilds only what changed, so PDF/EPUB findings of one run cover only those files.
With --checked (written by run_all.py), the published <site>/a11y/report.json is
updated instead of replaced: findings of files checked in this run are replaced, the
others are kept. The merged report is written back there.
"""

import argparse
import datetime as dt
import html
import json
from pathlib import Path

ESC = html.escape
REPO_URL = "https://github.com/Marius-Juston/SE-423---Class-Material"
ISSUE_URL = f"{REPO_URL}/issues/new?template=accessibility.yml"
CHECKERS = {
    "latex": "LaTeX lint (alt text, captions, tagging)",
    "pptx": "Slide lint (titles, alt text, contrast, tables)",
    "pdf": "PDF/UA (veraPDF)",
    "epub": "EPUB 3 (epubcheck)",
    "html": "Web pages (axe-core, WCAG 2.2 AA, light and dark)",
    "make4ht": "HTML conversion",
    "cvd": "Figure colours under colour blindness",
}


def totals(findings):
    out = {}
    for f in findings:
        t = out.setdefault(f["tool"], {"error": 0, "warning": 0})
        t[f["severity"]] = t.get(f["severity"], 0) + f["count"]
    return out


def sparkline(history, width=600, height=120):
    """Inline SVG line of open errors per run, with a text equivalent."""
    pts = [(h["date"], h["errors"]) for h in history][-60:]
    if len(pts) < 2:
        return "<p>The trend appears after the next build.</p>"
    hi = max(e for _, e in pts) or 1
    step = width / (len(pts) - 1)
    coords = " ".join(f"{i * step:.1f},{height - 8 - (e / hi) * (height - 16):.1f}" for i, (_, e) in enumerate(pts))
    first, last = pts[0], pts[-1]
    label = f"Open errors went from {first[1]} on {first[0]} to {last[1]} on {last[0]}."
    return (
        f'<figure><svg viewBox="0 0 {width} {height}" role="img" aria-label="{ESC(label)}" class="trend">'
        f'<polyline points="{coords}" fill="none" stroke="currentColor" stroke-width="3"/></svg>'
        f"<figcaption>{ESC(label)}</figcaption></figure>"
    )


def page(findings, history, generated):
    by_tool = totals(findings)
    errors = sum(t["error"] for t in by_tool.values())
    rows = "".join(
        f"<tr><th scope='row'>{ESC(CHECKERS.get(tool, tool))}</th><td>{t['error']}</td><td>{t['warning']}</td></tr>"
        for tool, t in sorted(by_tool.items())
    )
    files = {}
    for f in findings:
        if f["severity"] == "error":
            files[f["file"]] = files.get(f["file"], 0) + f["count"]
    file_rows = "".join(
        f"<tr><td><code>{ESC(name)}</code></td><td>{n}</td></tr>"
        for name, n in sorted(files.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    rules = {}
    for f in findings:
        if f["severity"] == "error":
            rules[f["rule"]] = rules.get(f["rule"], 0) + f["count"]
    rule_rows = "".join(
        f"<tr><td><code>{ESC(r)}</code></td><td>{n}</td></tr>" for r, n in sorted(rules.items(), key=lambda kv: -kv[1])
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accessibility | SE 423 Mechatronics</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:ital,wght@0,200..800;1,200..800&display=swap">
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#4a4a4a; --accent:#13294B; --link:#0b3d91; --rule:#d0d0d0; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121212; --fg:#eee; --muted:#c4c4c4; --accent:#9db7e8; --link:#9db7e8; --rule:#3a3a3a; }} }}
body {{ margin:0 auto; max-width:56rem; padding:1rem; background:var(--bg); color:var(--fg);
       font:1.125rem/1.6 'Atkinson Hyperlegible Next', system-ui, sans-serif; }}
a {{ color:var(--link); }} :focus-visible {{ outline:3px solid #FF5F05; outline-offset:2px; }}
h1, h2 {{ color:var(--accent); }} .muted {{ color:var(--muted); }}
table {{ border-collapse:collapse; margin:1rem 0; width:100%; }} th, td {{ border:1px solid var(--rule); padding:.35rem .6rem; text-align:left; }}
td {{ font-variant-numeric:tabular-nums; }} .trend {{ width:100%; max-width:600px; height:auto; color:var(--accent); }}
.skip {{ position:absolute; left:-999px; }} .skip:focus {{ left:1rem; top:1rem; background:var(--bg); padding:.5rem; }}
</style></head>
<body><a class="skip" href="#main">Skip to the report</a>
<header><p><a href="index.html">SE 423 course material</a></p><h1>Accessibility</h1></header>
<main id="main">
<section aria-labelledby="statement"><h2 id="statement">Statement</h2>
<p>The SE 423 course material aims to meet WCAG 2.2 level AA, and PDF/UA-2 for documents. Everything is
set in Atkinson Hyperlegible Next. Each handout is available as a tagged PDF, an accessible HTML page
(equations as MathML), an EPUB 3 book and a large-print PDF; each lecture deck as a tagged PDF, the
PowerPoint file and a text version with one section per slide. The web pages work by keyboard alone and in
light and dark mode.</p>
<p>Every change is checked automatically (below). Some material still has known problems, listed here
until they are fixed; new problems are not accepted.</p>
<p><strong>Need something in another format, or found a barrier?</strong>
<a href="{ISSUE_URL}">Report it on GitHub</a> or tell the course staff.</p>
</section>
<section aria-labelledby="status"><h2 id="status">Current status</h2>
<p class="muted">From the build of {ESC(generated)}. {errors} open error(s).</p>
<table><caption class="muted">Open problems by check (warnings are advisory)</caption>
<thead><tr><th scope="col">Check</th><th scope="col">Errors</th><th scope="col">Warnings</th></tr></thead>
<tbody>{rows}</tbody></table>
<h3>Trend</h3>{sparkline(history)}
</section>
<section aria-labelledby="details"><h2 id="details">Details</h2>
<details><summary>Open errors by kind</summary><table><thead><tr><th scope="col">Rule</th><th scope="col">Count</th></tr></thead><tbody>{rule_rows}</tbody></table></details>
<details><summary>Open errors by file</summary><table><thead><tr><th scope="col">File</th><th scope="col">Errors</th></tr></thead><tbody>{file_rows}</tbody></table></details>
<p>Raw data: <a href="a11y/report.json">report.json</a>, <a href="a11y/history.json">history.json</a>.
How the checks work: <a href="{REPO_URL}/blob/main/CONTRIBUTING.md#accessibility">CONTRIBUTING.md</a>.</p>
</section>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="findings JSON written by run_all.py")
    ap.add_argument("--site", required=True, help="published site directory (e.g. deploy_target)")
    ap.add_argument("--checked", help="checked.json from run_all.py: tool -> files examined in this run")
    args = ap.parse_args()
    site = Path(args.site)
    findings = json.loads(Path(args.report).read_text())
    published = site / "a11y" / "report.json"
    if args.checked and published.exists():
        checked = json.loads(Path(args.checked).read_text())
        previous = json.loads(published.read_text())
        # Keep earlier findings only for partially checked tools, on files not checked now.
        findings += [f for f in previous if f["tool"] in checked and f["file"] not in set(checked[f["tool"]])]
    published.parent.mkdir(parents=True, exist_ok=True)
    published.write_text(json.dumps(findings, indent=1) + "\n")
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    hist_path = site / "a11y" / "history.json"
    try:
        history = json.loads(hist_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    history.append(
        {
            "date": now[:10],
            "errors": sum(f["count"] for f in findings if f["severity"] == "error"),
            "warnings": sum(f["count"] for f in findings if f["severity"] == "warning"),
            "by_tool": totals(findings),
        }
    )
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(json.dumps(history[-500:], indent=1) + "\n")
    (site / "accessibility.html").write_text(page(findings, history, now))


if __name__ == "__main__":
    main()
