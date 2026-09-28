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


# ==================================================================== scene (v4)
# Composition notes
#  * 2:1 banner, text column on the left (~40%), diorama on the right (~60%).
#  * Value groups: dark = navy background + arena mat, mid = walls/floor/plywood,
#    light = whiteboard, wall tops, text.  The strongest light/dark contrast is kept
#    for the focal points: "SE 423" and the robot on the dark mat.
#  * Illini Orange is the ~10% accent and is always opaque.
#  * Eye path (Z): eyebrow → "SE 423" → robot → students → tagline.
# Physical consistency (checked by validate() before anything is written)
#  * The LiDAR scans a horizontal plane at the height of its head; only geometry at
#    least that tall can return a point.  Arena walls are therefore taller than the
#    scan plane; the walls between the camera and the scene are drawn cut away
#    (section view) with phantom outlines, like the room itself.
#  * A* runs on a grid with obstacles inflated by the robot's footprint radius.

K = 1.2
OX, OY = 832, 222

WALL_L = "#9FB4D1"
WALL_R = "#B7C7DD"
WALL_TOP = "#EEF3F9"
SLAB = ("#CAD5E4", "#24457A", "#1A3561")
SHADOW_FLOOR = "#AFBCCF"
SHADOW_MAT = "#1B2437"
MAT = "#27324A"
CELL_SEEN = "#35456A"
LAUNCH = ("#C42330", "#A51C1C", "#7F1414")
PCB = ("#3DBE72", "#2E9E5B", "#237A46")
HOODIE_B = ("#F1F4F9", "#D3DBE7")
PLY = ("#F2D6A2", "#E1B777", "#C7975A")
PLY_CUT = "#D9AE6E"            # section colour of a cut plywood wall
BLACKC = ("#3A3F4B", "#262A33", "#1A1D24")
METALC = ("#E3E8EE", "#BCC6D2", "#9CA8B8")
OAKC = ("#EDBB78", "#D9A05C", "#BC8242")
SILVER = ("#F1F4F8", "#CDD4DE", "#AAB4C2")

RX, RY = 330, 190
ROOM_H = 120

# ---- robot (the SE 423 car), local model units scaled by RS; heading +y
RS = 0.8
ROBOT = (200, 66)
ROBOT_HEADING = (0, 1)
LIDAR_LOCAL = (0, 16)
LIDAR_Z = 81 * RS                                  # centre of the spinning head
ROBOT_FOOT = (-31, 31, -32, 42)                     # local footprint x0,x1,y0,y1
ROBOT_HALF_W = 31 * RS                              # inflation radius for A* (drives axis-aligned segments)
ROBOT_TOP = 136 * RS
CAM_LOCAL, CAM_HFOV = (0, 32), 70                   # front camera: position (local) and horizontal FOV

# ---- arena: plywood walls taller than the LiDAR plane; "cut" walls face the camera
WALL_H = 70
CUT_H = 12
MAT_R = (156, 0, 318, 180)
WALLS = [
    dict(name="divider", x=262, y=0, dx=6, dy=100, cut=True),
    dict(name="left", x=150, y=0, dx=6, dy=186, cut=False),
    dict(name="front", x=156, y=180, dx=168, dy=6, cut=True),
    dict(name="right", x=318, y=0, dx=6, dy=180, cut=True),
]
BALL_O = (290, 150)          # A* goal (orange golf ball)
BALL_B = (170, 160)          # the other colour: in view of the robot's camera
BALL_R = 4.5

# ---- bench + people
A_POS, B_POS = (23, 150), (23, 84)
BODY_R = 11                                         # footprint radius of a person (matches the cast shadow)
BENCH = (38, 58, 54, 124, 44)                       # x, y, depth, length, height
bx, by, bdx, bdy, bh = BENCH
BT = bh
BOARD_S = 1.0                                       # breakout 44 x 57 world units at s=1
BOARD_POS = (bx + 5, by + 62)
LAPTOP = (bx + 10, by + 7, 26, 34)                  # x, y, depth, width

WB = (158, 250, 72, 114)                            # whiteboard on the back wall: x0, x1, z0, (z1 unused)
TAG = (284, 304, 30, 50)                            # AprilTag on the back wall (right chamber)

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



# ------------------------------------------------------------------ validation bookkeeping
CHECKS = []


def check(ok, msg):
    CHECKS.append((bool(ok), msg))


# ------------------------------------------------------------------ painter's sort for small parts
def iso_sort(parts):
    """parts: list of (bbox(x0,x1,y0,y1,z0,z1), svg). Topological back-to-front order:
    A is behind B when A ends before B starts along x, y or z."""
    n = len(parts)
    eps = 1e-6
    behind = [[False] * n for _ in range(n)]
    for i in range(n):
        a = parts[i][0]
        for j in range(n):
            if i == j:
                continue
            b = parts[j][0]
            xy_overlap = a[0] < b[1] - eps and b[0] < a[1] - eps and a[2] < b[3] - eps and b[2] < a[3] - eps
            if a[1] <= b[0] + eps or a[3] <= b[2] + eps or (xy_overlap and a[5] <= b[4] + eps):
                behind[i][j] = True
    order, used = [], [False] * n
    for _ in range(n):
        for i in range(n):
            if used[i]:
                continue
            if not any(behind[j][i] and not used[j] and not behind[i][j] for j in range(n)):
                order.append(i)
                used[i] = True
                break
        else:
            order.extend(i for i in range(n) if not used[i])
            break
    return "".join(parts[i][1] for i in order)


