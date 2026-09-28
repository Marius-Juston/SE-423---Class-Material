#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools", "uharfbuzz", "resvg-py"]
# ///
"""SE 423 GitHub repo card: a flat isometric diorama of the mechatronics lab.

Two lab partners program the red + green F28379D board at a bench while the
class robot maps its plywood arena with LiDAR and plans a path to the goal.

Everything (including text, converted to outlines) is emitted as plain SVG
paths, so the card renders identically everywhere.

    uv run make_repo_card.py [out.svg] [--no-png]

writes out.svg (default: repo-card.svg next to this script) and, unless --no-png is
given, the 1280x640 out.png that GitHub's social preview needs.  The script is
self-contained: everything it reads lives next to it.

    fonts/                 Montserrat + Source Sans 3 (Illinois brand typefaces, SIL OFL 1.1)
    SE423_F28379D.brd      Eagle layout of the SE 423 breakout board (drawn from it)

Before writing, validate() runs geometric/accessibility checks; any failure aborts.
"""
import math
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = Path(_args[0]) if _args else HERE / "repo-card.svg"
WRITE_PNG = "--no-png" not in sys.argv
W, H = 1280, 640

# ------------------------------------------------------------------ palette
BLUE = "#13294B"        # Illini Blue
ORANGE = "#FF5F05"      # Illini Orange
ALTGELD = "#C84113"
ARCHES = "#1D58A7"
INK = "#0E1E38"

# ------------------------------------------------------------------ fonts → outlines
FONT_DIR = HERE / "fonts"
_fonts = {}


def _font(name):
    if name not in _fonts:
        path = FONT_DIR / f"{name}.ttf"
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
K = 1.36                   # world → screen scale
OX, OY = 836, 212          # screen position of the world origin (back corner of the room)


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
MOCAP_BAR_Z = 92 * RS
CAM_LOCAL, CAM_HFOV = (0, 32), 70                   # front camera: position (local) and horizontal FOV

# ---- arena: plywood walls taller than the LiDAR plane; "cut" walls face the camera
WALL_H = 70                                         # physical wall height (must exceed the scan plane)
CUT_H = 20                                          # drawn height: walls are shown cut (section) here
MAT_R = (156, 0, 318, 180)
WALLS = [
    dict(name="divider", x=262, y=0, dx=6, dy=100, cut=True),
    dict(name="left", x=150, y=0, dx=6, dy=186, cut=True),
    dict(name="front", x=156, y=180, dx=168, dy=6, cut=True),
    dict(name="right", x=318, y=0, dx=6, dy=180, cut=True),
]
BALL_O = (291, 145)          # A* goal (orange golf ball), at a grid-cell centre
BALL_B = (170, 160)          # the other colour: in view of the robot's camera
BALL_R = 4.5

# ---- bench + people
A_POS, B_POS = (25, 150), (25, 84)
BODY_R = 11                                         # footprint radius of a person (matches the cast shadow)
BENCH = (38, 58, 54, 124, 58)                       # x, y, depth, length, height (standing lab bench ≈ ½ body height)
bx, by, bdx, bdy, bh = BENCH
BT = bh
BOARD_K = 0.284                                     # world units per mm (breakout is 154.9 x 198.1 mm)
BOARD_POS = (bx + 5, by + 62)
LAPTOP = (bx + 4, by + 7, 26, 34)                  # x, y, depth, width

WB = (158, 250, 72, 114)                            # whiteboard on the back wall: x0, x1, z0, (z1 unused)
TAG = (280, 306, 24, 50)                            # AprilTag (tag36h11 #0) on the back wall, right chamber

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
    reach = math.hypot(hx - sx, hy - sy) / ((l1 + l2) * K)
    check(reach <= 0.97, f"arm reaches its target with a bent elbow (reach {reach:.2f} of full length)")
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


# ------------------------------------------------------------------ the real SE 423 breakout, from the Eagle layout
import xml.etree.ElementTree as ET

BRD_FILE = HERE / "SE423_F28379D.brd"
_brd = ET.parse(BRD_FILE).getroot().find("drawing/board")
_libs = {(lib.get("name"), p.get("name")): p for lib in _brd.find("libraries") for p in lib.find("packages")}
_outline = [w for w in _brd.find("plain").findall("wire") if w.get("layer") == "20"]
BRD_W = max(max(float(w.get("x1")), float(w.get("x2"))) for w in _outline)
BRD_H = max(max(float(w.get("y1")), float(w.get("y2"))) for w in _outline)
VZ = 1.8          # vertical exaggeration of component heights (they are only 1–10 mm tall)


