#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools", "brotli", "uharfbuzz"]
# ///
"""SE 423 GitHub repo card: a flat isometric diorama of the mechatronics lab.

Two lab partners program the red + green F28379D board at a bench while the
class robot maps its plywood arena with LiDAR and plans a path to the goal.

Everything (including text, converted to outlines) is emitted as plain SVG
paths, so the card renders identically everywhere.

    uv run make_repo_card.py [out.svg]

Fonts: Montserrat + Source Sans 3 (the Illinois brand typefaces, SIL OFL),
fetched once from the @fontsource npm packages into ./ttf.
"""
import io
import math
import sys
import tarfile
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "repo-card.svg"
W, H = 1280, 640

# ------------------------------------------------------------------ palette
BLUE = "#13294B"        # Illini Blue
ORANGE = "#FF5F05"      # Illini Orange
ALTGELD = "#C84113"
ARCHES = "#1D58A7"
INDUSTRIAL = "#1E3877"
CLOUD = "#E8E9EB"

INK = "#0E1E38"
FLOOR = ("#E9EEF5", "#FF5F05", "#C84113")         # top, +y face, +x face
WALL_L = "#D3DCE8"                               # inner face of left wall
WALL_R = "#E4EAF2"                               # inner face of right wall
WALL_TOP = "#F7F9FC"
MAT = "#27324A"
PLY = ("#F2D6A2", "#E1B777", "#C7975A")
OAK = ("#EDBB78", "#D9A05C", "#BC8242")
METAL = ("#DDE2E9", "#B9C2CE", "#98A3B2")
PCB = ("#27A35A", "#1E8A4A", "#176B3A")
LAUNCH = ("#E0233F", "#C8102E", "#9E0B23")
BLACK = ("#3A3F4B", "#262A33", "#1A1D24")
WHITE = ("#FFFFFF", "#E6EAF0", "#C9D0DA")

# ------------------------------------------------------------------ fonts → outlines
FONT_DIR = HERE / "ttf"
_fonts = {}
_NPM = {"montserrat": "https://registry.npmjs.org/@fontsource/montserrat/-/montserrat-5.2.8.tgz",
        "source-sans-3": "https://registry.npmjs.org/@fontsource/source-sans-3/-/source-sans-3-5.2.9.tgz"}


def _fetch_font(name):
    """Download the fontsource tarball and convert the woff2 file to TTF."""
    family = "montserrat" if name.startswith("montserrat") else "source-sans-3"
    with urllib.request.urlopen(_NPM[family]) as resp:
        tar = tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz")
    member = tar.extractfile(f"package/files/{name}.woff2")
    font = TTFont(io.BytesIO(member.read()))
    font.flavor = None
    FONT_DIR.mkdir(exist_ok=True)
    font.save(FONT_DIR / f"{name}.ttf")


def _font(name):
    if name not in _fonts:
        path = FONT_DIR / f"{name}.ttf"
        if not path.exists():
            _fetch_font(name)
        data = path.read_bytes()
        face = hb.Face(data)
        _fonts[name] = (TTFont(path), hb.Font(face), face.upem)
    return _fonts[name]


def text_path(s, x, y, size, font, fill, spacing=0.0, anchor="start", extra=""):
    """Shape `s` with HarfBuzz (kerning, ligatures) and return an SVG <path>."""
    tt, hbf, upem = _font(font)
    buf = hb.Buffer()
    buf.add_str(s)
    buf.guess_segment_properties()
    hb.shape(hbf, buf, {"kern": True, "liga": True})
    scale = size / upem
    gs = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    total = sum(p.x_advance for p in buf.glyph_positions) * scale + spacing * (len(s) - 1)
    if anchor == "middle":
        x -= total / 2
    elif anchor == "end":
        x -= total
    pen = SVGPathPen(gs)
    cx = x
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = order[info.codepoint]
        tp = TransformPen(pen, (scale, 0, 0, -scale, cx + pos.x_offset * scale, y - pos.y_offset * scale))
        gs[name].draw(tp)
        cx += pos.x_advance * scale + spacing
    return f'<path d="{pen.getCommands()}" fill="{fill}"{extra}/>', total


MONT = {w: f"montserrat-latin-{w}-normal" for w in (600, 700, 800, 900)}
SANS = {w: f"source-sans-3-latin-{w}-normal" for w in (400, 600, 700)}

# ------------------------------------------------------------------ isometric engine
C, S = math.cos(math.pi / 6), 0.5
K = 1.3                    # world → screen scale
OX, OY = 800, 198          # screen position of world origin (back corner of the room)


def P(x, y, z=0.0):
    return (OX + (x - y) * C * K, OY + ((x + y) * S - z) * K)


def pts(*ps):
    return " ".join(f"{a:.1f},{b:.1f}" for a, b in (P(*p) for p in ps))


def poly(points, fill, extra=""):
    return f'<polygon points="{pts(*points)}" fill="{fill}"{extra}/>'


def box(x, y, z, dx, dy, dz, cols, extra=""):
    """Axis aligned box; draws the three faces visible to the camera."""
    top, fy, fx = cols
    x1, y1, z1 = x + dx, y + dy, z + dz
    return "".join((
        poly([(x, y1, z), (x1, y1, z), (x1, y1, z1), (x, y1, z1)], fy, extra),
        poly([(x1, y, z), (x1, y1, z), (x1, y1, z1), (x1, y, z1)], fx, extra),
        poly([(x, y, z1), (x1, y, z1), (x1, y1, z1), (x, y1, z1)], top, extra),
    ))


def cyl(cx, cy, z0, z1, r, top, side_l, side_r, extra=""):
    """Vertical cylinder (side shaded with a left→right gradient)."""
    rx, ry = r * C * math.sqrt(2) * K, r * S * math.sqrt(2) * K
    (tx, ty), (bx, by) = P(cx, cy, z1), P(cx, cy, z0)
    gid = f"cy{abs(hash((cx, cy, z0, z1, r))) % 10**8}"
    g = (f'<linearGradient id="{gid}" x1="{tx-rx:.1f}" x2="{tx+rx:.1f}" y1="0" y2="0" gradientUnits="userSpaceOnUse">'
         f'<stop offset="0" stop-color="{side_l}"/><stop offset="1" stop-color="{side_r}"/></linearGradient>')
    side = (f'<path d="M{tx-rx:.1f} {ty:.1f}V{by:.1f}A{rx:.1f} {ry:.1f} 0 0 0 {tx+rx:.1f} {by:.1f}V{ty:.1f}Z" '
            f'fill="url(#{gid})"{extra}/>')
    cap = f'<ellipse cx="{tx:.1f}" cy="{ty:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{top}"{extra}/>'
    return g + side + cap


