#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic==1.11.0", "pillow==12.3.0", "python-pptx==1.0.2", "coloraide==8.13", "lxml==6.1.2"]
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Draft lecture notes (the slide notes) for every slide with Claude, then write them in.

    uv run tools/a11y/draft_notes.py submit --renders DIR [--decks L5 L6-7] [--limit N]
    uv run tools/a11y/draft_notes.py status
    uv run tools/a11y/draft_notes.py collect [--wait]     # -> build/a11y/notes/<deck>.json
    uv run tools/a11y/draft_notes.py apply [DECK ...]      # write the collected notes into the decks

--renders holds one PNG per visible slide: DIR/<deck>/s001.png, s002.png, ... (e.g. a
LibreOffice PDF export rendered with `mutool draw -w 1280 -o DIR/<deck>/s%03d.png`).

Each request sends the slide image, its title, text, picture descriptions and existing
notes, the deck's outline (all titles) and the two slides before and after, so the notes
follow the lecture's story. Notes describe the slide (for screen-reader users, as
accessibility guidance recommends), explain it, connect it to its neighbours and add
pitfalls or lab links where useful. Existing notes are kept: their information is part
of the new text. `apply` replaces only the text of each slide's notes placeholder
(every slide already has a notes page) and saves with the byte-faithful writer.

Credentials: ANTHROPIC_API_KEY, else ~/.config/se423/anthropic-api-key. Never printed.
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deck_reader as dr  # noqa: E402
import sync_deck_figures as sdf  # noqa: E402

MODEL = "claude-opus-5-5"
KEY_FILE = Path.home() / ".config/se423/anthropic-api-key"
STATE = sdf.REPO / "build/a11y/notes-batches.json"
OUT = sdf.REPO / "build/a11y/notes"
MAX_EDGE = 1568
CHUNK = 250  # requests per batch (keeps each batch well under the 256 MB limit)

SYSTEM = """You write the lecture notes (the PowerPoint slide notes) for one slide of \
UIUC SE 423, Introduction to Mechatronics: the TMS320F28379D "Red Board" microcontroller, \
peripherals (GPIO, PWM, ADC, SPI, serial, encoders), sensors, filtering, feedback control, \
the Raspberry Pi, and mobile robotics (path planning, trajectory tracking, Kalman filters, \
computer vision, LiDAR SLAM).

The notes are published with the slides. Students read them, including students who use \
screen readers, for whom the notes are the description of the slide, and the instructor \
reads them while presenting.

For each slide write:
1. What the slide shows, so someone who cannot see it gets the same information: the \
point of the text, and a description of figures, diagrams, plots, tables and code. Read \
equations in words next to their plain-text form.
2. The explanation the lecturer would give: the key idea and why it matters, definitions \
of new terms, steps the slide skips, and the concrete numbers or examples on the slide.
3. The thread of the lecture: a sentence connecting to the previous slide or setting up \
the next one, so the notes read as one story.
4. Where it genuinely helps: a common mistake, the link to the lab or the robot, or a \
quick question to check understanding.

Rules:
- Stay faithful to the slide and correct; do not contradict it. Do not invent course \
logistics (dates, grading, rooms, deadlines) that are not on the slide.
- If the slide already has notes, keep all of their information, instructions and URLs \
(you may reorganise and polish them), and build on them.
- Plain text only: no Markdown, no bullet characters, no headings. Short paragraphs \
separated by one blank line. Math in plain text, e.g. x_(t+1) = x_t + v_t*cos(theta_t)*dt.
- About 120 to 250 words for a content slide; 40 to 80 words for a title, agenda, \
section, video or closing slide. Do not pad.
- Address students as "you" where natural; present tense.
Reply with the notes only."""


def client():
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY") and KEY_FILE.exists():
        return anthropic.Anthropic(api_key=KEY_FILE.read_text().strip())
    return anthropic.Anthropic()


def flat(text):
    return re.sub(r"[ \t]+", " ", text).strip()


