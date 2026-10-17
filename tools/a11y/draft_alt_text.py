#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic==1.11.0", "pillow==12.3.0", "python-pptx==1.0.2", "coloraide==8.13"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Draft alt text for slide pictures with Claude (vision), for a person to review.

    uv run tools/a11y/draft_alt_text.py submit [--limit N]   # send a batch (50% price)
    uv run tools/a11y/draft_alt_text.py status               # how far the batch is
    uv run tools/a11y/draft_alt_text.py collect              # write the drafts into figures.toml

Every picture in Lectures/Slides/figures.toml without reviewed alt text is sent once
per distinct source image, with the slide's title and text as context. Results are
stored as `alt_status = "draft"`: drafts are never written into the decks; review them
with tools/a11y/review_alt.py. Reviewed text is never overwritten. Pictures Claude
judges purely decorative come back as decorative drafts.

Credentials: ANTHROPIC_API_KEY, else the file ~/.config/se423/anthropic-api-key, else
an `ant auth login` profile. The key is never printed.
"""

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

MODEL = "claude-opus-5-5"
KEY_FILE = Path.home() / ".config/se423/anthropic-api-key"
STATE = sdf.REPO / "build/a11y/alt-batch.json"
MAX_EDGE = 1568  # longest image edge sent (larger images are scaled down)

SYSTEM = """You write alt text for figures in university engineering lecture slides \
(UIUC SE 423, Introduction to Mechatronics: microcontrollers, sensors, control, robotics). \
Students who use screen readers rely on it, so it must convey what a sighted student learns \
from the picture in the context of the slide.