def _rot(rot):
    rot = rot or "R0"
    return ("M" in rot), float("".join(ch for ch in rot if ch.isdigit() or ch == ".") or 0)


def _tf(el, x, y):
    """Package-local → board mm (Eagle, y up)."""
    mir, ang = _rot(el.get("rot"))
    if mir:
        x = -x
    a = math.radians(ang)
    return (float(el.get("x")) + x * math.cos(a) - y * math.sin(a), float(el.get("y")) + x * math.sin(a) + y * math.cos(a))


def _brd_texture():
    """Top view of the breakout in SVG units = mm, y down (tx = x, ty = BRD_H − y)."""
    T = lambda x, y: (x, BRD_H - y)
    s = [f'<rect width="{BRD_W}" height="{BRD_H}" rx="1.5" fill="{PCB[1]}"/>']
    traces = {}
    for sig in _brd.find("signals"):
        for w in sig.findall("wire"):
            if w.get("layer") != "1":
                continue
            a, b = T(float(w.get("x1")), float(w.get("y1"))), T(float(w.get("x2")), float(w.get("y2")))
            traces.setdefault(w.get("width"), []).append(f"M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}")
    for width, segs_ in traces.items():
        s.append(f'<path d="{"".join(segs_)}" stroke="#43B872" stroke-width="{max(float(width), 0.2):.2f}" stroke-linecap="round" fill="none"/>')
    silk, pads, holes = [], [], []
    for el in _brd.find("elements").findall("element"):
        pkg = _libs[(el.get("library"), el.get("package"))]
        mir, ang = _rot(el.get("rot"))
        for t in pkg:
            if t.tag == "pad":
                x, y = T(*_tf(el, float(t.get("x")), float(t.get("y"))))
                drill = float(t.get("drill"))
                dia = float(t.get("diameter") or 0) or drill * 1.7
                pads.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{dia/2:.2f}"/>')
                holes.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{drill/2:.2f}"/>')
            elif t.tag == "smd" and not mir:
                x, y = T(*_tf(el, float(t.get("x")), float(t.get("y"))))
                dx, dy = float(t.get("dx")), float(t.get("dy"))
                _, sr = _rot(t.get("rot"))
                pads.append(f'<rect x="{-dx/2:.2f}" y="{-dy/2:.2f}" width="{dx:.2f}" height="{dy:.2f}" transform="translate({x:.2f} {y:.2f}) rotate({-(ang + sr):.0f})"/>')
            elif t.tag == "wire" and t.get("layer") == "21" and not mir:
                a = T(*_tf(el, float(t.get("x1")), float(t.get("y1"))))
                b = T(*_tf(el, float(t.get("x2")), float(t.get("y2"))))
                silk.append(f"M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}")
            elif t.tag == "circle" and t.get("layer") == "21" and not mir:
                x, y = T(*_tf(el, float(t.get("x")), float(t.get("y"))))
                r_ = float(t.get("radius"))
                silk.append(f"M{x-r_:.2f} {y:.2f}a{r_:.2f} {r_:.2f} 0 1 0 {2*r_:.2f} 0a{r_:.2f} {r_:.2f} 0 1 0 {-2*r_:.2f} 0")
            elif t.tag == "hole":
                x, y = T(*_tf(el, float(t.get("x")), float(t.get("y"))))
                holes.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{float(t.get("drill"))/2:.2f}"/>')
    for w in _brd.find("plain").findall("wire"):
        if w.get("layer") == "21":
            a, b = T(float(w.get("x1")), float(w.get("y1"))), T(float(w.get("x2")), float(w.get("y2")))
            silk.append(f"M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}")
    for h_ in _brd.find("plain").findall("hole"):
        x, y = T(float(h_.get("x")), float(h_.get("y")))
        holes.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{float(h_.get("drill"))/2:.2f}"/>')
    s.append(f'<path d="{"".join(silk)}" stroke="#F1F5F0" stroke-width="0.25" fill="none" stroke-linecap="round"/>')
    for t in _brd.find("plain").findall("text"):
        if t.get("layer") != "21" or not (t.text or "").strip():
            continue
        x, y = T(float(t.get("x")), float(t.get("y")))
        size = float(t.get("size")) * 1.25
        _, ang = _rot(t.get("rot"))
        tp, _ = text_path(t.text.strip(), 0, 0, size, SANS[700], "#F1F5F0")
        s.append(f'<g transform="translate({x:.2f} {y:.2f}) rotate({-ang:.0f})">{tp}</g>')
    s.append(f'<g fill="#D8C27A">{"".join(pads)}</g>')
    s.append(f'<g fill="#173A26">{"".join(holes)}</g>')
    return "".join(s)