def m_top(x0, y0, z, s=1.0):
    """Affine map: local (u→+x, v→+y) on a horizontal plane."""
    s *= K
    ex, ey = P(x0, y0, z)
    return f"matrix({C*s:.4f} {S*s:.4f} {-C*s:.4f} {S*s:.4f} {ex:.2f} {ey:.2f})"


def m_top_uy(x0, y0, z, s=1.0):
    """Horizontal plane with local u→+y, v→−x (reads naturally for things lying along y)."""
    s *= K
    ex, ey = P(x0, y0, z)
    return f"matrix({-C*s:.4f} {S*s:.4f} {-C*s:.4f} {-S*s:.4f} {ex:.2f} {ey:.2f})"


def m_yface(y, x0, ztop, s=1.0):
    """Plane y=const (faces +y); local u→+x, w→down."""
    s *= K
    ex, ey = P(x0, y, ztop)
    return f"matrix({C*s:.4f} {S*s:.4f} 0 {s:.4f} {ex:.2f} {ey:.2f})"


def m_xface(x, y0, ztop, s=1.0):
    """Plane x=const (faces +x); local u→−y (reads left→right), w→down."""
    s *= K
    ex, ey = P(x, y0, ztop)
    return f"matrix({C*s:.4f} {-S*s:.4f} 0 {s:.4f} {ex:.2f} {ey:.2f})"


out = []
add = out.append
defs = []


# ==================================================================== v3 scene
# Composition notes
#  * 2:1 banner, text column on the left (~40%), diorama on the right (~60%).
#  * Value groups: dark = navy background + arena mat, mid = walls/floor/plywood,
#    light = whiteboard, wall tops, text.  The lightest-vs-darkest contrast is
#    reserved for the focal points: "SE 423" and the robot on the dark mat.
#  * Illini Orange is the ~10% accent and is always opaque (no transparent
#    orange over navy, which turns brown).
#  * Eye path (Z): eyebrow → "SE 423" → robot → students → tagline.  The robot
#    faces +y, i.e. towards the text and the students; both students look at it.

K = 1.2
OX, OY = 832, 214

WALL_L = "#9FB4D1"          # left wall inner face (mid value)
WALL_R = "#B7C7DD"          # right wall inner face
WALL_TOP = "#EEF3F9"
FLOOR_TOP = "#CAD5E4"
SLAB = ("#CAD5E4", "#24457A", "#1A3561")
SHADOW_FLOOR = "#AFBCCF"    # pre-mixed cast shadow on the floor
SHADOW_MAT = "#1B2437"      # pre-mixed cast shadow on the mat
MAT = "#27324A"
CELL_SEEN = "#35456A"       # A* closed set (pre-mixed, opaque)
LAUNCH = ("#C42330", "#A51C1C", "#7F1414")   # darker red: separates from green for CVD
PCB = ("#3DBE72", "#2E9E5B", "#237A46")      # lighter green
HOODIE_B = ("#F1F4F9", "#D3DBE7")

RX, RY = 330, 190
ROOM_H = 104
ARENA = (130, 12, 324, 186)
WALLS = {
    "back": (130, 12, 194, 6),
    "left": (130, 18, 6, 168),
    "baffle": (136, 110, 80, 6),
}
CRATE = (266, 58, 26, 26)
ROBOT = (178, 52)
BALL_O = (166, 160)
BALL_B = (298, 150)
WALL_H = 20

defs = []
out = []
add = out.append


def prism(poly2, z0, z1, top, light, dark, extra=""):
    """Extrude a convex polygon (CCW in world x/y); shade side faces by normal."""
    faces = []
    n = len(poly2)
    for i in range(n):
        (x0, y0), (x1, y1) = poly2[i], poly2[(i + 1) % n]
        nx, ny = (y1 - y0), -(x1 - x0)
        faces.append(((x0, y0), (x1, y1), nx, ny))
    # make normals point away from the centroid
    cx = sum(p[0] for p in poly2) / n
    cy = sum(p[1] for p in poly2) / n
    res = []
    for (a, b, nx, ny) in faces:
        mx, my = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        if nx * mx + ny * my < 0:
            nx, ny = -nx, -ny
        if nx + ny <= 1e-6:                      # faces away from the camera
            continue
        L = math.hypot(nx, ny)
        col = _mix(light, dark, (nx / L) ** 2 if ny >= 0 else 1.0)
        res.append(poly([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], col, extra))
    res.append(poly([(x, y, z1) for x, y in poly2], top, extra))
    return "".join(res)


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def disc_x(x, yc, zc, r, fill):
    """Circle lying in the plane x = const (e.g. a wheel on a +x axle)."""
    return f'<g transform="{m_xface(x, 0, 0)}"><circle cx="{-yc:.2f}" cy="{-zc:.2f}" r="{r}" fill="{fill}"/></g>'


def ell(x, y, z, r, fill, extra=""):
    """Horizontal circle of world radius r (an ellipse on screen)."""
    sx, sy = P(x, y, z)
    return (f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{r*C*math.sqrt(2)*K:.1f}" ry="{r*S*math.sqrt(2)*K:.1f}" '
            f'fill="{fill}"{extra}/>')


# ------------------------------------------------------------------ background
add(f'<rect width="{W}" height="{H}" fill="{BLUE}"/>')
defs.append('<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
            '<circle cx="2" cy="2" r="1.1" fill="#1F3A66"/></pattern>')
add(f'<rect width="{W}" height="{H}" fill="url(#dots)"/>')
# large soft backdrop disc (opaque, concentric steps instead of alpha glow)