# ------------------------------------------------------------------ the SE 423 breakout + LaunchPad (from photos)
def board3d(ox, oy, oz, s=1.0, lit=423):
    """Breakout v5 (green) with the TI LaunchPad F28379D (red) plugged in portrait.
    Photo 'up' (USB end, buzzer, buttons) points to −y; photo 'right' to +x.
    The 16 user LEDs show `lit` in binary (LED1 = bit 0)."""
    BWs, BLs = 44 * s, 57 * s
    U = lambda u: ox + u * BWs
    V = lambda v: oy + v * BLs
    z1 = oz + 1.6 * s
    parts = []

    def pbox(u0, v0, u1, v1, z0, h, cols):
        x0, y0, x1, y1 = U(u0), V(v0), U(u1), V(v1)
        parts.append(((x0, x1, y0, y1, z0, z0 + h * s), box(x0, y0, z0, x1 - x0, y1 - y0, h * s, cols)))

    def pcyl(u, v, z0, h, r, top, l, d):
        x, y = U(u), V(v)
        rr = r * s
        parts.append(((x - rr, x + rr, y - rr, y + rr, z0, z0 + h * s), cyl(x, y, z0, z0 + h * s, rr, top, l, d)))

    svg = [box(ox, oy, oz, BWs, BLs, 1.6 * s, PCB)]
    # --- flat features on the breakout (world-unit plane: a→+x, b→+y)
    f = []
    f.append(f'<rect x="{0.8*s}" y="{0.8*s}" width="{BWs-1.6*s}" height="{BLs-1.6*s}" rx="{1.2*s}" fill="none" stroke="{PCB[0]}" stroke-width="{0.7*s}"/>')
    for d_ in ((.05, .30, .20, .45), (.35, .72, .60, .95), (.70, .45, .95, .70), (.10, .85, .30, .98), (.66, .05, .80, .20)):
        f.append(f'<path d="M{d_[0]*BWs:.2f} {d_[1]*BLs:.2f}L{d_[2]*BWs:.2f} {d_[3]*BLs:.2f}" stroke="#46C47E" stroke-width="{1.4*s}" stroke-linecap="round"/>')
    for (u0, v0, u1, v1) in ((.245, .0, .665, .70), (.655, .62, .875, .87), (.80, .30, .975, .43), (.745, .905, .94, .985), (.0, .02, .24, .36)):
        f.append(f'<rect x="{u0*BWs:.2f}" y="{v0*BLs:.2f}" width="{(u1-u0)*BWs:.2f}" height="{(v1-v0)*BLs:.2f}" fill="none" stroke="#E8F5EC" stroke-width="{0.35*s}"/>')
    pads = []
    for i in range(20):                                   # Orange Pi Lite 2x20 footprint
        for cu in (.035, .065):
            pads.append((cu, .515 + i * .0135))
    for blk in (.675, .80):                               # ESP32 DevKit prototyping area
        for r_ in range(15):
            for c_ in range(3):
                pads.append((blk + c_ * .025, .64 + r_ * .015))
    for r_ in range(6):                                   # misc headers, top-left
        for c_ in range(5):
            pads.append((.03 + c_ * .035, .12 + r_ * .035))
    for (u, v) in pads:
        f.append(f'<circle cx="{u*BWs:.2f}" cy="{v*BLs:.2f}" r="{0.42*s:.2f}" fill="#F2C14E"/>')
    for (u, v) in ((.06, .935), (.19, .935), (.81, .935), (.94, .935), (.06, .975), (.94, .975)):
        f.append(f'<circle cx="{u*BWs:.2f}" cy="{v*BLs:.2f}" r="{0.9*s:.2f}" fill="#E0B54A"/><circle cx="{u*BWs:.2f}" cy="{v*BLs:.2f}" r="{0.45*s:.2f}" fill="{PCB[2]}"/>')
    t_, _ = text_path("SE 423", .765 * BWs, .962 * BLs, 3.2 * s, MONT[800], "#FFFFFF", spacing=0.15 * s)
    f.append(t_)
    svg.append(f'<g transform="{m_plane((ox, oy, z1 + .01), (1, 0, 0), (0, 1, 0))}">{"".join(f)}</g>')

    # --- raised parts on the breakout
    for v in (.49, .566, .638):                                               # scope terminals
        pcyl(.169, v, z1, 0.8, 1.7, "#E3E8EE", "#C3CBD6", "#9AA5B4")
    pcyl(.814, .03, z1, 5.0, 2.5, "#2A2E36", "#3A3F4B", "#15171C")          # TDK buzzer
    for i in range(4):                                                        # push buttons
        pbox(.905, .005 + i * .026, .965, .025 + i * .026, z1, 2.0, BLACKC)
    leds = [(c, r) for c in range(3) for r in range(5)] + [(3, 4)]            # LED1..LED16 layout
    for n_, (c, r) in enumerate(leds):
        on = (lit >> n_) & 1
        u, v = .835 + c * .04, .115 + r * .033
        cols = ("#FFE36E", "#F4C430", "#D9A520") if on else ("#F3F1E6", "#DAD7C8", "#BDB9A8")
        pbox(u, v, u + .022, v + .014, z1, 0.8, cols)
    pbox(.128, .718, .216, .751, z1, 0.9, BLACKC)                             # A4973 motor drivers
    pbox(.243, .718, .318, .751, z1, 0.9, BLACKC)
    pbox(.743, .436, .81, .497, z1, 0.8, BLACKC)                              # F28027
    pbox(.44, .898, .472, .922, z1, 0.8, BLACKC)                              # DRV8874 x2
    pbox(.63, .898, .662, .922, z1, 0.8, BLACKC)
    for (u, v) in ((.176, .79), (.284, .79), (.378, .90), (.595, .90)):      # electrolytic caps
        pcyl(u, v, z1, 2.4, 1.5, "#EEF1F5", "#D0D6DF", "#9AA5B4")
    pbox(.547, .70, .575, .835, z1, 4.0, BLACKC)                              # MPU-9250 header
    pcyl(.64, .64, z1, 0.8, 0.9, "#E9A15B", "#D08A45", "#A86A30")            # photoresistor

    # --- the LaunchPad, plugged in on two female headers
    LU0, LU1, LV0, LV1 = .253, .655, -.047, .696
    LU = lambda u: LU0 + u * (LU1 - LU0)
    LV = lambda v: LV0 + v * (LV1 - LV0)
    for hu in ((.02, .10), (.86, .94)):
        pbox(LU(hu[0]), LV(.26), LU(hu[1]), LV(.97), z1, 5.0, BLACKC)
    lz = z1 + 5.0 * s
    x0, y0, x1, y1 = U(LU0), V(LV0), U(LU1), V(LV1)
    parts.append(((x0, x1, y0, y1, lz, lz + 1.3 * s), box(x0, y0, lz, x1 - x0, y1 - y0, 1.3 * s, LAUNCH)))
    lt = lz + 1.3 * s
    lw, ll = x1 - x0, y1 - y0
    g = []
    g.append(f'<rect x="{0.5*s}" y="{0.5*s}" width="{lw-s}" height="{ll-s}" rx="{0.8*s}" fill="none" stroke="#F4F4F4" stroke-width="{0.45*s}"/>')
    g.append(f'<path d="M{0.06*lw:.2f} {0.186*ll:.2f}H{0.94*lw:.2f}" stroke="#F4F4F4" stroke-width="{0.35*s}"/>')
    g.append(f'<rect x="{0.41*lw:.2f}" y="{0.49*ll:.2f}" width="{0.41*lw:.2f}" height="{0.21*ll:.2f}" fill="none" stroke="#F4F4F4" stroke-width="{0.35*s}"/>')
    for (u, v) in ((.22, .41), (.52, .76)):
        g.append(f'<circle cx="{u*lw:.2f}" cy="{v*ll:.2f}" r="{0.7*s:.2f}" fill="#3A0A0A"/>')
    for (v0_, v1_) in ((.55, .61), (.63, .69)):
        g.append(f'<rect x="{0.02*lw:.2f}" y="{v0_*ll:.2f}" width="{0.06*lw:.2f}" height="{(v1_-v0_)*ll:.2f}" fill="#F2C14E"/>')
    for i in range(3):
        g.append(f'<rect x="{0.30*lw:.2f}" y="{(0.75+i*0.025)*ll:.2f}" width="{(0.28 - i*0.06)*lw:.2f}" height="{0.35*s:.2f}" fill="#F4F4F4"/>')
    g.append(f'<circle cx="{0.72*lw:.2f}" cy="{0.23*ll:.2f}" r="{0.55*s:.2f}" fill="#FF6B6B"/><circle cx="{0.78*lw:.2f}" cy="{0.23*ll:.2f}" r="{0.55*s:.2f}" fill="#8EC5FF"/>')
    parts.append(((x0, x1, y0, y1, lt, lt), f'<g transform="{m_plane((x0, y0, lt + .01), (1, 0, 0), (0, 1, 0))}">{"".join(g)}</g>'))

    def lbox(u0, v0, u1, v1, h, cols):
        pbox(LU(u0), LV(v0), LU(u1), LV(v1), lt, h, cols)

    lbox(.11, -.01, .23, .08, 2.4, SILVER)               # mini-USB (XDS100v2 debug)
    lbox(.53, .02, .68, .056, 1.0, SILVER)               # crystal
    lbox(.185, .137, .36, .204, 0.8, BLACKC)             # debug-probe ICs
    lbox(.387, .137, .555, .204, 0.8, BLACKC)
    lbox(.66, .09, .83, .16, 0.8, BLACKC)
    lbox(.445, .517, .78, .673, 1.0, ("#2F333C", "#22252C", "#17191E"))   # TMS320F28379D
    lbox(.67, .70, .765, .725, 0.9, SILVER)              # crystal
    lbox(.30, .357, .43, .413, 0.9, BLACKC)              # DIP switch
    lbox(.87, .50, .95, .545, 1.8, BLACKC)               # reset button
    lbox(.09, .70, .15, .74, 2.2, BLACKC)                # jumpers
    lbox(.87, .15, .97, .21, 2.2, BLACKC)
    for hu in ((.02, .08), (.88, .94)):                  # pin headers along both edges
        lbox(hu[0], .26, hu[1], .97, 2.0, BLACKC)
    lbox(.09, .965, .90, .998, 2.0, BLACKC)              # bottom headers

    svg.append(iso_sort(parts))
    # jumper wires (drawn last, they arc over everything)
    tip = lambda u, v: (U(LU(u)), V(LV(v)), lt + 2.0 * s)
    svg.append(wire3d(tip(.91, .95), (U(.66), V(.64), z1 + 0.8 * s), 5 * s, "#FFD23F", 1.2 * s))
    for i, c_ in enumerate(("#FF8A3D", "#FF8A3D", "#E0474C", "#E0474C")):
        svg.append(wire3d((U(.575), V(.715 + i * .03), z1 + 3.5 * s), (U(.49), V(.74 + i * .03), z1 + 0.2 * s), 2.5 * s, c_, 0.9 * s))
    return "".join(svg), (ox, ox + BWs, oy, oy + BLs), (U(LU(.17)), V(LV(-.01)), lt + 1.2 * s)