defs.append(f'<g id="se423-breakout-top">{_brd_texture()}</g>')


def _el(name):
    return next(e for e in _brd.find("elements").findall("element") if e.get("name") == name)


def _pads_bbox(el, kinds=("pad", "smd")):
    pkg = _libs[(el.get("library"), el.get("package"))]
    pts_ = [_tf(el, float(t.get("x")), float(t.get("y"))) for t in pkg if t.tag in kinds]
    xs, ys = [p[0] for p in pts_], [p[1] for p in pts_]
    return min(xs), max(xs), min(ys), max(ys)


def _ic_body(el):
    """Body of a gull-wing IC: between its two pin rows."""
    pkg = _libs[(el.get("library"), el.get("package"))]
    smds = [t for t in pkg if t.tag == "smd"]
    lx = [float(t.get("x")) for t in smds]
    ly = [float(t.get("y")) for t in smds]
    if len(set(round(v, 2) for v in ly)) <= 3:           # rows along x
        pl = max(float(t.get("dy")) for t in smds)
        yr = max(abs(v) for v in ly)
        corners = [(min(lx) - 0.6, -yr + pl / 2), (max(lx) + 0.6, yr - pl / 2)]
    else:
        pl = max(float(t.get("dx")) for t in smds)
        xr = max(abs(v) for v in lx)
        corners = [(-xr + pl / 2, min(ly) - 0.6), (xr - pl / 2, max(ly) + 0.6)]
    (ax, ay), (bx_, by_) = _tf(el, *corners[0]), _tf(el, *corners[1])
    return min(ax, bx_), max(ax, bx_), min(ay, by_), max(ay, by_)


# LaunchPad (LAUNCHXL-F28379D, ~58.4 × 137.2 mm) centred on its header footprint L1,
# overhanging the top edge of the breakout as on the real board
_lp_pads = _pads_bbox(_el("L1"))
LP_W, LP_L = 58.4, 137.2
LP_X0 = (_lp_pads[0] + _lp_pads[1]) / 2 - LP_W / 2
LP_Y1 = BRD_H + 7.4
LP_Y0 = LP_Y1 - LP_L


