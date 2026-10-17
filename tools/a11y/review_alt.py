#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["python-pptx==1.0.2", "coloraide==8.13"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Review drafted alt text in the browser and approve, edit or reject it.

    uv run tools/a11y/review_alt.py [--port 8423]

Opens a local page (127.0.0.1 only) with every picture whose alt text in
Lectures/Slides/figures.toml is still a draft: the image, the slide it is on, and the
draft in an editable box. "Approve" stores the (edited) text as reviewed, "Decorative"
marks the picture decorative, "Skip" leaves it for later. Decisions are saved to
figures.toml immediately; commit them (the pre-commit hook, or
`uv run tools/sync_deck_figures.py sync`, writes the reviewed text into the decks).
"""

import argparse
import html
import http.server
import json
import mimetypes
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import sync_deck_figures as sdf  # noqa: E402
from draft_alt_text import open_deck, slide_context  # noqa: E402

LOCK = threading.Lock()


def drafts():
    groups = {}
    for f in sdf.load_manifest()["figure"]:
        if f.get("alt_status") == "draft":
            groups.setdefault(f["source"], []).append(f)
    return groups


def page():
    groups = drafts()
    decks, cards = {}, []
    for i, (source, entries) in enumerate(sorted(groups.items(), key=lambda kv: sdf.natural(kv[0]))):
        e = entries[0]
        title, body = slide_context(open_deck(e["deck"], decks), e)
        where = ", ".join(f"{x['deck'][:-5]} slide {x['slide']}" for x in entries)
        text = "" if e["alt"] == "(decorative)" else e["alt"]
        note = "<p class='hint'>Suggested: decorative</p>" if e["alt"] == "(decorative)" else ""
        cards.append(f"""
<article id="c{i}" data-source="{html.escape(source)}">
  <img src="/file?path={urllib.parse.quote(source)}" alt="">
  <div>
    <h2>{html.escape(title or "(untitled slide)")}</h2>
    <p class="where">{html.escape(where)}</p>
    <details><summary>Slide text</summary><pre>{html.escape(body or "(none)")}</pre></details>
    {note}
    <label for="t{i}">Alt text</label>
    <textarea id="t{i}" rows="4">{html.escape(text)}</textarea>
    <div class="actions">
      <button data-act="approve">Approve</button>
      <button data-act="decorative">Decorative</button>
      <button data-act="skip">Skip</button>
      <span class="status" role="status"></span>
    </div>
  </div>
</article>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Review alt text</title>
<style>
:root {{ --bg:#fff; --fg:#111; --muted:#555; --card:#f4f5f7; --accent:#13294B; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111; --fg:#eee; --muted:#bbb; --card:#1c1f24; --accent:#9db7e8; }} }}
body {{ font-family: 'Atkinson Hyperlegible Next', system-ui, sans-serif; background:var(--bg); color:var(--fg);
       margin:0 auto; max-width:1100px; padding:16px; }}
article {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; background:var(--card);
          padding:16px; border-radius:8px; margin:16px 0; }}
article.done {{ opacity:.45; }}
img {{ max-width:100%; max-height:420px; object-fit:contain; background:#fff; border-radius:4px; }}
h2 {{ font-size:1.1rem; margin:0 0 4px; }} .where, .hint {{ color:var(--muted); margin:0 0 8px; }}
textarea {{ width:100%; font:inherit; box-sizing:border-box; }}
button {{ font:inherit; padding:6px 14px; margin:8px 8px 0 0; border-radius:6px; border:1px solid var(--accent);
         background:var(--bg); color:var(--fg); cursor:pointer; }}
button[data-act=approve] {{ background:var(--accent); color:var(--bg); }}
:focus-visible {{ outline:3px solid #FF5F05; outline-offset:2px; }}
@media (max-width: 700px) {{ article {{ grid-template-columns:1fr; }} }}
</style></head><body>
<main><h1>Review alt text ({len(groups)} images)</h1>
<p>Approve keeps the text exactly as it is in the box (edit first if needed). Decisions save immediately.</p>
{"".join(cards) or "<p>No drafts to review.</p>"}</main>
<script>
document.addEventListener('click', async ev => {{
  const b = ev.target.closest('button[data-act]'); if (!b) return;
  const card = b.closest('article'), status = card.querySelector('.status');
  const res = await fetch('/save', {{method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{source: card.dataset.source, action: b.dataset.act, alt: card.querySelector('textarea').value}})}});
  status.textContent = res.ok ? ({{approve:'Approved', decorative:'Marked decorative', skip:'Skipped'}})[b.dataset.act] : 'Error: ' + await res.text();
  if (res.ok && b.dataset.act !== 'skip') card.classList.add('done');
  const next = card.nextElementSibling; if (res.ok && next) next.querySelector('textarea').focus();
}});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            return self.send(200, page(), "text/html; charset=utf-8")
        if url.path == "/file":
            rel = urllib.parse.parse_qs(url.query).get("path", [""])[0]
            target = (sdf.REPO / rel).resolve()
            if not target.is_relative_to(sdf.FIGURES) or not target.is_file():
                return self.send(404, "not found")
            return self.send(
                200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
        self.send(404, "not found")

    def do_POST(self):
        if self.path != "/save":
            return self.send(404, "not found")
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        action, alt = req.get("action"), (req.get("alt") or "").strip()
        if action == "approve" and not alt:
            return self.send(400, "empty alt text: write a description or mark it decorative")
        with LOCK:
            m = sdf.load_manifest()
            for f in m["figure"]:
                if f["source"] != req.get("source") or f.get("alt_status") != "draft":
                    continue
                if action == "approve":
                    f.update(alt=alt, alt_status="reviewed")
                elif action == "decorative":
                    f.pop("alt", None)
                    f.pop("alt_status", None)
                    f["decorative"] = True
            if action != "skip":
                sdf.save_manifest(m)
        self.send(200, "ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8423)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Reviewing {len(drafts())} image(s) at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