# ------------------------------------------------------------------ background + room
add(f'<rect width="{W}" height="{H}" fill="{BLUE}"/>')
defs.append('<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
            '<circle cx="2" cy="2" r="1.1" fill="#1F3A66"/></pattern>')
add(f'<rect width="{W}" height="{H}" fill="url(#dots)"/>')
add(poly([(8, 8, -30), (RX + 10, 8, -30), (RX + 10, RY + 10, -30), (8, RY + 10, -30)], "#0F2344"))
add(box(0, 0, -18, RX, RY, 18, SLAB))
add(poly([(0, RY, -4), (RX, RY, -4), (RX, RY, 0), (0, RY, 0)], ORANGE))
add(poly([(RX, 0, -4), (RX, RY, -4), (RX, RY, 0), (RX, 0, 0)], ALTGELD))
WT = 8
add(poly([(0, 0, 0), (0, RY, 0), (0, RY, ROOM_H), (0, 0, ROOM_H)], WALL_L))
add(poly([(0, 0, 0), (RX, 0, 0), (RX, 0, ROOM_H), (0, 0, ROOM_H)], WALL_R))
add(poly([(-WT, -WT, ROOM_H), (-WT, RY, ROOM_H), (0, RY, ROOM_H), (0, 0, ROOM_H), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], WALL_TOP))
add(poly([(-WT, RY, -18), (0, RY, -18), (0, RY, ROOM_H), (-WT, RY, ROOM_H)], "#DCE4EF"))
add(poly([(RX, -WT, -18), (RX, 0, -18), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], "#C3CFDF"))
add(poly([(0.01, 0, 0), (0.01, RY, 0), (0.01, RY, 5), (0.01, 0, 5)], "#8398B7"))
add(poly([(0, 0.01, 0), (RX, 0.01, 0), (RX, 0.01, 5), (0, 0.01, 5)], "#9CAECA"))