def board3d(ox, oy, oz, k=0.284, lit=423):
    """The breakout (texture from the .brd + populated parts) with the LaunchPad plugged in.
    k = world units per mm.  Board 'up' (+y in Eagle) points to world −y."""
    WX = lambda x: ox + x * k                  # Eagle mm → world
    WY = lambda y: oy + (BRD_H - y) * k
    z1 = oz + 1.6 * k
    parts = []

    def mbox(x0, x1, y0, y1, zb, h_mm, cols):
        wx0, wx1, wy0, wy1 = WX(x0), WX(x1), WY(y1), WY(y0)
        h = h_mm * k * VZ
        parts.append(((wx0, wx1, wy0, wy1, zb, zb + h), box(wx0, wy0, zb, wx1 - wx0, wy1 - wy0, h, cols)))

    def mcyl(x, y, r_mm, zb, h_mm, top, l, d):
        wx, wy, rr, h = WX(x), WY(y), r_mm * k, h_mm * k * VZ
        parts.append(((wx - rr, wx + rr, wy - rr, wy + rr, zb, zb + h), cyl(wx, wy, zb, zb + h, rr, top, l, d)))

    svg = [box(ox, oy, oz, BRD_W * k, BRD_H * k, 1.6 * k, PCB),
           f'<use href="#se423-breakout-top" transform="{m_plane((ox, oy, z1 + .01), (k, 0, 0), (0, k, 0))}"/>']

    for n in ("U1", "U5", "U2", "U4", "U8", "U6", "U3", "IC1", "IC2", "IC3", "U7"):   # populated ICs
        x0, x1, y0, y1 = _ic_body(_el(n))
        mbox(x0, x1, y0, y1, z1, 1.6, BLACKC)
    for el in _brd.find("elements").findall("element"):
        pk, name = el.get("package"), el.get("name")
        mir, _ = _rot(el.get("rot"))
        if mir:
            continue
        if pk == "CHIPLED_1206":
            x0, x1, y0, y1 = _pads_bbox(el)
            n = int(name[3:]) if name.startswith("LED") and name[3:].isdigit() else 0
            on = 1 <= n <= 16 and (lit >> (n - 1)) & 1
            cols = ("#FFE36E", "#F4C430", "#D9A520") if on else ("#F3F1E6", "#DAD7C8", "#BDB9A8")
            mbox(min(x0, x1) - .5, max(x0, x1) + .5, min(y0, y1) - .5, max(y0, y1) + .5, z1, 1.1, cols)
        elif pk in ("R1206", "M1206"):
            x0, x1, y0, y1 = _pads_bbox(el)
            mbox(x0 - .5, x1 + .5, y0 - .5, y1 + .5, z1, 0.6, ("#3A3F4B", "#262A33", "#1A1D24"))
        elif pk == "C1206":
            x0, x1, y0, y1 = _pads_bbox(el)
            mbox(x0 - .5, x1 + .5, y0 - .5, y1 + .5, z1, 0.9, ("#D9B98E", "#C4A175", "#A5855C"))
        elif pk == "BANANA_MALE":                                               # scope terminals
            mcyl(float(el.get("x")), float(el.get("y")), 4.4, z1, 1.2, "#E3E8EE", "#C3CBD6", "#9AA5B4")
    b1 = _el("B1")                                                              # TDK buzzer, Ø12 mm
    mcyl(float(b1.get("x")), float(b1.get("y")), 6.0, z1, 7.5, "#2A2E36", "#3A3F4B", "#15171C")
    for row_y in (180.18, 185.26, 190.34, 195.42):                               # four 6 mm push buttons
        mbox(137.6, 151.2, row_y - 1.7, row_y + 4.2, z1, 3.4, BLACKC)
    x0, x1, y0, y1 = _pads_bbox(_el("U$1"))                                      # MPU-9250 female header
    mbox(x0 - 1.3, x1 + 1.3, y0 - 1.3, y1 + 1.3, z1, 8.5, BLACKC)
    mpu_top = (x0, x1, (y0 + y1) / 2)

    # female headers under the LaunchPad: one block per run of pads in each column pair
    lp = _el("L1")
    pkg = _libs[(lp.get("library"), lp.get("package"))]
    cols_ = {}
    for t in pkg:
        if t.tag == "pad":
            x, y = _tf(lp, float(t.get("x")), float(t.get("y")))
            cols_.setdefault(round(x / 5.08), []).append((x, y))
    for pl in cols_.values():
        xs, ys = [p[0] for p in pl], [p[1] for p in pl]
        mbox(min(xs) - 1.3, max(xs) + 1.3, min(ys) - 1.3, max(ys) + 1.3, z1, 8.5, BLACKC)
    lz = z1 + 8.5 * k * VZ
    wx0, wx1, wy0, wy1 = WX(LP_X0), WX(LP_X0 + LP_W), WY(LP_Y1), WY(LP_Y0)
    parts.append(((wx0, wx1, wy0, wy1, lz, lz + 1.6 * k * VZ), box(wx0, wy0, lz, wx1 - wx0, wy1 - wy0, 1.6 * k * VZ, LAUNCH)))
    lt = lz + 1.6 * k * VZ
    lw, ll = wx1 - wx0, wy1 - wy0
    g = []
    sw = 0.35 * k / 0.284
    g.append(f'<rect x="{0.4*sw}" y="{0.4*sw}" width="{lw-0.8*sw}" height="{ll-0.8*sw}" rx="{sw}" fill="none" stroke="#F4F4F4" stroke-width="{sw:.2f}"/>')
    g.append(f'<path d="M{0.06*lw:.2f} {0.186*ll:.2f}H{0.94*lw:.2f}" stroke="#F4F4F4" stroke-width="{sw*0.8:.2f}"/>')
    g.append(f'<rect x="{0.41*lw:.2f}" y="{0.49*ll:.2f}" width="{0.41*lw:.2f}" height="{0.21*ll:.2f}" fill="none" stroke="#F4F4F4" stroke-width="{sw*0.8:.2f}"/>')
    for (u, v) in ((.22, .41), (.52, .76)):
        g.append(f'<circle cx="{u*lw:.2f}" cy="{v*ll:.2f}" r="{1.6*sw:.2f}" fill="#3A0A0A"/>')
    for (v0_, v1_) in ((.55, .61), (.63, .69)):
        g.append(f'<rect x="{0.02*lw:.2f}" y="{v0_*ll:.2f}" width="{0.06*lw:.2f}" height="{(v1_-v0_)*ll:.2f}" fill="#F2C14E"/>')
    for i in range(3):
        g.append(f'<rect x="{0.30*lw:.2f}" y="{(0.75+i*0.025)*ll:.2f}" width="{(0.28 - i*0.06)*lw:.2f}" height="{0.8*sw:.2f}" fill="#F4F4F4"/>')
    g.append(f'<circle cx="{0.72*lw:.2f}" cy="{0.23*ll:.2f}" r="{1.3*sw:.2f}" fill="#FF6B6B"/><circle cx="{0.78*lw:.2f}" cy="{0.23*ll:.2f}" r="{1.3*sw:.2f}" fill="#8EC5FF"/>')
    parts.append(((wx0, wx1, wy0, wy1, lt, lt), f'<g transform="{m_plane((wx0, wy0, lt + .01), (1, 0, 0), (0, 1, 0))}">{"".join(g)}</g>'))
    # LaunchPad parts, in fractions of its outline (u across, v from the USB end)
    LXm = lambda u: LP_X0 + u * LP_W
    LYm = lambda v: LP_Y1 - v * LP_L

    def lbox(u0, v0, u1, v1, h_mm, cols):
        mbox(LXm(u0), LXm(u1), LYm(v1), LYm(v0), lt, h_mm, cols)

    lbox(.11, -.01, .23, .06, 4.0, SILVER)               # mini-USB (XDS100v2 debug probe)
    lbox(.53, .02, .68, .056, 1.6, SILVER)               # crystal
    lbox(.185, .137, .36, .204, 1.4, BLACKC)             # debug-probe ICs
    lbox(.387, .137, .555, .204, 1.4, BLACKC)
    lbox(.66, .09, .83, .16, 1.2, BLACKC)
    lbox(.445, .517, .78, .673, 1.6, ("#2F333C", "#22252C", "#17191E"))   # TMS320F28379D
    lbox(.67, .70, .765, .725, 1.4, SILVER)              # crystal
    lbox(.30, .357, .43, .413, 1.4, BLACKC)              # DIP switch
    lbox(.87, .50, .95, .545, 3.0, BLACKC)               # reset button
    lbox(.09, .70, .15, .74, 3.5, BLACKC)                # jumpers
    lbox(.87, .15, .97, .21, 3.5, BLACKC)
    for hu in ((.02, .08), (.88, .94)):                  # pin headers along both edges
        lbox(hu[0], .26, hu[1], .97, 3.0, BLACKC)
    lbox(.09, .965, .90, .998, 3.0, BLACKC)              # bottom headers

    svg.append(iso_sort(parts))
    # the MPU-9250 wires (orange / red), plugged into the header as in the photo
    top_z = z1 + 8.5 * k * VZ
    for i, c_ in enumerate(("#FF8A3D", "#FF8A3D", "#E0474C", "#E0474C")):
        xm = mpu_top[0] + (i + 1) * (mpu_top[1] - mpu_top[0]) / 5
        svg.append(wire3d((WX(xm), WY(mpu_top[2]), top_z), (WX(xm - 6), WY(mpu_top[2] + 9), z1), 10 * k, c_, 2.4 * k / 0.284 * 0.4))
    usb = (WX(LXm(.17)), WY(LYm(.0)), lt + 2.0 * k * VZ)
    return "".join(svg), (ox, ox + BRD_W * k, oy + (BRD_H - LP_Y1) * k, oy + BRD_H * k), usb


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