def slide_info(prs):
    """[(no, slide_id, hidden, title, text, picture descriptions, notes)] for a deck."""
    out = []
    for no, slide in dr.slides(prs):
        title = dr.title_text(slide) or ""
        texts = []
        for sp in dr.xp(slide._element, ".//p:sp"):
            if dr.ph_type(sp) in (*dr.TITLE_TYPES, "sldNum", "dt", "ftr"):
                continue
            paras = [flat(dr.text_of(p)) for p in dr.xp(sp, "./p:txBody/a:p")]
            t = "\n".join(p for p in paras if p)
            if t and t not in ("GRAINGER ENGINEERING", "SYSTEMS ENGINEERING"):
                texts.append(t)
        pics = [
            (dr.cnvpr(p).get("descr") or "").strip()
            for p in dr.xp(slide._element, ".//p:pic")
            if not dr.is_decorative(p) and (dr.cnvpr(p).get("descr") or "").strip()
        ]
        hidden = slide._element.get("show") == "0"
        out.append((no, slide.slide_id, hidden, title, "\n\n".join(texts), pics, "\n".join(dr.notes_text(slide))))
    return out


def image_block(path):
    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()},
    }


def describe(s, full=False):
    no, _sid, _hidden, title, text, pics, notes = s
    parts = [f"Slide {no}: {title or '(no title)'}"]
    if text:
        parts.append("Text on the slide:\n" + (text if full else text[:1200]))
    if pics:
        parts.append("Pictures (alt text):\n" + "\n".join(f"- {p}" for p in pics))
    if full and notes:
        parts.append("Existing notes (keep their information):\n" + notes)
    return "\n".join(parts)


def requests_for(deck_path, renders):
    prs = dr.open_deck(deck_path)
    info = slide_info(prs)
    visible = [s for s in info if not s[2]]
    pngs = sorted((renders / deck_path.stem).glob("s*.png"))
    if len(pngs) != len(visible):
        sys.exit(f"{deck_path.name}: {len(pngs)} renders for {len(visible)} visible slides")
    image_of = {s[1]: png for s, png in zip(visible, pngs, strict=True)}
    outline = "\n".join(f"{s[0]}. {s[3] or '(no title)'}" for s in info)
    reqs = []
    for i, s in enumerate(info):
        if s[1] not in image_of:
            continue  # hidden slide: not presented, no render
        before = [describe(x) for x in info[max(0, i - 2) : i]]
        after = [describe(x) for x in info[i + 1 : i + 3]]
        prompt = (
            f"Lecture deck {deck_path.stem} ({len(info)} slides). Outline:\n{outline}\n\n"
            f"Previous slides:\n{chr(10).join(before) or '(this is the first slide)'}\n\n"
            f"Next slides:\n{chr(10).join(after) or '(this is the last slide)'}\n\n"
            f"THE SLIDE TO WRITE NOTES FOR (image above):\n{describe(s, full=True)}\n\n"
            "Write the lecture notes for this slide."
        )
        reqs.append(((deck_path.name, s[1]), [image_block(image_of[s[1]]), {"type": "text", "text": prompt}]))
    return reqs


def cmd_submit(args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    renders = Path(args.renders)
    decks = [sdf.SLIDES / f"{d}.pptx" for d in args.decks] if args.decks else sdf.decks()
    pending = [r for d in decks for r in requests_for(d, renders)][: args.limit or None]
    if args.dry_run:
        print(f"would submit {len(pending)} request(s) in {(len(pending) + CHUNK - 1) // CHUNK} batch(es)")
        return
    api = client()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"batches": []}
    for start in range(0, len(pending), CHUNK):
        chunk = pending[start : start + CHUNK]
        ids = {}
        reqs = []
        for j, (key, content) in enumerate(chunk):
            cid = f"n{start + j}"
            ids[cid] = key
            reqs.append(
                Request(
                    custom_id=cid,
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL,
                        max_tokens=16000,
                        output_config={"effort": "medium"},
                        system=SYSTEM,
                        messages=[{"role": "user", "content": content}],
                    ),
                )
            )
        batch = api.messages.batches.create(requests=reqs)
        state["batches"].append({"batch": batch.id, "ids": ids})
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
        print(f"submitted {batch.id}: {len(reqs)} slide(s)")


def cmd_status(_args):
    api = client()
    for b in json.loads(STATE.read_text())["batches"]:
        r = api.messages.batches.retrieve(b["batch"])
        c = r.request_counts
        print(
            f"{r.id}: {r.processing_status} (processing {c.processing}, succeeded {c.succeeded}, errored {c.errored})"
        )