# ------------------------------------------------------------------ room shell
add(poly([(8, 8, -30), (RX + 10, 8, -30), (RX + 10, RY + 10, -30), (8, RY + 10, -30)], "#0F2344"))   # cast shadow
add(box(0, 0, -18, RX, RY, 18, SLAB))
add(poly([(0, RY, -4), (RX, RY, -4), (RX, RY, 0), (0, RY, 0)], ORANGE))          # orange floor-edge band
add(poly([(RX, 0, -4), (RX, RY, -4), (RX, RY, 0), (RX, 0, 0)], ALTGELD))
WT = 8
add(poly([(0, 0, 0), (0, RY, 0), (0, RY, ROOM_H), (0, 0, ROOM_H)], WALL_L))
add(poly([(0, 0, 0), (RX, 0, 0), (RX, 0, ROOM_H), (0, 0, ROOM_H)], WALL_R))
add(poly([(-WT, -WT, ROOM_H), (-WT, RY, ROOM_H), (0, RY, ROOM_H), (0, 0, ROOM_H), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], WALL_TOP))
add(poly([(-WT, RY, -18), (0, RY, -18), (0, RY, ROOM_H), (-WT, RY, ROOM_H)], "#DCE4EF"))
add(poly([(RX, -WT, -18), (RX, 0, -18), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], "#C3CFDF"))
# skirting boards
add(poly([(0.01, 0, 0), (0.01, RY, 0), (0.01, RY, 5), (0.01, 0, 5)], "#8398B7"))
add(poly([(0, 0.01, 0), (RX, 0.01, 0), (RX, 0.01, 5), (0, 0.01, 5)], "#9CAECA"))

# --- whiteboard: the two ideas the whole course keeps returning to (PWM → PID)
wb = []
wb.append('<rect x="0" y="0" width="128" height="62" rx="3" fill="#FFFFFF"/>')
wb.append('<rect x="0" y="58" width="128" height="4" fill="#DDE4EE"/>')
wb.append(f'<g fill="none" stroke="{BLUE}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
          '<path d="M10 20h14"/><circle cx="29" cy="20" r="5"/><path d="M34 20h10"/>'
          '<rect x="44" y="10" width="36" height="20" rx="3"/><path d="M80 20h26M100 20v16H29v-11"/>'
          '<path d="M102 15l5 5-5 5"/></g>')