TAG36H11_ID0 = ("########", "###.####", "##..#.##", "####.#.#",       # '#' black, '.' white
                "####..##", "#.#...##", "#.#.#..#", "########")          # (8×8 incl. black border)
tag = ['<rect x="0" y="0" width="10" height="10" fill="#FFFFFF"/>']
for j, row in enumerate(TAG36H11_ID0):
    for i, c in enumerate(row):
        if c == "#":
            tag.append(f'<rect x="{i + 1}" y="{j + 1}" width="1.02" height="1.02" fill="#111"/>')
add(f'<g transform="{m_yface(0.02, TAG[0], TAG[3], (TAG[1]-TAG[0])/10)}">{"".join(tag)}</g>')

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
check(len(centers) > 1 and math.dist(centers[-1], BALL_O) < 1e-6, "the A* path ends exactly on the orange ball")
vis = [c for c in centers if c[1] > ROBOT[1] + 40 * RS or c[0] != centers[0][0]]
vis = [(centers[0][0], ROBOT[1] + 40 * RS)] + vis
dpath = "M" + "L".join(f"{P(x, y, .5)[0]:.1f} {P(x, y, .5)[1]:.1f}" for x, y in vis)
add(f'<path d="{dpath}" fill="none" stroke="{ORANGE}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>')
for x, y in vis[1:-1]:                                   # one waypoint per grid cell
    q = P(x, y, .5)
    add(f'<circle cx="{q[0]:.1f}" cy="{q[1]:.1f}" r="2.6" fill="{ORANGE}"/>')
