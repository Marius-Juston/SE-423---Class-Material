#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Describe online (YouTube) videos in the decks from YouTube's own metadata.

    uv run tools/a11y/fix_video_alt.py [--dry-run] [DECK.pptx ...]

A video on a slide is a picture (its poster frame) linked to the video. Videos without
a description get "YouTube video: <title> (<channel>)", looked up with YouTube's public
oEmbed endpoint. Existing descriptions are never changed. Embedded video files have no
such metadata and are left for tools/a11y/draft_alt_text.py and review.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import sync_deck_figures as sdf  # noqa: E402

YOUTUBE_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")


def oembed(video_id):
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    paths = [Path(p).resolve() for p in args.decks] or sdf.decks()
    done = skipped = 0
    for path in paths:
        deck = sdf.Deck(path)
        for no, sid, part in deck.slides():
            x = deck.data[part].decode()
            rels = deck.data[deck.rels_part(part)].decode()
            targets = {
                re.search(r'Id="([^"]+)"', r)[1]: re.search(r'Target="([^"]+)"', r)[1]
                for r in re.findall(r"<Relationship [^>]*>", rels)
            }
            # Back to front, so editing one picture never shifts the positions of the others.
            for m in reversed(list(re.finditer(r"<p:pic>.*?</p:pic>", x, re.S))):
                pic = m[0]
                if not sdf.MEDIA.search(pic) or re.search(r'<p:cNvPr\b[^>]*\bdescr="[^"]+"', pic):
                    continue
                link = re.search(r'<a:videoFile\b[^>]*r:link="(rId\d+)"', pic)
                vid = YOUTUBE_ID.search(targets.get(link[1], "")) if link else None
                info = oembed(vid[1]) if vid else None
                if not info:
                    print(f"skip     {path.name} slide {no}: not a YouTube video (or not found)")
                    skipped += 1
                    continue
                text = f"YouTube video: {info['title']} ({info.get('author_name', 'YouTube')})"
                cid = re.search(r'a16:creationId [^>]*id="(\{[^"]+\})"', pic)
                shape = re.search(r'<p:cNvPr\b[^>]*\bid="(\d+)"', pic)[1]
                p = sdf.Picture(deck, part, no, sid, m.span(), pic)
                p.key = f"{sid}/{cid[1] if cid else 'shape-' + shape}"
                sdf.set_alt(deck, p, text, False)
                print(f"describe {path.name} slide {no}: {text}")
                done += 1
        if deck.changed and not args.dry_run:
            deck.save()
    print(f"{done} video(s) described, {skipped} left for review")


if __name__ == "__main__":
    main()
