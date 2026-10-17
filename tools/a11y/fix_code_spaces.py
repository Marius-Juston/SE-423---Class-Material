#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Turn the non-breaking spaces in tex4ht's HTML code blocks into plain spaces.

    uv run tools/a11y/fix_code_spaces.py PAGE.html [...]   (rewrites in place)

tex4ht writes every space of a code block (<pre class="fancyvrb">, lstlisting,
verbatim) as U+00A0. Copied into an editor that is not a space: C compilers reject
it ("stray '\\302' in program"), and it also keeps long lines from wrapping on narrow
screens. Plain spaces render the same inside <pre>. Only <pre> blocks change.
(EPUBs get the same fix in epub_repair.py.)
"""

import re
import sys
from pathlib import Path

PRE = re.compile(r"(<pre\b[^>]*>)(.*?)(</pre>)", re.S | re.I)
NBSP = re.compile(r" |&nbsp;|&#160;|&#x0*a0;", re.I)


def fix(text):
    count = 0

    def block(m):
        nonlocal count
        body, n = NBSP.subn(" ", m[2])
        count += n
        return m[1] + body + m[3]

    return PRE.sub(block, text), count


def main():
    total = 0
    for name in sys.argv[1:]:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        new, n = fix(text)
        if n:
            path.write_text(new, encoding="utf-8")
            total += n
    print(f"code blocks: {total} non-breaking space(s) replaced in {len(sys.argv) - 1} page(s)")


if __name__ == "__main__":
    main()