add(ell(*BALL_O, .6, 10, "none", f' stroke="{ORANGE}" stroke-width="2.2"'))


# ------------------------------------------------------------------ people + bench
fa, fb = P(*A_POS), P(*B_POS)
for fx_, fy_ in (A_POS, B_POS):
    add(ell(fx_ + 2, fy_ + 2, .1, BODY_R, SHADOW_FLOOR))
add(person(*fb, STU_B))
add(person(*fa, STU_A))

add(poly([(bx + 4, by + 4, .1), (bx + bdx + 8, by + 4, .1), (bx + bdx + 8, by + bdy + 8, .1), (bx + 4, by + bdy + 8, .1)], SHADOW_FLOOR))
LEG = 5
legs = ((bx + 1.5, by + 1.5), (bx + bdx - 1.5 - LEG, by + 1.5), (bx + 1.5, by + bdy - 1.5 - LEG), (bx + bdx - 1.5 - LEG, by + bdy - 1.5 - LEG))
for lx, ly in legs[:3]:
    add(box(lx, ly, 0, LEG, LEG, bh - 5, METALC))
add(box(bx + 1.5, by + 1.5, 14, bdx - 3, bdy - 3, 2, METALC))                     # lower shelf, between the legs
add(box(bx + 10, by + 70, 16, 30, 36, 16, ("#5B6B84", "#4A5970", "#3B475B")))     # bench power supply on the shelf
add(box(*legs[3], 0, LEG, LEG, bh - 5, METALC))                                    # front leg last (nearest the camera)
add(box(bx + 1.5, by + 1.5, bh - 9, bdx - 3, bdy - 3, 4, METALC))                 # apron frame under the top
add(box(bx, by, bh - 5, bdx, bdy, 5, OAKC))
check(16 + 16 <= bh - 9, "power supply fits between the shelf and the apron")

# laptop base + keyboard (keys towards the student at low x)
lx0, ly0, LW_, LL_ = LAPTOP
ALU = ("#E3E8EE", "#C3CBD6", "#A6B0BE")
add(box(lx0, ly0, BT, LW_, LL_, 1.8, ALU))
kb = (f'<rect x="{LL_/2-6}" y="2.5" width="12" height="6" rx="1.2" fill="#CDD4DE"/>'
      f'<rect x="3" y="10" width="{LL_-6}" height="11" rx="1.5" fill="#2F3440"/>')
add(f'<g transform="{m_plane((lx0 + 1, ly0 + LL_, BT + 1.8), (0, -1, 0), (1, 0, 0))}">{kb}</g>')

# the breakout + LaunchPad on the bench
bsvg, bfoot, usb_pt = board3d(*BOARD_POS, BT, BOARD_K)
add(bsvg)
c0, c1 = P(*usb_pt), P(lx0 + 14, ly0 + LL_, BT + 1)
add(f'<path d="M{c0[0]:.1f} {c0[1]:.1f}C{c0[0]-4:.1f} {c0[1]-12:.1f} {c1[0]+10:.1f} {c1[1]+6:.1f} {c1[0]:.1f} {c1[1]:.1f}" fill="none" stroke="#3B4252" stroke-width="{2*K:.1f}" stroke-linecap="round"/>')

check(bx <= bfoot[0] and bfoot[1] <= bx + bdx and by <= bfoot[2] and bfoot[3] <= by + bdy, "breakout board rests fully on the bench top")
check(bx <= lx0 and lx0 + LW_ <= bx + bdx and by <= ly0 and ly0 + LL_ <= by + bdy, "laptop rests fully on the bench top")
check(ly0 + LL_ <= bfoot[2] - 2, "laptop and board do not overlap")
check(A_POS[0] + BODY_R <= bx - 2 and B_POS[0] + BODY_R <= bx - 2, "students stand behind the bench, not inside it")

# arms. People face +x, so their left side (+y) is towards the camera: the left shoulder
# (screen-left, x = −4..−6) is the NEAR arm — drawn last, in the main colour — and it must
# reach the +y side of whatever it touches; the right shoulder (x = +10..+11) is the FAR arm,
# drawn first in the shadow colour.
SH_NEAR, SH_FAR = -5, 10.5


UPPER_ARM, FOREARM = 22, 23           # shoulder→elbow, elbow→palm centre (≈0.19 H and 0.20 H for H ≈ 115)