Rules:
- Describe the information, not the appearance: what the figure shows and why it is on this slide.
- Be concise: one or two sentences for simple pictures; for diagrams, plots and circuits, up to \
about 80 words covering the key components, connections, axes, trends or values.
- Do not start with "Image of", "Picture of" or "Diagram showing a"; say the type only when it \
matters ("Circuit:", "Plot:", "Photo:").
- Read equations as speech ("x sub t equals x sub t minus 1 plus ...").
- Do not repeat text that is already on the slide unless the picture adds to it.
- If the picture is purely decorative (a logo, a background flourish, an icon that adds nothing), \
reply with exactly DECORATIVE.
Reply with the alt text only, no preamble or quotes."""


def client():
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY") and KEY_FILE.exists():
        return anthropic.Anthropic(api_key=KEY_FILE.read_text().strip())
    return anthropic.Anthropic()


def image_block(path):
    """A base64 image block for the source file (SVG rendered to PNG; big images scaled)."""
    from PIL import Image

    ext = path.suffix[1:].lower()
    data = path.read_bytes()
    if ext == "svg":
        data = sdf.render_png(data, MAX_EDGE)
        if data is None:
            raise RuntimeError("mutool is needed to render SVG figures")
        ext = "png"
    img = Image.open(io.BytesIO(data))
    if ext in ("ppm", "bmp", "tif", "tiff") or max(img.size) > MAX_EDGE or len(data) > 4_500_000:
        img.seek(0)
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        img.thumbnail((MAX_EDGE, MAX_EDGE))
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        data, ext = out.getvalue(), "png"
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}[ext]
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}}


def open_deck(name, cache):
    """The deck Lectures/Slides/<name>, opened once per run."""
    if name not in cache:
        cache[name] = dr.open_deck(sdf.SLIDES / name)
    return cache[name]


def slide_context(prs, entry):
    """Title and other text of the slide holding this picture (entry key: <slide id>/...)."""
    slide = prs.slides.get(int(entry["picture"].split("/")[0]))
    if slide is None:
        return "", ""
    title, body = "", []
    for sp in dr.xp(slide._element, ".//p:sp"):
        paras = [dr.text_of(p).strip() for p in dr.xp(sp, "./p:txBody/a:p")]
        text = "\n".join(p for p in paras if p)
        kind = dr.ph_type(sp)
        if kind in dr.TITLE_TYPES:
            title = text
        elif text and kind not in ("sldNum", "ftr", "dt"):
            body.append(text)
    return title, "\n".join(body)[:3000]


def pending(m):
    """Distinct sources whose pictures still need reviewed alt text -> their entries."""
    groups = {}
    for f in m["figure"]:
        if f.get("decorative") or f.get("alt_status", "reviewed" if f.get("alt") else None) == "reviewed":
            continue
        groups.setdefault(f["source"], []).append(f)
    return groups


def cmd_submit(args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    m = sdf.load_manifest()
    groups = pending(m)
    sources = sorted(groups, key=sdf.natural)[: args.limit or None]
    decks = {}
    requests, ids = [], {}
    for i, source in enumerate(sources):
        entry = groups[source][0]
        title, body = slide_context(open_deck(entry["deck"], decks), entry)
        hint = (
            f"\nAn earlier caption (often just a web page title, may be unhelpful): {entry['alt']}"
            if entry.get("alt")
            else ""
        )
        prompt = (
            f"Lecture deck: {entry['deck']}, slide {entry['slide']}.\nSlide title: {title or '(none)'}\n"
            f"Other text on the slide:\n{body or '(none)'}{hint}\n\nWrite the alt text for this picture."
        )
        try:
            block = image_block(sdf.REPO / source)
        except Exception as e:
            print(f"skip {source}: {e}")
            continue
        cid = f"alt-{i}"
        ids[cid] = source
        requests.append(
            Request(
                custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=16000,
                    output_config={"effort": "medium"},
                    system=SYSTEM,
                    messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
                ),
            )
        )
    if not requests:
        print("nothing to draft: every picture has reviewed alt text")
        return
    if args.dry_run:
        print(f"would submit {len(requests)} request(s) for {sum(len(groups[s]) for s in ids.values())} picture(s)")
        return
    batch = client().messages.batches.create(requests=requests)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"batch": batch.id, "ids": ids}, indent=1))
    print(f"submitted batch {batch.id}: {len(requests)} image(s); run `collect` when it has ended (usually < 1 hour)")


def cmd_status(_args):
    state = json.loads(STATE.read_text())
    b = client().messages.batches.retrieve(state["batch"])
    c = b.request_counts
    print(f"{b.id}: {b.processing_status} (processing {c.processing}, succeeded {c.succeeded}, errored {c.errored})")


def cmd_collect(args):
    state = json.loads(STATE.read_text())
    api = client()
    while True:
        b = api.messages.batches.retrieve(state["batch"])
        if b.processing_status == "ended" or not args.wait:
            break
        print(f"{b.processing_status}: {b.request_counts.processing} still processing ...")
        time.sleep(60)
    if b.processing_status != "ended":
        sys.exit(f"batch {b.id} is still {b.processing_status}; try again later (or pass --wait)")
    m = sdf.load_manifest()
    groups = pending(m)
    drafted = decorative = failed = 0
    for result in api.messages.batches.results(state["batch"]):
        source = state["ids"].get(result.custom_id)
        if result.result.type != "succeeded" or source not in groups:
            failed += result.result.type != "succeeded"
            continue
        msg = result.result.message
        if msg.stop_reason == "refusal":
            print(f"declined: {source} (write this one by hand)")
            failed += 1
            continue
        text = next((b.text for b in msg.content if b.type == "text"), "").strip().strip('"')
        for f in groups[source]:
            if f.get("alt_status") == "reviewed":
                continue
            if text.upper() == "DECORATIVE":
                f.update(alt="(decorative)", alt_status="draft")
                decorative += 1
            elif text:
                f.update(alt=text, alt_status="draft")
                drafted += 1
    sdf.save_manifest(m)
    print(
        f"{drafted} draft(s), {decorative} suggested decorative, {failed} failed; review with tools/a11y/review_alt.py"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--limit", type=int, help="only the first N images (to try it out)")
    s.add_argument("--dry-run", action="store_true", help="count the requests, send nothing")
    sub.add_parser("status")
    c = sub.add_parser("collect")
    c.add_argument("--wait", action="store_true", help="poll until the batch has ended")
    args = ap.parse_args()
    {"submit": cmd_submit, "status": cmd_status, "collect": cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    main()