# whiteboard (PWM → PID), scaled to its slot on the back wall
wb_s = (WB[1] - WB[0]) / 128
wb = []
wb.append('<rect x="0" y="0" width="128" height="62" rx="3" fill="#FFFFFF"/>')
wb.append('<rect x="0" y="58" width="128" height="4" fill="#DDE4EE"/>')
wb.append(f'<g fill="none" stroke="{BLUE}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
          '<path d="M10 20h14"/><circle cx="29" cy="20" r="5"/><path d="M34 20h10"/>'
          '<rect x="44" y="10" width="36" height="20" rx="3"/><path d="M80 20h26M100 20v16H29v-11"/>'
          '<path d="M102 15l5 5-5 5"/></g>')
t, _ = text_path("PID", 62, 25.5, 12, MONT[800], BLUE, anchor="middle"); wb.append(t)
wb.append(f'<path d="M10 50h12v-10h12v10h12v-10h12v10h12v-10h12v10h12" fill="none" stroke="{ORANGE}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
add(f'<g transform="{m_yface(0.02, WB[0], WB[2] + 62 * wb_s, wb_s)}">{"".join(wb)}</g>')
check(WB[2] + 62 * wb_s <= ROOM_H - 2, "whiteboard fits below the top of the back wall")

tag = ['<rect x="0" y="0" width="16" height="16" fill="#FFFFFF"/><rect x="2" y="2" width="12" height="12" fill="#111"/>']
for (i, j) in ((1, 1), (3, 1), (2, 2), (1, 3), (4, 3), (3, 4), (2, 4)):
    tag.append(f'<rect x="{2+i*2}" y="{2+j*2}" width="2" height="2" fill="#FFFFFF"/>')
add(f'<g transform="{m_yface(0.02, TAG[0], TAG[3], (TAG[1]-TAG[0])/16)}">{"".join(tag)}</g>')

# ------------------------------------------------------------------ arena floor + A*
mx0, my0, mx1, my1 = MAT_R
add(poly([(mx0, my0, .2), (mx1, my0, .2), (mx1, my1, .2), (mx0, my1, .2)], MAT))

G = 10
gx0, gy0 = mx0, my0
cols, rows = int((mx1 - mx0) // G), int((my1 - my0) // G)
INFL = ROBOT_HALF_W


def cell_blocked(i, j):
    cx, cy = gx0 + (i + .5) * G, gy0 + (j + .5) * G
    for w in WALLS:
        dx = max(w["x"] - cx, 0, cx - (w["x"] + w["dx"]))
        dy = max(w["y"] - cy, 0, cy - (w["y"] + w["dy"]))
        if math.hypot(dx, dy) < INFL:
            return True
    return cy < INFL                    # back wall of the room (y = 0)


def cell_of(p):
    return (int((p[0] - gx0) // G), int((p[1] - gy0) // G))


def astar4(start, goal, turn_cost=0.5):
    """4-connected A* (Manhattan heuristic) with a small turn penalty."""
    import heapq
    h = lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1])
    openq = [(h(start), 0.0, start, (0, 0))]
    came, best, closed = {}, {(start, (0, 0)): 0.0}, []
    seen = set()
    while openq:
        f_, g_, cur, d = heapq.heappop(openq)
        if (cur, d) in seen:
            continue
        seen.add((cur, d))
        if cur not in closed:
            closed.append(cur)
        if cur == goal:
            path = [(cur, d)]
            while path[-1] in came:
                path.append(came[path[-1]])
            return [c for c, _ in path[::-1]], closed
        for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (cur[0] + nd[0], cur[1] + nd[1])
            if not (0 <= nb[0] < cols and 0 <= nb[1] < rows) or cell_blocked(*nb):
                continue
            ng = g_ + 1 + (turn_cost if d != (0, 0) and nd != d else 0)
            if ng < best.get((nb, nd), 1e9):
                best[(nb, nd)] = ng
                came[(nb, nd)] = (cur, d)
                heapq.heappush(openq, (ng + h(nb), ng, nb, nd))
    return [], closed


start_c, goal_c = cell_of(ROBOT), cell_of(BALL_O)
check(not cell_blocked(*start_c), "robot start cell is free in the inflated map")
check(not cell_blocked(*goal_c), "goal (orange ball) cell is free in the inflated map")
apath, aclosed = astar4(start_c, goal_c)
check(len(apath) > 1, "A* found a path")
check(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(apath, apath[1:])), "A* path is 4-connected")
check(all(not cell_blocked(*c) for c in apath), "every A* path cell is collision-free")
if len(apath) > 1:
    first = (apath[1][0] - apath[0][0], apath[1][1] - apath[0][1])
    check(first == ROBOT_HEADING, f"robot faces along the first path step {first}")
for (i, j) in aclosed:
    x, y = gx0 + i * G, gy0 + j * G
    add(poly([(x + 1.2, y + 1.2, .3), (x + G - 1.2, y + 1.2, .3), (x + G - 1.2, y + G - 1.2, .3), (x + 1.2, y + G - 1.2, .3)], CELL_SEEN))
centers = [(gx0 + (i + .5) * G, gy0 + (j + .5) * G) for i, j in apath]
# draw from the robot's front bumper onward (the part under the robot is hidden anyway)
vis = [c for c in centers if c[1] > ROBOT[1] + 40 * RS or c[0] != centers[0][0]]
vis = [(centers[0][0], ROBOT[1] + 40 * RS)] + vis
dpath = "M" + "L".join(f"{P(x, y, .5)[0]:.1f} {P(x, y, .5)[1]:.1f}" for x, y in vis)
add(f'<path d="{dpath}" fill="none" stroke="{ORANGE}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>')
add(ell(*BALL_O, .6, 10, "none", f' stroke="{ORANGE}" stroke-width="2.2"'))


# ------------------------------------------------------------------ people + bench
fa, fb = P(*A_POS), P(*B_POS)
for fx_, fy_ in (A_POS, B_POS):
    add(ell(fx_ + 2, fy_ + 2, .1, BODY_R, SHADOW_FLOOR))
add(person(*fb, STU_B))
add(person(*fa, STU_A))

add(poly([(bx + 4, by + 4, .1), (bx + bdx + 8, by + 4, .1), (bx + bdx + 8, by + bdy + 8, .1), (bx + 4, by + bdy + 8, .1)], SHADOW_FLOOR))
for lx, ly in ((bx + 3, by + 3), (bx + bdx - 7, by + 3), (bx + 3, by + bdy - 7), (bx + bdx - 7, by + bdy - 7)):
    add(box(lx, ly, 0, 4, 4, bh - 5, METALC))
add(box(bx + 3, by + 3, 12, bdx - 6, bdy - 6, 3, METALC))
add(box(bx + 12, by + 70, 15, 30, 36, 18, ("#5B6B84", "#4A5970", "#3B475B")))     # bench power supply
add(box(bx, by, bh - 5, bdx, bdy, 5, OAKC))

# laptop base + keyboard (keys towards the student at low x)
lx0, ly0, LW_, LL_ = LAPTOP
ALU = ("#E3E8EE", "#C3CBD6", "#A6B0BE")
add(box(lx0, ly0, BT, LW_, LL_, 1.8, ALU))
kb = (f'<rect x="{LL_/2-6}" y="2.5" width="12" height="6" rx="1.2" fill="#CDD4DE"/>'
      f'<rect x="3" y="10" width="{LL_-6}" height="11" rx="1.5" fill="#2F3440"/>')
add(f'<g transform="{m_plane((lx0 + 1, ly0 + LL_, BT + 1.8), (0, -1, 0), (1, 0, 0))}">{kb}</g>')

# the breakout + LaunchPad on the bench
bsvg, bfoot, usb_pt = board3d(*BOARD_POS, BT, BOARD_S)
add(bsvg)
c0, c1 = P(*usb_pt), P(lx0 + 14, ly0 + LL_, BT + 1)
add(f'<path d="M{c0[0]:.1f} {c0[1]:.1f}C{c0[0]-4:.1f} {c0[1]-12:.1f} {c1[0]+10:.1f} {c1[1]+6:.1f} {c1[0]:.1f} {c1[1]:.1f}" fill="none" stroke="#3B4252" stroke-width="{2*K:.1f}" stroke-linecap="round"/>')

check(bx <= bfoot[0] and bfoot[1] <= bx + bdx and by <= bfoot[2] and bfoot[3] <= by + bdy, "breakout board rests fully on the bench top")
check(bx <= lx0 and lx0 + LW_ <= bx + bdx and by <= ly0 and ly0 + LL_ <= by + bdy, "laptop rests fully on the bench top")
check(ly0 + LL_ <= bfoot[2] - 2, "laptop and board do not overlap")
check(A_POS[0] + BODY_R <= bx - 2 and B_POS[0] + BODY_R <= bx - 2, "students stand behind the bench, not inside it")

# arms: B types (hands on the keyboard, behind the lid); A rests a hand on the bench and
# points at the robot's LiDAR
hb1 = P(lx0 + 13, ly0 + 11, BT + 3)
hb2 = P(lx0 + 13, ly0 + 23, BT + 3)
add(arm(*fb, (-4, -85), hb1, STU_B, bend=-1, back=True))
add(arm(*fb, (10, -85), hb2, STU_B, bend=-1))
add(laptop_lid())
ha = P(bx + 2, A_POS[1] + 14, BT + 1)
check(bx <= bx + 2 <= bfoot[0], "A's resting hand is on the bench, beside the board")
add(arm(*fa, (-6, -85), ha, STU_A, l1=20, l2=19, bend=-1, back=True))
lid_pt = P(ROBOT[0] + LIDAR_LOCAL[0] * RS, ROBOT[1] + LIDAR_LOCAL[1] * RS, LIDAR_Z)
sh = (fa[0] + 11 * K, fa[1] - 85 * K)
ang = math.atan2(lid_pt[1] - sh[1], lid_pt[0] - sh[0])
pa = (sh[0] + math.cos(ang) * 38 * K, sh[1] + math.sin(ang) * 38 * K)
add(arm(*fa, (11, -85), pa, STU_A, l1=21, l2=19, bend=-1, point=True))

# ------------------------------------------------------------------ LiDAR ray casting (scan plane z = LIDAR_Z)
LX, LY = ROBOT[0] + LIDAR_LOCAL[0] * RS, ROBOT[1] + LIDAR_LOCAL[1] * RS
segs = []          # (p1, p2, owner, outward normal)
for w in WALLS:
    x, y, dx, dy = w["x"], w["y"], w["dx"], w["dy"]
    for (p1, p2, n) in (((x, y), (x + dx, y), (0, -1)), ((x + dx, y), (x + dx, y + dy), (1, 0)),
                        ((x, y + dy), (x + dx, y + dy), (0, 1)), ((x, y), (x, y + dy), (-1, 0))):
        segs.append((p1, p2, w["name"], n))
segs.append(((0, 0), (RX, 0), "room", (0, 1)))
segs.append(((0, 0), (0, RY), "room", (1, 0)))
check(all(WALL_H >= LIDAR_Z + 4 for _ in WALLS), f"arena walls ({WALL_H}) are taller than the LiDAR scan plane ({LIDAR_Z:.1f})")
check(ROOM_H >= LIDAR_Z + 4, "room walls are taller than the LiDAR scan plane")


def cast(ox, oy, a, rmax):
    dx, dy = math.cos(a), math.sin(a)
    best, hit = rmax, None
    for (x1, y1), (x2, y2), owner, n in segs:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
        u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        if t > 1e-6 and -1e-9 <= u <= 1 + 1e-9 and t < best:
            best, hit = t, (owner, n, (x1, y1), (x2, y2))
    return best, hit


FOV, NRAYS, RMAX = 240, 121, 400    # URG-04LX: 240°, ~4 m (drawn at 2° steps)
HEAD_R = 7.5 * RS
rays = []
hd = math.atan2(ROBOT_HEADING[1], ROBOT_HEADING[0])
for k in range(NRAYS):
    a = hd + math.radians(-FOV / 2 + k * FOV / (NRAYS - 1))
    r, hit = cast(LX, LY, a, RMAX)
    hx, hy = LX + r * math.cos(a), LY + r * math.sin(a)
    if hit:
        owner, n, p1, p2 = hit
        # the hit must lie on its segment, and the segment must face the LiDAR
        cross = (p2[0] - p1[0]) * (hy - p1[1]) - (p2[1] - p1[1]) * (hx - p1[0])
        check(abs(cross) < 1e-6 * max(1, math.hypot(p2[0] - p1[0], p2[1] - p1[1])), f"ray {k} hit lies on {owner}")
        check((LX - hx) * n[0] + (LY - hy) * n[1] > 0, f"ray {k} hits the face of {owner} that faces the LiDAR")
        wall = next((w for w in WALLS if w["name"] == owner), None)
        visible = (n[0] + n[1] > 0) or (wall is not None and wall["cut"])
    else:
        owner, visible = None, False
    rays.append(dict(a=a, end=(hx, hy), owner=owner, visible=visible))
check(all(r["owner"] for r in rays), "every LiDAR ray returns a point (arena is closed)")

# the robot's own mocap posts must be outside the LiDAR's field of view
for px_, py_ in ((-25 + 1.5, -30 + 1.5), (22 + 1.5, -30 + 1.5)):
    ang_ = math.degrees(math.atan2(ROBOT[1] + py_ * RS - LY, ROBOT[0] + px_ * RS - LX) - hd)
    ang_ = (ang_ + 180) % 360 - 180
    check(abs(ang_) > FOV / 2, f"mocap post at {ang_:.0f}° is outside the LiDAR's ±{FOV/2:.0f}° field of view")


def draw_rays(sel):
    s = []
    for k, r in enumerate(rays):
        if not sel(r):
            continue
        a = r["a"]
        p1 = P(*r["end"], LIDAR_Z)
        if k % 15 == 0:                                   # a few sample beams
            p0 = P(LX + HEAD_R * math.cos(a), LY + HEAD_R * math.sin(a), LIDAR_Z)
            s.append(f'<path d="M{p0[0]:.1f} {p0[1]:.1f}L{p1[0]:.1f} {p1[1]:.1f}" stroke="{ORANGE}" stroke-width="0.9" stroke-dasharray="2 3" stroke-linecap="round"/>')
        if r["visible"]:
            s.append(f'<circle cx="{p1[0]:.1f}" cy="{p1[1]:.1f}" r="1.7" fill="{ORANGE}"/>')
    return "".join(s)


toward_cam = lambda r: (r["end"][0] - LX) + (r["end"][1] - LY) > 0

# ------------------------------------------------------------------ arena objects (back → front)
def wall_svg(w):
    h = CUT_H if w["cut"] else WALL_H
    s = box(w["x"], w["y"], 0, w["dx"], w["dy"], h, PLY)
    if w["cut"]:
        s += poly([(w["x"], w["y"], h + .01), (w["x"] + w["dx"], w["y"], h + .01), (w["x"] + w["dx"], w["y"] + w["dy"], h + .01), (w["x"], w["y"] + w["dy"], h + .01)], PLY_CUT)
    return s


def phantom(w):
    """Dashed outline of the part of a cut wall that was removed for the view."""
    x0, y0, x1, y1 = w["x"], w["y"], w["x"] + w["dx"], w["y"] + w["dy"]
    pts_top = [(x0, y0, WALL_H), (x1, y0, WALL_H), (x1, y1, WALL_H), (x0, y1, WALL_H), (x0, y0, WALL_H)]
    d = "M" + "L".join(f"{P(*p)[0]:.1f} {P(*p)[1]:.1f}" for p in pts_top)
    return f'<path d="{d}" fill="none" stroke="#C9D6EA" stroke-width="0.8" stroke-dasharray="2 3"/>'


def robot(rx, ry):
    Rb = lambda lx, ly, lz, dx, dy, dz, cols: box(rx + lx * RS, ry + ly * RS, lz * RS, dx * RS, dy * RS, dz * RS, cols)
    Rp = lambda lx, ly, lz: P(rx + lx * RS, ry + ly * RS, lz * RS)
    g = []
    g.append(ell(rx, ry + 4 * RS, .4, 36 * RS, SHADOW_MAT))
    for xx in (-25, 22):                                   # mocap frame (behind)
        g.append(Rb(xx, -30, 24, 3, 3, 82, METALC))
    YEL = ("#F0F76A", "#E4F04B", "#C7D23A")
    g.append(Rb(-31, -31.5, 106, 62, 5, 6, BLACKC))
    g.append(Rb(-31.2, -31.7, 106, 12, 5.4, 6.2, YEL))
    g.append(Rb(19, -31.7, 106, 12, 5.4, 6.2, YEL))
    balls = [(-20, -29, 112, 128), (4, -29, 112, 136), (24, -29, 112, 124)]
    for bx_, by_, z0, z1 in balls:
        a_, b_ = Rp(bx_, by_, z0), Rp(bx_, by_, z1)
        g.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#8C97A7" stroke-width="1.8"/>')
    a_, b_ = Rp(-31, -29, 110), Rp(-46, -26, 114)
    g.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#8C97A7" stroke-width="1.8"/>')
    ball_pts = [Rp(bx_, by_, z1) for bx_, by_, _, z1 in balls] + [b_]
    # wheels: far, chassis, near (wheel radius 13 → axle at z 13: wheels touch the floor)
    g.append(disc_x(rx - 26 * RS, ry - 10 * RS, 13 * RS, 13 * RS, "#1A1C22"))
    g.append(Rb(-21, -30, 5, 42, 44, 20, METALC))
    for w_ in range(6):
        g.append(disc_x(rx + (26 + w_ * 1.2) * RS, ry - 10 * RS, 13 * RS, 13 * RS, "#23262E" if w_ < 5 else "#2E323B"))
    g.append(disc_x(rx + 32.2 * RS, ry - 10 * RS, 13 * RS, 6 * RS, "#B9C2CE"))
    g.append(disc_x(rx + 32.3 * RS, ry - 10 * RS, 13 * RS, 2.2 * RS, "#6B7684"))
    skirt = [(-30, 2), (30, 2), (30, 30), (20, 42), (-20, 42), (-30, 30)]
    g.append(prism([(rx + a * RS, ry + b * RS) for a, b in skirt], 10 * RS, 14 * RS, "#FFFFFF", "#E1E6EE", "#C3CCD8"))
    for vx, vy in ((-22, 30), (-5, 33), (12, 30)):
        g.append(poly([(rx + vx * RS, ry + vy * RS, 14 * RS + .1), (rx + (vx + 10) * RS, ry + vy * RS, 14 * RS + .1),
                       (rx + (vx + 10) * RS, ry + (vy + 7) * RS, 14 * RS + .1), (rx + vx * RS, ry + (vy + 7) * RS, 14 * RS + .1)], "#2A2D36"))
    for ox_, oy_ in ((-18, -26), (18, -26), (-18, 10), (18, 10)):
        g.append(Rb(ox_ - 1, oy_ - 1, 25, 2.4, 2.4, 20, METALC))
    g.append(Rb(-26, -32, 45, 52, 54, 3, BLACKC))
    # the same breakout + LaunchPad as on the bench, at robot scale
    rs_board = 0.5
    rsvg, rfoot, _ = board3d(rx - 22 * rs_board, ry - 31 * RS, 48 * RS, rs_board)
    deck = (rx - 26 * RS, rx + 26 * RS, ry - 32 * RS, ry + 22 * RS)
    check(deck[0] <= rfoot[0] and rfoot[1] <= deck[1] and deck[2] <= rfoot[2] and rfoot[3] <= deck[3], "robot's board fits on its deck")
    g.append(rsvg)
    w0, w1 = Rp(21, -16, 51), Rp(24, 8, 38)
    g.append(f'<path d="M{w0[0]:.1f} {w0[1]:.1f}C{w0[0]+10:.1f} {w0[1]+2:.1f} {w1[0]+9:.1f} {w1[1]-6:.1f} {w1[0]:.1f} {w1[1]:.1f}" fill="none" stroke="#FFD23F" stroke-width="1.8"/>')
    for ox_ in (-12, 10):
        g.append(Rb(ox_, 24, 14, 2.4, 2.4, 44, METALC))
    g.append(Rb(-16, 4, 58, 32, 26, 3, ("#FFFFFF", "#E1E6EE", "#C3CCD8")))
    g.append(Rb(-7, 28, 46, 14, 4, 11, LAUNCH))
    g.append(f'<g transform="{m_yface(ry + 32 * RS, 0, 0)}"><circle cx="{rx}" cy="{-51.5*RS:.2f}" r="{4.4*RS:.2f}" fill="#C9D0DA"/>'
             f'<circle cx="{rx}" cy="{-51.5*RS:.2f}" r="{3*RS:.2f}" fill="#1B2230"/><circle cx="{rx-0.8:.2f}" cy="{-52.5*RS:.2f}" r="{1*RS:.2f}" fill="#9CD3FF"/></g>')
    g.append(Rb(-7, 9, 61, 14, 14, 13, ("#F4F6F9", "#D9DEE5", "#B9C1CC")))
    g.append(poly([(rx - 4 * RS, ry + 23 * RS, 64 * RS), (rx + 4 * RS, ry + 23 * RS, 64 * RS), (rx + 4 * RS, ry + 23 * RS, 69 * RS), (rx - 4 * RS, ry + 23 * RS, 69 * RS)], "#F5D90A"))
    g.append(cyl(rx, ry + 16 * RS, 74 * RS, 88 * RS, 7.5 * RS, "#3A3F4B", "#2F333D", "#101217"))
    g.append(cyl(rx, ry + 16 * RS, 88 * RS, 90.5 * RS, 5.5 * RS, "#2F6BC4", "#1D58A7", "#133F7C"))
    for dx_, dy_ in ((-4.6, 5.8), (3.6, 6.6)):                # the mascot's eyes, on the LiDAR head
        e = Rp(dx_, 16 + dy_, 81)
        g.append(f'<ellipse cx="{e[0]:.1f}" cy="{e[1]:.1f}" rx="{3.5*K*RS:.1f}" ry="{4.4*K*RS:.1f}" fill="#FFFFFF"/>'
                 f'<circle cx="{e[0]-1:.1f}" cy="{e[1]+0.7:.1f}" r="{2.1*K*RS:.1f}" fill="{INK}"/>'
                 f'<circle cx="{e[0]-1.5:.1f}" cy="{e[1]-.2:.1f}" r="{0.7*K*RS:.1f}" fill="#FFFFFF"/>')
    for bp in ball_pts:
        g.append(f'<circle cx="{bp[0]:.1f}" cy="{bp[1]:.1f}" r="{4.8*K*RS:.1f}" fill="#DCE1E8"/>'
                 f'<circle cx="{bp[0]-1.2:.1f}" cy="{bp[1]-1.4:.1f}" r="{1.8*K*RS:.1f}" fill="#FFFFFF"/>')
    return "".join(g)


def golf(x, y, col, hi):
    s = ell(x + 1.5, y + 1.5, .3, BALL_R + 1, SHADOW_MAT)
    c = P(x, y, BALL_R)
    s += (f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="{BALL_R*K:.1f}" fill="{col}"/>'
          f'<circle cx="{c[0]-1.6:.1f}" cy="{c[1]-1.8:.1f}" r="{1.6*K:.1f}" fill="{hi}"/>')
    return s


W_ = {w["name"]: w for w in WALLS}
add(wall_svg(W_["left"]))
add(draw_rays(lambda r: not toward_cam(r)))
add(robot(*ROBOT))
add(wall_svg(W_["divider"]))
add(golf(*BALL_B, "#3D8BFF", "#B5D3FF"))
add(golf(*BALL_O, ORANGE, "#FFB27A"))
add(wall_svg(W_["right"]))
add(wall_svg(W_["front"]))
add(draw_rays(toward_cam))
for w in WALLS:
    if w["cut"]:
        add(phantom(w))

# ------------------------------------------------------------------ physical checks on the arena
foot = (ROBOT[0] + ROBOT_FOOT[0] * RS, ROBOT[0] + ROBOT_FOOT[1] * RS, ROBOT[1] + ROBOT_FOOT[2] * RS, ROBOT[1] + ROBOT_FOOT[3] * RS)
check(mx0 <= foot[0] and foot[1] <= mx1 and my0 <= foot[2] and foot[3] <= my1, "robot footprint is on the arena mat")
for w in WALLS:
    gapx = max(w["x"] - foot[1], foot[0] - (w["x"] + w["dx"]))
    gapy = max(w["y"] - foot[3], foot[2] - (w["y"] + w["dy"]))
    check(max(gapx, gapy) >= 4, f"robot clears the {w['name']} wall (gap {max(gapx, gapy):.1f})")
for name, b in (("orange", BALL_O), ("blue", BALL_B)):
    check(mx0 + BALL_R <= b[0] <= mx1 - BALL_R and my0 + BALL_R <= b[1] <= my1 - BALL_R, f"{name} ball is on the mat")
    for w in WALLS:
        dx = max(w["x"] - b[0], 0, b[0] - (w["x"] + w["dx"]))
        dy = max(w["y"] - b[1], 0, b[1] - (w["y"] + w["dy"]))
        check(math.hypot(dx, dy) >= BALL_R, f"{name} ball does not intersect the {w['name']} wall")
path_pts_w = [(gx0 + (i + .5) * G, gy0 + (j + .5) * G) for i, j in apath]
check(min(math.hypot(px - BALL_B[0], py - BALL_B[1]) for px, py in path_pts_w) > ROBOT_HALF_W + BALL_R,
      "the planned path does not run over the blue ball")
cam = (ROBOT[0] + CAM_LOCAL[0] * RS, ROBOT[1] + CAM_LOCAL[1] * RS)
cam_ang = math.degrees(math.atan2(BALL_B[1] - cam[1], BALL_B[0] - cam[0]) - hd)
check(abs(cam_ang) < CAM_HFOV / 2, f"blue ball is in the robot camera's view ({cam_ang:.0f}° of ±{CAM_HFOV/2:.0f}°)")
wb_top = WB[2] + 62 * wb_s
for w in WALLS:
    h = CUT_H if w["cut"] else WALL_H
    if w["y"] <= 0.5:                                   # walls that touch the back wall
        for name, (x0, x1, z0) in (("whiteboard", (WB[0], WB[1], WB[2])), ("AprilTag", (TAG[0], TAG[1], TAG[2]))):
            clear = x1 <= w["x"] or x0 >= w["x"] + w["dx"] or z0 >= h
            check(clear, f"{name} is not covered by the {w['name']} wall")

# ------------------------------------------------------------------ title block
TX = 64
text_right = 0
t, w_ = text_path("UNIVERSITY OF ILLINOIS", TX, 150, 20, MONT[700], ORANGE, spacing=3.2); add(t); text_right = max(text_right, TX + w_)
t, w_se = text_path("SE", TX - 6, 290, 146, MONT[900], "#FFFFFF", spacing=-2); add(t)
t, w_ = text_path("423", TX - 6 + w_se + 30, 290, 146, MONT[900], ORANGE, spacing=-2); add(t); text_right = max(text_right, TX - 6 + w_se + 30 + w_)
t, w_ = text_path("Introduction to", TX, 346, 32, MONT[600], "#B8C8E0"); add(t); text_right = max(text_right, TX + w_)
t, w_ = text_path("Mechatronics", TX - 2, 404, 58, MONT[800], "#FFFFFF", spacing=-0.5); add(t); text_right = max(text_right, TX + w_)
add(f'<path d="M{TX} 446h34v-16h22v16h14v-16h22v16h14v-16h22v16h34" fill="none" stroke="{ORANGE}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
t, w_ = text_path("Microcontrollers · Sensors · Control · Robots", TX, 494, 24, SANS[600], "#DCE5F2"); add(t); text_right = max(text_right, TX + w_)
t, w_ = text_path("Urbana-Champaign  ·  lectures, labs & homework", TX, 526, 20, SANS[400], "#B8C8E0"); add(t); text_right = max(text_right, TX + w_)
t, _ = text_path("illustration · Claude", 1236, 620, 14, SANS[600], "#A9BBD6", anchor="end"); add(t)


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (colour, px size, bold?) → WCAG AA: 4.5:1, or 3:1 for large text (≥24px, or ≥18.66px bold)
for col, size, bold in ((ORANGE, 20, True), ("#FFFFFF", 146, True), (ORANGE, 146, True), ("#B8C8E0", 32, False),
                        ("#FFFFFF", 58, True), ("#DCE5F2", 24, True), ("#B8C8E0", 20, False), ("#A9BBD6", 14, True)):
    need = 3.0 if (size >= 24 or (bold and size >= 18.66)) else 4.5
    cr = contrast(col, BLUE)
    check(cr >= need, f"text {col} at {size}px: contrast {cr:.2f}:1 ≥ {need}")

room_pts = [P(-WT, -WT, ROOM_H), P(-WT, RY, ROOM_H), P(-WT, RY, -18), P(RX, RY, -18), P(RX, -WT, ROOM_H), P(RX, -WT, -18)]
d_left = min(p[0] for p in room_pts)
d_right = max(p[0] for p in room_pts)
d_top = min(p[1] for p in room_pts)
d_bot = max(p[1] for p in room_pts)
check(text_right + 40 <= d_left, f"≥40px of air between text ({text_right:.0f}) and diorama ({d_left:.0f})")
check(d_right <= W - 24 and d_top >= 24 and d_bot <= H - 24, f"diorama inside the canvas with margins ({d_left:.0f}–{d_right:.0f}, {d_top:.0f}–{d_bot:.0f})")

# ------------------------------------------------------------------ report + write
failed = [m for ok, m in CHECKS if not ok]
print(f"validation: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
for m in failed:
    print("  FAIL:", m)
if failed:
    raise SystemExit(1)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
       f'<title id="t">SE 423: Introduction to Mechatronics, University of Illinois Urbana-Champaign</title>'
       f'<desc id="d">Isometric illustration of the SE 423 mechatronics lab. Two lab partners at a workbench program the red '
       f'TI LaunchPad F28379D on its green breakout board from a laptop; the board\'s LEDs show 423 in binary. One partner points at '
       f'the class robot car, which carries the same board, a camera, motion-capture markers and a LiDAR whose scan hits the '
       f'plywood arena walls. The robot follows an A-star path around a divider to an orange golf ball. A whiteboard shows a PWM '
       f'signal and a PID feedback loop.</desc>'
       f'<defs>{"".join(defs)}</defs>{"".join(out)}</svg>\n')
OUT.write_text(svg, encoding="utf-8")
print(f"wrote {OUT} ({len(svg)/1024:.0f} KB)")