def shoulder_world(pos, sprite_dx, y_off):
    """World point of a shoulder: lateral offset y_off (+y is the near side), chosen so that it
    projects exactly onto the sprite's shoulder at (sprite_dx, −85)."""
    x_off = sprite_dx / C + y_off
    z = 85 + (x_off + y_off) * S
    return (pos[0] + x_off, pos[1] + y_off, z)


def arm3d(pos, sprite_dx, y_off, hand, p, bend_dir, back=False, point=False, who=""):
    """Two-bone arm solved in 3-D (so its length is right from the camera's point of view),
    then projected.  bend_dir: preferred elbow direction (world vector)."""
    Sh = shoulder_world(pos, sprite_dx, y_off)
    d = math.dist(Sh, hand)
    reach = d / (UPPER_ARM + FOREARM)
    check(reach <= 0.97, f"{who} reaches its target with a bent elbow (reach {reach:.2f})")
    u = [(hand[i] - Sh[i]) / d for i in range(3)]
    a = (UPPER_ARM ** 2 - FOREARM ** 2 + d * d) / (2 * d)
    hgt = math.sqrt(max(UPPER_ARM ** 2 - a * a, 0))
    bdot = sum(bend_dir[i] * u[i] for i in range(3))
    n = [bend_dir[i] - bdot * u[i] for i in range(3)]
    nl = math.sqrt(sum(v * v for v in n)) or 1
    E = tuple(Sh[i] + a * u[i] + hgt * n[i] / nl for i in range(3))
    check(abs(math.dist(Sh, E) - UPPER_ARM) < 1e-6 and abs(math.dist(E, hand) - FOREARM) < 1e-6, f"{who}: limb lengths preserved")
    top, top_d = p["top"]
    skin, _ = p["skin"]
    (sx, sy), (ex, ey), (hx, hy) = P(*Sh), P(*E), P(*hand)
    col = top_d if back else top
    ang = math.atan2(hy - ey, hx - ex)
    cx_, cy_ = hx - math.cos(ang) * 4.5 * K, hy - math.sin(ang) * 4.5 * K
    s_ = (f'<path d="M{sx:.1f} {sy:.1f}L{ex:.1f} {ey:.1f}" stroke="{col}" stroke-width="{9*K:.1f}" stroke-linecap="round"/>'
          f'<path d="M{ex:.1f} {ey:.1f}L{cx_:.1f} {cy_:.1f}" stroke="{col}" stroke-width="{7.6*K:.1f}" stroke-linecap="round"/>'
          f'<circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="{4.1*K:.1f}" fill="{top_d}"/>')
    hand_svg = (f'<g transform="translate({hx:.1f} {hy:.1f}) rotate({math.degrees(ang):.1f}) scale({K})">'
                f'<ellipse cx="0.5" cy="0" rx="4.4" ry="3.4" fill="{skin}"/>'
                f'<ellipse cx="-0.5" cy="-3" rx="1.6" ry="1.2" fill="{skin}"/>')
    if point:
        hand_svg += '<rect x="2" y="-1.2" width="6.5" height="2.4" rx="1.2" fill="' + skin + '"/>'
    hand_svg += '</g>'
    return s_ + hand_svg, (sx, sy), (hx, hy)


def cross2(a0, a1, b0, b1):
    o = lambda p, q, r: (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a0, a1, b0) * o(a0, a1, b1) < 0 and o(b0, b1, a0) * o(b0, b1, a1) < 0


# B types: palms on the palm rest, near hand on the +y half, far hand on the −y half (behind the lid)
far_b, s0, h0 = arm3d(B_POS, SH_FAR, -9, (lx0 + 9, ly0 + 11, BT + 2.5), STU_B, (0, -1, -1), back=True, who="B's far arm")
near_b, s1, h1 = arm3d(B_POS, SH_NEAR, 6, (lx0 + 9, ly0 + 23, BT + 2.5), STU_B, (0, 1, -1), who="B's near arm")
check(not cross2(s0, h0, s1, h1), "B's arms do not cross")
add(far_b)
add(near_b)
add(laptop_lid())
# A points at the robot's LiDAR with the far arm and rests the near hand on the bench
check(bx <= bx + 2 <= bfoot[0], "A's resting hand is on the bench, beside the board")
Sh_far = shoulder_world(A_POS, SH_FAR, -9)
lid_w = (ROBOT[0] + LIDAR_LOCAL[0] * RS, ROBOT[1] + LIDAR_LOCAL[1] * RS, LIDAR_Z)
dv = [lid_w[i] - Sh_far[i] for i in range(3)]
dl = math.sqrt(sum(v * v for v in dv))
point_to = tuple(Sh_far[i] + dv[i] / dl * 0.93 * (UPPER_ARM + FOREARM) for i in range(3))
far_a, s0, h0 = arm3d(A_POS, SH_FAR, -9, point_to, STU_A, (0, -1, -1), back=True, point=True, who="A's pointing arm")
near_a, s1, h1 = arm3d(A_POS, SH_NEAR, 6, (bx + 2, A_POS[1] + 14, BT + 1), STU_A, (0, 1, -0.3), who="A's resting arm")
check(not cross2(s0, h0, s1, h1), "A's arms do not cross")
add(far_a)
add(near_a)

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
check(MOCAP_BAR_Z > LIDAR_Z + 2, "mocap crossbar sits above the LiDAR scan plane")
check(abs(LIDAR_Z / MOCAP_BAR_Z - 0.86) < 0.05, f"LiDAR/crossbar height ratio {LIDAR_Z / MOCAP_BAR_Z:.2f} matches the real robot (~0.86)")


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