def cmd_collect(args):
    api = client()
    state = json.loads(STATE.read_text())
    results = {}
    for b in state["batches"]:
        while True:
            r = api.messages.batches.retrieve(b["batch"])
            if r.processing_status == "ended" or not args.wait:
                break
            print(f"{r.id}: {r.request_counts.processing} still processing ...")
            time.sleep(60)
        if r.processing_status != "ended":
            sys.exit(f"batch {r.id} is still {r.processing_status}; try again later (or pass --wait)")
        for res in api.messages.batches.results(b["batch"]):
            deck, sid = b["ids"][res.custom_id]
            if res.result.type != "succeeded" or res.result.message.stop_reason == "refusal":
                print(f"failed: {deck} slide id {sid}")
                continue
            text = next((c.text for c in res.result.message.content if c.type == "text"), "").strip()
            if text:
                results.setdefault(deck, {})[str(sid)] = text
    OUT.mkdir(parents=True, exist_ok=True)
    for deck, notes in results.items():
        path = OUT / f"{Path(deck).stem}.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        old.update(notes)
        path.write_text(json.dumps(old, indent=1, ensure_ascii=False) + "\n")
        print(f"{deck}: {len(notes)} slide note(s) -> {path.relative_to(sdf.REPO)}")


A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def set_notes(xml, text):
    """Notes slide XML with the body placeholder's text replaced by text (paragraphs)."""
    root = etree.fromstring(xml)
    body = next(
        (sp for sp in dr.xp(root, ".//p:sp") if dr.ph_type(sp) == "body"),
        None,
    )
    if body is None:
        return None
    tx = body.find(dr.q("p:txBody"))
    # Shrink text on overflow, so long notes still fit a printed notes page.
    body_pr = tx.find(A + "bodyPr")
    if body_pr is not None:
        for fit in [c for c in body_pr if etree.QName(c).localname in ("noAutofit", "normAutofit", "spAutoFit")]:
            body_pr.remove(fit)
        etree.SubElement(body_pr, A + "normAutofit")
    first = tx.find(A + "p")
    ppr = first.find(A + "pPr") if first is not None else None
    end_rpr = first.find(A + "endParaRPr") if first is not None else None
    for p in tx.findall(A + "p"):
        tx.remove(p)
    # One notes paragraph per line (blank lines separate paragraphs; "- " list lines stay lines).
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        p = etree.SubElement(tx, A + "p")
        new_ppr = etree.fromstring(etree.tostring(ppr)) if ppr is not None else etree.Element(A + "pPr")
        for old in new_ppr.findall(A + "spcAft"):
            new_ppr.remove(old)
        # 6 pt after each paragraph, so paragraphs stay apart in the notes pane and pages.
        spc = etree.Element(A + "spcAft")
        etree.SubElement(spc, A + "spcPts", val="600")
        # Schema order: lnSpc, spcBef, spcAft, then bullets etc.
        after = [c for c in new_ppr if etree.QName(c).localname in ("lnSpc", "spcBef")]
        new_ppr.insert(new_ppr.index(after[-1]) + 1 if after else 0, spc)
        p.append(new_ppr)
        r = etree.SubElement(p, A + "r")
        rpr = etree.SubElement(r, A + "rPr", lang="en-US", dirty="0")
        if end_rpr is not None:
            for k, v in end_rpr.attrib.items():
                if k not in ("lang", "dirty"):
                    rpr.set(k, v)
        t = etree.SubElement(r, A + "t")
        t.text = " ".join(para.split())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def cmd_apply(args):
    paths = sorted(OUT.glob("*.json")) if not args.decks else [OUT / f"{d}.json" for d in args.decks]
    for path in paths:
        notes = json.loads(path.read_text())
        deck = sdf.Deck(sdf.SLIDES / f"{path.stem}.pptx")
        prs = dr.open_deck(deck.path)
        changed = 0
        for _no, slide in dr.slides(prs):
            text = notes.get(str(slide.slide_id))
            if not text or not slide.has_notes_slide:
                continue
            part = str(slide.notes_slide.part.partname).lstrip("/")
            new = set_notes(deck.data[part], text)
            if new is not None and new != deck.data[part]:
                deck.data[part] = new
                deck.changed = True
                changed += 1
        if deck.changed:
            deck.save()
        print(f"{path.stem}.pptx: notes written on {changed} slide(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--renders", required=True)
    s.add_argument("--decks", nargs="*")
    s.add_argument("--limit", type=int)
    s.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    c = sub.add_parser("collect")
    c.add_argument("--wait", action="store_true")
    a = sub.add_parser("apply")
    a.add_argument("decks", nargs="*")
    args = ap.parse_args()
    {"submit": cmd_submit, "status": cmd_status, "collect": cmd_collect, "apply": cmd_apply}[args.cmd](args)


if __name__ == "__main__":
    main()