t, _ = text_path("PID", 62, 25.5, 12, MONT[800], BLUE, anchor="middle"); wb.append(t)
wb.append(f'<path d="M10 50h12v-10h12v10h12v-10h12v10h12v-10h12v10h12" fill="none" stroke="{ORANGE}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
add(f'<g transform="{m_yface(0, 196, 92)}">{"".join(wb)}</g>')

# ------------------------------------------------------------------ arena floor
ax0, ay0, ax1, ay1 = ARENA
add(poly([(ax0, ay0, .2), (ax1, ay0, .2), (ax1, ay1, .2), (ax0, ay1, .2)], MAT))

# A* on the arena grid (Lecture 18): closed set + final path, computed for real
G = 16
cols, rows = int((ax1 - 136) // G), int((ay1 - 18) // G)
gx0, gy0 = 136, 18


def blocked(i, j):
    x, y = gx0 + i * G, gy0 + j * G
    for (wx, wy, wdx, wdy) in list(WALLS.values()) + [CRATE]:
        if x < wx + wdx + 4 and x + G > wx - 4 and y < wy + wdy + 4 and y + G > wy - 4:
            return True
    return False


def cell_of(p):
    return (int((p[0] - gx0) // G), int((p[1] - gy0) // G))


def astar(start, goal):
    import heapq
    oct_h = lambda a: (max(abs(a[0] - goal[0]), abs(a[1] - goal[1])) + (math.sqrt(2) - 1) * min(abs(a[0] - goal[0]), abs(a[1] - goal[1])))
    openq = [(oct_h(start), 0.0, start)]
    came, gcost, closed = {}, {start: 0.0}, []
    while openq:
        _, g, cur = heapq.heappop(openq)
        if cur in closed:
            continue
        closed.append(cur)
        if cur == goal:
            break
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == dj == 0:
                    continue
                nb = (cur[0] + di, cur[1] + dj)
                if not (0 <= nb[0] < cols and 0 <= nb[1] < rows) or blocked(*nb):
                    continue
                if di and dj and (blocked(cur[0] + di, cur[1]) or blocked(cur[0], cur[1] + dj)):
                    continue
                ng = g + (math.sqrt(2) if di and dj else 1)
                if ng < gcost.get(nb, 1e9):
                    gcost[nb] = ng
                    came[nb] = cur
                    heapq.heappush(openq, (ng + oct_h(nb), ng, nb))
    path = [goal]
    while path[-1] in came:
        path.append(came[path[-1]])
    return path[::-1], closed


start_c = cell_of((ROBOT[0], ROBOT[1] + 30))
goal_c = cell_of(BALL_O)
apath, aclosed = astar(start_c, goal_c)
for (i, j) in aclosed:
    x, y = gx0 + i * G, gy0 + j * G
    add(poly([(x + 1.5, y + 1.5, .3), (x + G - 1.5, y + 1.5, .3), (x + G - 1.5, y + G - 1.5, .3), (x + 1.5, y + G - 1.5, .3)], CELL_SEEN))
centers = [(gx0 + (i + .5) * G, gy0 + (j + .5) * G) for i, j in apath]
dpath = "M" + "L".join(f"{P(x, y, .5)[0]:.1f} {P(x, y, .5)[1]:.1f}" for x, y in centers)
add(f'<path d="{dpath}" fill="none" stroke="{ORANGE}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
for x, y in centers[1:-1]:
    q = P(x, y, .5)
    add(f'<circle cx="{q[0]:.1f}" cy="{q[1]:.1f}" r="2.6" fill="{ORANGE}"/>')
# goal ring around the orange ball
add(ell(*BALL_O, .6, 13, "none", f' stroke="{ORANGE}" stroke-width="2.4"'))

# ------------------------------------------------------------------ people
SKIN_A, SKIN_A_D = "#8A5536", "#6E3F25"      # deep tone
SKIN_B, SKIN_B_D = "#E3AE85", "#C98F66"      # medium tone


def ik(sx, sy, hx, hy, l1, l2, bend=1):
    dx, dy = hx - sx, hy - sy
    dist = max(1e-3, min(math.hypot(dx, dy), l1 + l2 - 0.01))
    a = math.atan2(dy, dx)
    cosb = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    b = math.acos(max(-1, min(1, cosb)))
    ea = a + bend * b
    return sx + l1 * math.cos(ea), sy + l1 * math.sin(ea)


def person(fx, fy, p):
    """3/4 view, facing screen-right. ~5.6 heads tall. Local units → scaled by K."""
    g = []
    top, top_d = p["top"]
    pants, pants_d = p["pants"]
    skin, skin_d = p["skin"]
    # legs + shoes
    g.append(f'<path d="M-10 -52H0L-1.5 -6H-9Z" fill="{pants_d}"/>')
    g.append(f'<path d="M-1 -52H10L9 -5H0.5Z" fill="{pants}"/>')
    g.append('<rect x="-11" y="-7" width="13" height="7" rx="3.5" fill="#C9D2DE"/>')
    g.append(f'<rect x="0" y="-6.5" width="16" height="6.5" rx="3.2" fill="{p.get("shoe", "#FFFFFF")}"/>')
    g.append('<rect x="0" y="-2" width="16" height="2" rx="1" fill="#9AA7B8"/>')
    # hoodie torso with shoulders
    g.append(f'<path d="M-13 -50C-15 -64 -16 -79 -12 -85Q-9 -90 -2 -90H7Q13 -90 15.5 -85C18 -78 17 -64 16 -50Z" fill="{top}"/>')
    g.append(f'<path d="M-13 -50C-15 -64 -16 -79 -12 -85Q-9 -90 -3 -90C-8 -80 -8 -62 -6 -50Z" fill="{top_d}"/>')
    g.append(f'<rect x="-13" y="-55" width="29" height="6" rx="2.5" fill="{top_d}"/>')
    g.append(f'<path d="M0 -66H13L11.5 -58H1.5Z" fill="{top_d}"/>')                 # kangaroo pocket
    g.append(f'<path d="M-7 -89C-11 -97 6 -99 9 -90Z" fill="{top_d}"/>')              # hood
    if p.get("strings"):
        g.append('<path d="M4.5 -87v9M8.5 -87v7" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>')
    # neck + head
    g.append(f'<rect x="-2" y="-96" width="7" height="8" fill="{skin_d}"/>')
    g.append(f'<circle cx="2.5" cy="-104" r="10.5" fill="{skin}"/>')
    g.append(f'<ellipse cx="-4.2" cy="-103" rx="2.4" ry="3.2" fill="{skin_d}"/>')
    g.append(p["hair"])
    # face: 3/4 right, looking toward the robot
    g.append(f'<path d="M4 -108.6l3 -.6M9.6 -109.2l2.6 .2" stroke="{p["brow"]}" stroke-width="1.3" stroke-linecap="round"/>')
    g.append(f'<ellipse cx="6" cy="-105" rx="1.25" ry="1.7" fill="{INK}"/><ellipse cx="11.2" cy="-105" rx="1.1" ry="1.6" fill="{INK}"/>')
    g.append(f'<path d="M12.6 -103.5q1.4 1.8 -.4 2.6" fill="none" stroke="{skin_d}" stroke-width="1.2" stroke-linecap="round"/>')
    g.append(f'<path d="M6.5 -99q2.8 2.2 5.4 .2" fill="none" stroke="{INK}" stroke-width="1.3" stroke-linecap="round"/>')
    if p.get("glasses"):
        g.append(f'<g fill="none" stroke="{INK}" stroke-width="1.1"><rect x="3" y="-107.8" width="5.6" height="4.8" rx="1.6"/><rect x="9.6" y="-107.8" width="4.2" height="4.6" rx="1.4"/><path d="M8.6 -106h1M3 -106l-6 -1"/></g>')
    return f'<g transform="translate({fx:.1f} {fy:.1f}) scale({K})">{"".join(g)}</g>'


def arm(fx, fy, shoulder, hand, p, l1=21, l2=20, bend=1, back=False, point=None):
    """Sleeve (upper arm + forearm) with cuff and mitten hand, solved with 2-bone IK."""
    top, top_d = p["top"]
    skin, _ = p["skin"]
    sx, sy = fx + shoulder[0] * K, fy + shoulder[1] * K
    hx, hy = hand
    ex, ey = ik(sx, sy, hx, hy, l1 * K, l2 * K, bend)
    col = top_d if back else top
    ang = math.atan2(hy - ey, hx - ex)
    cx_, cy_ = hx - math.cos(ang) * 4.5 * K, hy - math.sin(ang) * 4.5 * K
    s = (f'<path d="M{sx:.1f} {sy:.1f}L{ex:.1f} {ey:.1f}" stroke="{col}" stroke-width="{9*K:.1f}" stroke-linecap="round"/>'
         f'<path d="M{ex:.1f} {ey:.1f}L{cx_:.1f} {cy_:.1f}" stroke="{col}" stroke-width="{7.6*K:.1f}" stroke-linecap="round"/>'
         f'<circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="{4.1*K:.1f}" fill="{top_d}"/>')
    deg = math.degrees(ang)
    hand_svg = (f'<g transform="translate({hx:.1f} {hy:.1f}) rotate({deg:.1f}) scale({K})">'
                f'<ellipse cx="0.5" cy="0" rx="4.4" ry="3.4" fill="{skin}"/>'
                f'<ellipse cx="-0.5" cy="-3" rx="1.6" ry="1.2" fill="{skin}"/>')
    if point:
        hand_svg += f'<rect x="2" y="-1.2" width="6.5" height="2.4" rx="1.2" fill="{skin}"/>'
    hand_svg += '</g>'
    return s + hand_svg


HAIR_A = ('<circle cx="-5" cy="-121" r="7.5" fill="#1B120E"/>'
          '<path d="M-8.5 -101C-12 -113 -4 -118 5 -117C11 -116 14 -111 13.5 -107C9 -111 3 -112 -1 -109C-3 -106 -5 -103 -8.5 -101Z" fill="#1B120E"/>'
          '<rect x="-7" y="-116.5" width="9" height="3" rx="1.5" fill="#FF5F05"/>')
HAIR_B = ('<path d="M-8.8 -99C-13 -110 -8 -117 2 -117C10 -117 15 -112 13.5 -107.5C10 -110 6 -110.5 3 -108.5C1 -106 -3 -104 -5 -99Z" fill="#3B2A1E"/>'
          '<path d="M2 -117C6 -120 12 -117 13.5 -112" fill="none" stroke="#3B2A1E" stroke-width="3" stroke-linecap="round"/>')
STU_A = dict(top=(ORANGE, ALTGELD), pants=("#1D58A7", "#1E3877"), skin=(SKIN_A, SKIN_A_D), hair=HAIR_A,
             brow="#1B120E", strings=True, shoe="#FFFFFF")
STU_B = dict(top=HOODIE_B, pants=("#2B3F63", "#1E2E4B"), skin=(SKIN_B, SKIN_B_D), hair=HAIR_B,
             brow="#3B2A1E", glasses=True, shoe="#FFFFFF")

A_POS, B_POS = (24, 150), (24, 84)
BENCH = (38, 58, 54, 122, 44)                 # x, y, depth, length, height
bx, by, bdx, bdy, bh = BENCH
BT = bh

fa, fb = P(*A_POS), P(*B_POS)
# soft cast shadows (pre-mixed floor shadow colour)
for fx_, fy_ in (A_POS, B_POS):
    add(ell(fx_ + 2, fy_ + 2, .1, 11, SHADOW_FLOOR))
add(person(*fb, STU_B))
add(person(*fa, STU_A))

# ------------------------------------------------------------------ workbench
OAKC = ("#EDBB78", "#D9A05C", "#BC8242")
METALC = ("#E3E8EE", "#BCC6D2", "#9CA8B8")
add(poly([(bx + 4, by + 4, .1), (bx + bdx + 8, by + 4, .1), (bx + bdx + 8, by + bdy + 8, .1), (bx + 4, by + bdy + 8, .1)], SHADOW_FLOOR))
for lx, ly in ((bx + 3, by + 3), (bx + bdx - 7, by + 3), (bx + 3, by + bdy - 7), (bx + bdx - 7, by + bdy - 7)):
    add(box(lx, ly, 0, 4, 4, bh - 5, METALC))
add(box(bx + 3, by + 3, 12, bdx - 6, bdy - 6, 3, METALC))
add(box(bx + 12, by + 70, 15, 30, 36, 18, ("#5B6B84", "#4A5970", "#3B475B")))     # bench power supply
add(box(bx, by, bh - 5, bdx, bdy, 5, OAKC))

# ---- general affine map for any plane: origin + u·uvec + w·wvec (world vectors)
def m_plane(origin, uvec, wvec):
    ox_, oy_ = P(*origin)
    ux, uy = P(origin[0] + uvec[0], origin[1] + uvec[1], origin[2] + uvec[2])
    wx, wy = P(origin[0] + wvec[0], origin[1] + wvec[1], origin[2] + wvec[2])
    return f"matrix({ux-ox_:.4f} {uy-oy_:.4f} {wx-ox_:.4f} {wy-oy_:.4f} {ox_:.2f} {oy_:.2f})"


def wire3d(p0, p1, lift, col, w=1.7):
    """Jumper wire: a quadratic arc in 3-D between two pins, lifted by `lift`."""
    (x0, y0, z0), (x1, y1, z1) = p0, p1
    mx, my, mz = (x0 + x1) / 2, (y0 + y1) / 2, max(z0, z1) + lift
    pts_ = []
    for i in range(17):
        t = i / 16
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t * t * y1
        z = (1 - t) ** 2 * z0 + 2 * (1 - t) * t * mz + t * t * z1
        pts_.append(P(x, y, z))
    d = "M" + "L".join(f"{a:.1f} {b:.1f}" for a, b in pts_)
    return f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w*K:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'


# ---- laptop: keyboard towards the student (low x), lid hinged on the far edge and
#      tilted back, so we see the lid's aluminium back; B's hands go behind it.
lx0, ly0 = bx + 10, by + 7
LW_, LL_ = 26, 34                      # depth (x) and width (y) of the base
ALU = ("#E3E8EE", "#C3CBD6", "#A6B0BE")
add(box(lx0, ly0, BT, LW_, LL_, 1.8, ALU))
kb = (f'<rect x="{LL_/2-6}" y="2.5" width="12" height="6" rx="1.2" fill="#CDD4DE"/>'
      f'<rect x="3" y="10" width="{LL_-6}" height="11" rx="1.5" fill="#2F3440"/>')
add(f'<g transform="{m_plane((lx0 + 1, ly0 + LL_, BT + 1.8), (0, -1, 0), (1, 0, 0))}">{kb}</g>')


def laptop_lid():
    h, z0 = lx0 + LW_ - 3, BT + 1.8
    tilt, L, T = math.radians(16), 23, 1.4
    dx, dz = L * math.sin(tilt), L * math.cos(tilt)
    y0, y1 = ly0 + 1, ly0 + LL_ - 1
    s = []
    s.append(poly([(h, y1, z0), (h + T, y1, z0), (h + T + dx, y1, z0 + dz), (h + dx, y1, z0 + dz)], "#EEF2F6"))      # side edge
    s.append(poly([(h + T, y0, z0), (h + T, y1, z0), (h + T + dx, y1, z0 + dz), (h + T + dx, y0, z0 + dz)], "#C7CFDA"))  # back
    s.append(poly([(h + dx, y0, z0 + dz), (h + T + dx, y0, z0 + dz), (h + T + dx, y1, z0 + dz), (h + dx, y1, z0 + dz)], "#F4F7FA"))
    # stickers on the lid back (plane mapped so text reads left → right)
    org = (h + T + dx, y1, z0 + dz)
    uvec, wvec = (0, -1, 0), (-math.sin(tilt), 0, -math.cos(tilt))
    st = (f'<circle cx="10" cy="8" r="4.6" fill="{ORANGE}"/>'
          f'<rect x="17" y="12" width="12" height="5" rx="1.2" fill="{BLUE}"/>'
          f'<rect x="6" y="15" width="7" height="4" rx="1" fill="#F2C14E"/>')
    s.append(f'<g transform="{m_plane(org, uvec, wvec)}">{st}</g>')
    return "".join(s)


# ---- the red + green board, modelled in 3-D:
#      SE 423 breakout (green) with the TI LaunchPad F28379D (red) standing on its headers.
BX0, BY0, BW_, BL_ = bx + 6, by + 44, 42, 74       # footprint (x depth, y length)
BZ = BT
PCB_T = 1.6


def board3d():
    s = []
    z1 = BZ + PCB_T
    s.append(box(BX0, BY0, BZ, BW_, BL_, PCB_T, PCB))
    # flat details on the breakout (traces, holes, silkscreen)
    flat = []
    flat.append(f'<rect x="1.5" y="1.5" width="{BL_-3}" height="{BW_-3}" rx="2" fill="none" stroke="{PCB[0]}" stroke-width="1.2"/>')
    for d_ in ("M6 8h10l4 4h6", "M6 34h14l4-4h8", "M60 36h8v-10", "M50 6h14"):
        flat.append(f'<path d="{d_}" fill="none" stroke="#5FD393" stroke-width="0.9" stroke-linecap="round"/>')
    for hx, hy in ((4, 4), (BL_ - 4, 4), (4, BW_ - 4), (BL_ - 4, BW_ - 4)):
        flat.append(f'<circle cx="{hx}" cy="{hy}" r="2.2" fill="#F2C14E"/><circle cx="{hx}" cy="{hy}" r="1" fill="{PCB[2]}"/>')
    t_, _ = text_path("SE 423", 20, 39.6, 4.4, MONT[800], "#FFFFFF", spacing=0.4)
    flat.append(t_)
    # plane: u along −y from the far end (reads left→right on screen), w along −x
    add_flat = f'<g transform="{m_plane((BX0, BY0 + BL_, z1 + .01), (0, -1, 0), (1, 0, 0))}">{"".join(flat)}</g>'
    s.append(add_flat)

    # serial DB-9 at the back end, JST + buzzer + IMU on the sides
    s.append(box(BX0 + 14, BY0 + 1, z1, 14, 5, 5, ("#E3E8EE", "#C3CBD6", "#A6B0BE")))
    s.append(cyl(BX0 + 6, BY0 + 10, z1, z1 + 3, 3.2, "#3A3F4B", "#2A2E36", "#15171C"))
    # female headers on the breakout that the LaunchPad plugs into
    LX0, LY0, LWd, LLn = BX0 + 10, BY0 + 16, 22, 44
    for hx in (LX0 + 1, LX0 + LWd - 4):
        s.append(box(hx, LY0 + 3, z1, 3, LLn - 6, 5.5, ("#3A3F4B", "#262A33", "#1A1D24")))
    lz = z1 + 5.5
    # LaunchPad PCB
    s.append(box(LX0, LY0, lz, LWd, LLn, 1.4, LAUNCH))
    lt = lz + 1.4
    # silkscreen edge (non-colour cue) + labels on the LaunchPad top
    lp = (f'<rect x="1" y="1" width="{LLn-2}" height="{LWd-2}" rx="1.4" fill="none" stroke="#F4F4F4" stroke-width="0.8"/>'
          f'<circle cx="{LLn-8}" cy="8" r="1.3" fill="#FF6B6B"/><circle cx="{LLn-8}" cy="12" r="1.3" fill="#8EC5FF"/>')
    s.append(f'<g transform="{m_plane((LX0, LY0 + LLn, lt + .01), (0, -1, 0), (1, 0, 0))}">{lp}</g>')
    # USB connector (debug) overhanging the back end, male headers, MCU, reset button
    s.append(box(LX0 + 8, LY0 - 3, lt, 6, 6, 2.6, ("#F1F4F8", "#CDD4DE", "#AAB4C2")))
    for hx in (LX0 + 1.5, LX0 + LWd - 4):
        s.append(box(hx, LY0 + 6, lt, 2.5, LLn - 10, 2.4, ("#3A3F4B", "#262A33", "#1A1D24")))
    s.append(box(LX0 + 8, LY0 + 20, lt, 8, 8, 1.2, ("#2F333C", "#22252C", "#17191E")))
    s.append(box(LX0 + 16, LY0 + 8, lt, 3, 3, 1.4, ("#F4F4F4", "#DADADA", "#BDBDBD")))
    # front end: green screw terminals, white JST, blue IMU breakout
    for i in range(3):
        s.append(box(BX0 + 4 + i * 6, BY0 + BL_ - 8, z1, 5, 5, 4, ("#8FE0B0", "#5CC98A", "#3FA86C")))
    s.append(box(BX0 + BW_ - 11, BY0 + BL_ - 12, z1, 7, 8, 4, ("#FFFFFF", "#EDEDE8", "#D4D4CC")))
    s.append(box(BX0 + BW_ - 10, BY0 + 6, z1, 7, 7, 1.2, ("#2F6BC4", "#1D58A7", "#133F7C")))
    # jumper wires arcing from the LaunchPad headers to the breakout
    s.append(wire3d((LX0 + 3, LY0 + 38, lt + 2.4), (BX0 + 7, BY0 + BL_ - 6, z1 + 4), 9, "#FFD23F"))
    s.append(wire3d((LX0 + LWd - 3, LY0 + 30, lt + 2.4), (BX0 + BW_ - 7, BY0 + BL_ - 8, z1 + 4), 7, "#4F8BFF"))
    s.append(wire3d((LX0 + LWd - 3, LY0 + 10, lt + 2.4), (BX0 + BW_ - 7, BY0 + 9, z1 + 1.2), 6, "#FF6B6B"))
    return "".join(s)


add(board3d())
# USB cable: LaunchPad debug port → laptop
c0 = P(bx + 6 + 10 + 11, by + 44 + 16 - 3, BT + PCB_T + 5.5 + 2.6)
c1 = P(lx0 + 14, ly0 + LL_, BT + 1)
add(f'<path d="M{c0[0]:.1f} {c0[1]:.1f}C{c0[0]-2:.1f} {c0[1]-10:.1f} {c1[0]+10:.1f} {c1[1]+6:.1f} {c1[0]:.1f} {c1[1]:.1f}" fill="none" stroke="#3B4252" stroke-width="{2*K:.1f}" stroke-linecap="round"/>')

# arms: B types (hands on the keyboard, behind the lid), A rests a hand on the bench
# and points at the robot
hb1 = P(lx0 + 13, ly0 + 11, BT + 3)
hb2 = P(lx0 + 13, ly0 + 23, BT + 3)
add(arm(*fb, (-4, -85), hb1, STU_B, bend=-1, back=True))
add(arm(*fb, (10, -85), hb2, STU_B, bend=-1))
add(laptop_lid())
ha = P(bx + 3, A_POS[1] + 12, BT + 1)
add(arm(*fa, (-6, -85), ha, STU_A, l1=20, l2=19, bend=-1, back=True))
lid_pt = P(ROBOT[0], ROBOT[1] + 10, 80)
sh = (fa[0] + 11 * K, fa[1] - 85 * K)
ang = math.atan2(lid_pt[1] - sh[1], lid_pt[0] - sh[0])
pa = (sh[0] + math.cos(ang) * 38 * K, sh[1] + math.sin(ang) * 38 * K)
add(arm(*fa, (11, -85), pa, STU_A, l1=21, l2=19, bend=-1, point=True))

# ------------------------------------------------------------------ arena objects (back → front)
PLY = ("#F2D6A2", "#E1B777", "#C7975A")


def ply_wall(key):
    x, y, dx, dy = WALLS[key]
    return box(x, y, 0, dx, dy, WALL_H, PLY)


add(ply_wall("back"))
# AprilTag on the back wall (faces +y)
tag = ['<rect x="0" y="0" width="16" height="16" fill="#FFFFFF"/><rect x="2" y="2" width="12" height="12" fill="#111"/>']
for (i, j) in ((1, 1), (3, 1), (2, 2), (1, 3), (4, 3), (3, 4), (2, 4)):
    tag.append(f'<rect x="{2+i*2}" y="{2+j*2}" width="2" height="2" fill="#FFFFFF"/>')
add(f'<g transform="{m_yface(18, 238, 18)}">{"".join(tag)}</g>')
add(ply_wall("left"))

# --- LiDAR (URG-04LX style 240° fan, centred on the heading +y), ray-cast for real
segs = []


def rect_segs(x, y, dx, dy):
    a, b, c, d = (x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy)
    return [(a, b), (b, c), (c, d), (d, a)]


for (x, y, dx, dy) in WALLS.values():
    segs += rect_segs(x, y, dx, dy)
segs += rect_segs(*CRATE)
segs += [((0, 0), (RX, 0)), ((0, 0), (0, RY))]
edge_segs = [((ax1, 0), (ax1, ay1)), ((0, ay1), (ax1, ay1))]


def cast(ox, oy, a, rmax):
    dx, dy = math.cos(a), math.sin(a)
    best = rmax
    for (x1, y1), (x2, y2) in segs:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
        u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        if t > 0 and 0 <= u <= 1 and t < best:
            best = t
    return best


LID = (ROBOT[0], ROBOT[1] + 16)
rays, hits = [], []
for k in range(0, 33):
    a = math.pi / 2 + math.radians(-120 + k * 7.5)
    r = cast(*LID, a, 120)
    segs_all, segs[:] = segs[:], segs + edge_segs
    r_edge = cast(*LID, a, 120)
    segs[:] = segs_all
    rr = min(r, r_edge)
    hx, hy = LID[0] + rr * math.cos(a), LID[1] + rr * math.sin(a)
    rays.append((hx, hy))
    if r < 120 and r <= r_edge:
        hits.append((hx, hy))
lp = P(*LID, .6)
rp = "".join(f"M{lp[0]:.1f} {lp[1]:.1f}L{P(x, y, .6)[0]:.1f} {P(x, y, .6)[1]:.1f}" for x, y in rays)
add(f'<path d="{rp}" stroke="#6A5260" stroke-width="1"/>')      # opaque, pre-mixed orange-on-mat


def hits_where(sel):
    for hx, hy in hits:
        if sel(hx + hy):
            q = P(hx, hy, 8)
            add(f'<circle cx="{q[0]:.1f}" cy="{q[1]:.1f}" r="2.2" fill="{ORANGE}"/>')


# ---- the robot (heading +y), modelled on the SE 423 robot car
def robot(rx, ry):
    g = []
    g.append(ell(rx, ry + 4, .4, 36, SHADOW_MAT))
    # mocap frame at the back
    for xx in (rx - 25, rx + 22):
        g.append(box(xx, ry - 30, 24, 3, 3, 82, METALC))
    YEL = ("#F0F76A", "#E4F04B", "#C7D23A")
    g.append(box(rx - 31, ry - 31.5, 106, 62, 5, 6, ("#3A3F4B", "#262A33", "#1A1D24")))
    g.append(box(rx - 31.2, ry - 31.7, 106, 12, 5.4, 6.2, YEL))
    g.append(box(rx + 19, ry - 31.7, 106, 12, 5.4, 6.2, YEL))
    balls = [(rx - 20, ry - 29, 112, 128), (rx + 4, ry - 29, 112, 136), (rx + 24, ry - 29, 112, 124)]
    for bx_, by_, z0, z1 in balls:
        a_, b_ = P(bx_, by_, z0), P(bx_, by_, z1)
        g.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#8C97A7" stroke-width="2"/>')
    a_, b_ = P(rx - 31, ry - 29, 110), P(rx - 46, ry - 26, 114)
    g.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#8C97A7" stroke-width="2"/>')
    ball_pts = [P(bx_, by_, z1) for bx_, by_, _, z1 in balls] + [b_]
    # far wheel (−x side) then chassis then near wheel (+x side)
    g.append(disc_x(rx - 26, ry - 10, 13, 13, "#1A1C22"))
    g.append(box(rx - 21, ry - 30, 5, 42, 44, 20, METALC))
    g.append(box(rx - 28, ry - 20, 8, 56, 3, 1, METALC))
    for w_ in range(6):
        g.append(disc_x(rx + 26 + w_ * 1.2, ry - 10, 13, 13, "#23262E" if w_ < 5 else "#2E323B"))
    g.append(disc_x(rx + 32.2, ry - 10, 13, 6, "#B9C2CE"))
    g.append(disc_x(rx + 32.3, ry - 10, 13, 2.2, "#6B7684"))
    # white acrylic front skirt (chamfered) with velcro
    skirt = [(rx - 30, ry + 2), (rx + 30, ry + 2), (rx + 30, ry + 30), (rx + 20, ry + 42), (rx - 20, ry + 42), (rx - 30, ry + 30)]
    g.append(prism(skirt, 10, 14, "#FFFFFF", "#E1E6EE", "#C3CCD8"))
    for vx, vy in ((rx - 22, ry + 30), (rx - 5, ry + 33), (rx + 12, ry + 30)):
        g.append(poly([(vx, vy, 14.1), (vx + 10, vy, 14.1), (vx + 10, vy + 7, 14.1), (vx, vy + 7, 14.1)], "#2A2D36"))
    # standoffs + mid deck carrying the red + green board (visible at the back)
    for ox_, oy_ in ((-18, -26), (18, -26), (-18, 10), (18, 10)):
        g.append(box(rx + ox_ - 1, ry + oy_ - 1, 25, 2.4, 2.4, 20, METALC))
    g.append(box(rx - 26, ry - 32, 45, 52, 54, 3, ("#3A3F4B", "#262A33", "#1A1D24")))
    g.append(box(rx - 22, ry - 30, 48, 44, 30, 2, PCB))
    g.append(box(rx - 12, ry - 26, 50, 24, 22, 2.6, LAUNCH))
    g.append(box(rx - 11, ry - 24, 52.6, 22, 3, 1.6, ("#3A3F4B", "#262A33", "#1A1D24")))
    g.append(box(rx - 11, ry - 9, 52.6, 22, 3, 1.6, ("#3A3F4B", "#262A33", "#1A1D24")))
    g.append(box(rx - 4, ry - 19, 52.6, 7, 7, 1.6, ("#3A3F4B", "#262A33", "#1A1D24")))
    # yellow wire loop
    w0, w1 = P(rx + 21, ry - 16, 51), P(rx + 24, ry + 8, 38)
    g.append(f'<path d="M{w0[0]:.1f} {w0[1]:.1f}C{w0[0]+14:.1f} {w0[1]+2:.1f} {w1[0]+12:.1f} {w1[1]-8:.1f} {w1[0]:.1f} {w1[1]:.1f}" fill="none" stroke="#FFD23F" stroke-width="2"/>')
    # front tower: posts + white plate with the LiDAR and camera
    for ox_ in (-12, 10):
        g.append(box(rx + ox_, ry + 24, 14, 2.4, 2.4, 44, METALC))
    g.append(box(rx - 16, ry + 4, 58, 32, 26, 3, ("#FFFFFF", "#E1E6EE", "#C3CCD8")))
    # camera (faces +y) under the plate
    g.append(box(rx - 7, ry + 28, 46, 14, 4, 11, LAUNCH))
    g.append(f'<g transform="{m_yface(ry + 32, 0, 0)}"><circle cx="{rx}" cy="-51.5" r="4.4" fill="#C9D0DA"/><circle cx="{rx}" cy="-51.5" r="3" fill="#1B2230"/><circle cx="{rx-1}" cy="-52.5" r="1" fill="#9CD3FF"/></g>')
    # LiDAR body + spinning head
    g.append(box(rx - 7, ry + 9, 61, 14, 14, 13, ("#F4F6F9", "#D9DEE5", "#B9C1CC")))
    g.append(poly([(rx - 4, ry + 23, 64), (rx + 4, ry + 23, 64), (rx + 4, ry + 23, 69), (rx - 4, ry + 23, 69)], "#F5D90A"))
    g.append(cyl(rx, ry + 16, 74, 88, 7.5, "#3A3F4B", "#2F333D", "#101217"))
    g.append(cyl(rx, ry + 16, 88, 90.5, 5.5, "#2F6BC4", "#1D58A7", "#133F7C"))
    # the face (from the class mascot): two big eyes on the LiDAR, looking at the students
    for dx_, dy_ in ((-4.6, 5.8), (3.6, 6.6)):
        e = P(rx + dx_, ry + 16 + dy_, 81)
        g.append(f'<ellipse cx="{e[0]:.1f}" cy="{e[1]:.1f}" rx="{3.5*K:.1f}" ry="{4.4*K:.1f}" fill="#FFFFFF"/>'
                 f'<circle cx="{e[0]-1.3:.1f}" cy="{e[1]+0.9:.1f}" r="{2.1*K:.1f}" fill="{INK}"/>'
                 f'<circle cx="{e[0]-2:.1f}" cy="{e[1]-.2:.1f}" r="{0.7*K:.1f}" fill="#FFFFFF"/>')
    for bp in ball_pts:
        g.append(f'<circle cx="{bp[0]:.1f}" cy="{bp[1]:.1f}" r="{4.8*K:.1f}" fill="#DCE1E8"/>'
                 f'<circle cx="{bp[0]-1.4:.1f}" cy="{bp[1]-1.6:.1f}" r="{1.8*K:.1f}" fill="#FFFFFF"/>')
    return "".join(g)


hits_where(lambda d: d < sum(ROBOT) + 10)
add(robot(*ROBOT))
add(box(*CRATE[:2], 0, CRATE[2], CRATE[3], 24, PLY))
xo, yo = CRATE[:2]
add(f'<g transform="{m_yface(yo + CRATE[3], xo, 15)}"><rect width="{CRATE[2]}" height="4" fill="{ORANGE}"/></g>'
    f'<g transform="{m_xface(xo + CRATE[2], yo + CRATE[3], 15)}"><rect width="{CRATE[3]}" height="4" fill="{ALTGELD}"/></g>')
add(ply_wall("baffle"))
hits_where(lambda d: d >= sum(ROBOT) + 10)


# golf balls (vision / blob detection: orange vs blue is colour-blind safe)
def golf(x, y, col, hi):
    s = ell(x + 2, y + 2, .3, 5.5, SHADOW_MAT)
    c = P(x, y, 5)
    s += f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="{5*K:.1f}" fill="{col}"/><circle cx="{c[0]-1.8:.1f}" cy="{c[1]-2:.1f}" r="{1.7*K:.1f}" fill="{hi}"/>'
    return s


add(golf(*BALL_O, ORANGE, "#FFB27A"))
add(golf(*BALL_B, "#3D8BFF", "#B5D3FF"))

# ------------------------------------------------------------------ title block (all text ≥ AA on Illini Blue)
TX = 64
t, _ = text_path("UNIVERSITY OF ILLINOIS", TX, 150, 20, MONT[700], ORANGE, spacing=3.2); add(t)          # 4.8:1, bold 20px
t, w_se = text_path("SE", TX - 6, 290, 146, MONT[900], "#FFFFFF", spacing=-2); add(t)                   # 14.5:1
t, _ = text_path("423", TX - 6 + w_se + 30, 290, 146, MONT[900], ORANGE, spacing=-2); add(t)
t, _ = text_path("Introduction to", TX, 346, 32, MONT[600], "#B8C8E0"); add(t)                          # 8.6:1
t, _ = text_path("Mechatronics", TX - 2, 404, 58, MONT[800], "#FFFFFF", spacing=-0.5); add(t)
add(f'<path d="M{TX} 446h34v-16h22v16h14v-16h22v16h14v-16h22v16h34" fill="none" stroke="{ORANGE}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
t, _ = text_path("Microcontrollers · Sensors · Control · Robots", TX, 494, 24, SANS[600], "#DCE5F2"); add(t)   # 11.4:1
t, _ = text_path("Urbana-Champaign  ·  lectures, labs & homework", TX, 526, 20, SANS[400], "#B8C8E0"); add(t)
t, _ = text_path("illustration · Claude", 1236, 620, 14, SANS[600], "#A9BBD6", anchor="end"); add(t)    # 7.4:1

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
       f'<title id="t">SE 423: Introduction to Mechatronics, University of Illinois Urbana-Champaign</title>'
       f'<desc id="d">Isometric illustration of the SE 423 mechatronics lab. Two lab partners at a workbench program the red '
       f'TI LaunchPad F28379D on its green breakout board from a laptop, and point at the class robot car. The robot, with its '
       f'LiDAR, camera and motion-capture markers, scans a plywood arena and follows an A-star path around a wall to an orange '
       f'golf ball. A whiteboard shows a PWM signal and a PID feedback loop.</desc>'
       f'<defs>{"".join(defs)}</defs>{"".join(out)}</svg>\n')
OUT.write_text(svg, encoding="utf-8")
print(f"wrote {OUT} ({len(svg)/1024:.0f} KB)")