def scan_dots(owner):
    """Returns on one surface. On the (tall) room walls they sit at the true scan height;
    arena walls are drawn as a section below the scan plane, so their returns are shown
    projected onto the cut, exactly on the face that the beam hit."""
    s = []
    for r in rays:
        if r["owner"] != owner or not r["visible"]:
            continue
        z = LIDAR_Z if owner == "room" else CUT_H + 0.2
        p1 = P(*r["end"], z)
        s.append(f'<circle cx="{p1[0]:.1f}" cy="{p1[1]:.1f}" r="1.9" fill="{ORANGE}"/>')
    return "".join(s)


toward_cam = lambda r: (r["end"][0] - LX) + (r["end"][1] - LY) > 0

# ------------------------------------------------------------------ arena objects (back → front)
def wall_svg(w):
    h = CUT_H if w["cut"] else WALL_H
    s = box(w["x"], w["y"], 0, w["dx"], w["dy"], h, PLY)
    if w["cut"]:
        s += poly([(w["x"], w["y"], h + .01), (w["x"] + w["dx"], w["y"], h + .01), (w["x"] + w["dx"], w["y"] + w["dy"], h + .01), (w["x"], w["y"] + w["dy"], h + .01)], PLY_CUT)
    return s


def robot(rx, ry):
    Rb = lambda lx, ly, lz, dx, dy, dz, cols: box(rx + lx * RS, ry + ly * RS, lz * RS, dx * RS, dy * RS, dz * RS, cols)
    Rp = lambda lx, ly, lz: P(rx + lx * RS, ry + ly * RS, lz * RS)
    g = []
    g.append(ell(rx, ry + 4 * RS, .4, 36 * RS, SHADOW_MAT))
    for xx in (-25, 22):                                   # mocap frame (behind)
        g.append(Rb(xx, -30, 24, 3, 3, 68, METALC))
    YEL = ("#F0F76A", "#E4F04B", "#C7D23A")
    g.append(Rb(-31, -31.5, 92, 62, 5, 5, BLACKC))
    g.append(Rb(-31.2, -31.7, 92, 12, 5.4, 5.2, YEL))
    g.append(Rb(19, -31.7, 92, 12, 5.4, 5.2, YEL))
    balls = [(-20, -29, 97, 108), (4, -29, 97, 114), (24, -29, 97, 105)]
    for bx_, by_, z0, z1 in balls:
        a_, b_ = Rp(bx_, by_, z0), Rp(bx_, by_, z1)
        g.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#8C97A7" stroke-width="1.8"/>')
    a_, b_ = Rp(-31, -29, 95), Rp(-44, -26, 98)
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
    k_board = BOARD_K / 2
    rsvg, rfoot, _ = board3d(rx - BRD_W * k_board / 2, ry - 30 * RS, 48 * RS, k_board)
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
add(scan_dots("room"))
add(wall_svg(W_["left"]))
add(scan_dots("left"))
add(robot(*ROBOT))
add(wall_svg(W_["divider"]))
add(scan_dots("divider"))
add(golf(*BALL_B, "#3D8BFF", "#B5D3FF"))
add(golf(*BALL_O, ORANGE, "#FFB27A"))
add(wall_svg(W_["right"]))
add(scan_dots("right"))
add(wall_svg(W_["front"]))
add(scan_dots("front"))

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
if WRITE_PNG:
    import resvg_py
    png = OUT.with_suffix(".png")
    png.write_bytes(bytes(resvg_py.svg_to_bytes(svg_string=svg, width=W, height=H)))
    print(f"wrote {png} ({png.stat().st_size/1024:.0f} KB, {W}x{H}; GitHub accepts < 1 MB)")
