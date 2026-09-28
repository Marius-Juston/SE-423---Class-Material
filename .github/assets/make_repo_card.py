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

# ------------------------------------------------------------------ world layout
RX, RY = 360, 222                      # room floor extents
ROOM_H = 118
ARENA = (140, 16, 354, 216)            # x0, y0, x1, y1 of the black mat
ROBOT = (200, 80)
WALLS = {                              # plywood arena walls: x, y, dx, dy
    "back": (140, 16, 214, 6),
    "left": (140, 22, 6, 194),
    "mid": (264, 22, 6, 76),
    "low": (146, 162, 84, 6),
}
BOX_OBS = (300, 46, 28, 28)            # a crate obstacle
GOAL = (324, 184)
WALL_H = 20

# ------------------------------------------------------------------ background
add(f'<rect width="{W}" height="{H}" fill="{BLUE}"/>')
defs.append('<radialGradient id="halo" cx="0.5" cy="0.5" r="0.5">'
            '<stop offset="0" stop-color="#2B5496" stop-opacity="0.55"/>'
            '<stop offset="1" stop-color="#2B5496" stop-opacity="0"/></radialGradient>')
defs.append('<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
            '<circle cx="2" cy="2" r="1.2" fill="#FFFFFF" fill-opacity="0.07"/></pattern>')
add(f'<rect width="{W}" height="{H}" fill="url(#dots)"/>')
add(f'<ellipse cx="880" cy="340" rx="440" ry="320" fill="url(#halo)"/>')

# ------------------------------------------------------------------ room shell
# soft drop shadow under the floating floor slab
for i, op in enumerate((0.10, 0.10, 0.12)):
    add(poly([(-16 + i*6, -16 + i*6, -40), (RX + 16 - i*6, -16 + i*6, -40), (RX + 16 - i*6, RY + 16 - i*6, -40), (-16 + i*6, RY + 16 - i*6, -40)], "#050E1F", f' opacity="{op}"'))
add(box(0, 0, -20, RX, RY, 20, FLOOR))
# thin highlight on the floor edge
add(f'<polyline points="{pts((0, RY, 0), (RX, RY, 0), (RX, 0, 0))}" fill="none" stroke="#FFFFFF" stroke-opacity="0.7" stroke-width="1.5"/>')

# cut-away walls (orange section edges = UIUC accent)
WT = 10
add(poly([(0, 0, 0), (0, RY, 0), (0, RY, ROOM_H), (0, 0, ROOM_H)], WALL_L))             # left inner face
add(poly([(0, 0, 0), (RX, 0, 0), (RX, 0, ROOM_H), (0, 0, ROOM_H)], WALL_R))             # right inner face
add(poly([(-WT, -WT, ROOM_H), (-WT, RY, ROOM_H), (0, RY, ROOM_H), (0, 0, ROOM_H), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], WALL_TOP))
add(poly([(-WT, RY, -20), (0, RY, -20), (0, RY, ROOM_H), (-WT, RY, ROOM_H)], ORANGE))   # section cuts
add(poly([(RX, -WT, -20), (RX, 0, -20), (RX, 0, ROOM_H), (RX, -WT, ROOM_H)], ALTGELD))
# skirting shadow where walls meet floor
add(f'<polyline points="{pts((0, RY, 0), (0, 0, 0), (RX, 0, 0))}" fill="none" stroke="#B4C0D0" stroke-width="3"/>')

# --- right wall: whiteboard with a control loop, PWM and a LiDAR map
wb = []
wb.append('<rect x="0" y="0" width="170" height="74" rx="3" fill="#FFFFFF" stroke="#AEB9C9" stroke-width="3"/>')
# block diagram:  r → (Σ) → [PID] → [robot] → y , feedback underneath
wb.append(f'<g fill="none" stroke="{ARCHES}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
          '<path d="M8 22h12"/><circle cx="25" cy="22" r="5"/><path d="M30 22h8"/>'
          '<rect x="38" y="13" width="30" height="18" rx="2"/><path d="M68 22h10"/>'
          '<rect x="78" y="13" width="30" height="18" rx="2"/><path d="M108 22h14"/>'
          '<path d="M116 22v18H25v-13"/></g>')
wb.append(f'<path d="M36 19l3 3-3 3M76 19l3 3-3 3M120 19l3 3-3 3" fill="none" stroke="{ARCHES}" stroke-width="2" stroke-linecap="round"/>')
t, _ = text_path("PID", 53, 26.5, 9, MONT[800], ARCHES, anchor="middle"); wb.append(t)
t, _ = text_path("ROBOT", 93, 25.8, 6.6, MONT[800], ARCHES, anchor="middle"); wb.append(t)
# PWM trace
wb.append(f'<path d="M8 64h8v-12h10v12h6v-12h10v12h6v-12h10v12h8" fill="none" stroke="{ORANGE}" stroke-width="2.4" stroke-linejoin="round"/>')
# tiny occupancy map sketch
wb.append(f'<g fill="none" stroke="{BLUE}" stroke-width="2" stroke-linecap="round"><path d="M96 48h60v20h-60z" stroke-dasharray="1 3.5"/>'
          f'<path d="M112 68v-10M136 48v10"/></g><circle cx="104" cy="60" r="2.4" fill="{ORANGE}"/>'
          f'<path d="M104 60c10 0 12-6 22-6s14 8 22 8" fill="none" stroke="{ORANGE}" stroke-width="1.6" stroke-dasharray="3 2"/>')
add(f'<g transform="{m_yface(0, 160, 104)}">{"".join(wb)}</g>')
# marker tray
add(box(160, 0, 26, 170, 5, 3, METAL))

# --- left wall: SE 423 pennant + lab clock
pen_ = []
pen_.append(f'<path d="M0 0L96 18L0 36Z" fill="{ORANGE}"/><path d="M0 0v36" stroke="{INK}" stroke-width="3"/>')
t, _ = text_path("SE 423", 10, 22.5, 11.5, MONT[900], BLUE); pen_.append(t)
add(f'<g transform="{m_xface(0, 214, 100)}">{"".join(pen_)}</g>')
clk = (f'<circle cx="0" cy="0" r="15" fill="#FFFFFF" stroke="{INK}" stroke-width="3"/>'
       f'<path d="M0 0V-9M0 0L7 3" stroke="{INK}" stroke-width="2.4" stroke-linecap="round"/>'
       f'<circle r="1.8" fill="{ORANGE}"/>')
cx_, cy_ = P(0, 40, 98)
add(f'<g transform="translate({cx_:.1f} {cy_:.1f}) scale({K}) matrix({C:.3f} {-S:.3f} 0 1 0 0)">{clk}</g>')

# ------------------------------------------------------------------ arena floor decals
ax0, ay0, ax1, ay1 = ARENA
add(poly([(ax0, ay0, 0.3), (ax1, ay0, 0.3), (ax1, ay1, 0.3), (ax0, ay1, 0.3)], MAT))
grid = []
for gx in range(ax0 + 30, ax1, 30):
    grid.append(f"M{P(gx, ay0, .3)[0]:.1f} {P(gx, ay0, .3)[1]:.1f}L{P(gx, ay1, .3)[0]:.1f} {P(gx, ay1, .3)[1]:.1f}")
for gy in range(ay0 + 30, ay1, 30):
    grid.append(f"M{P(ax0, gy, .3)[0]:.1f} {P(ax0, gy, .3)[1]:.1f}L{P(ax1, gy, .3)[0]:.1f} {P(ax1, gy, .3)[1]:.1f}")
add(f'<path d="{"".join(grid)}" stroke="#FFFFFF" stroke-opacity="0.06" stroke-width="1"/>')
# --- LiDAR scan: real 2-D ray casting against the arena geometry
segs = []


def rect_segs(x, y, dx, dy):
    a, b, c, d = (x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy)
    return [(a, b), (b, c), (c, d), (d, a)]


for (x, y, dx, dy) in WALLS.values():
    segs += rect_segs(x, y, dx, dy)
segs += rect_segs(*BOX_OBS)
segs += [((0, 0), (RX, 0)), ((0, 0), (0, RY))]


def cast(ox, oy, ang, rmax):
    dx, dy = math.cos(ang), math.sin(ang)
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


RMAX = 118
scan, hits = [], []
N = 540
for i in range(N):
    ang = 2 * math.pi * i / N
    r = cast(*ROBOT, ang, RMAX)
    px, py = ROBOT[0] + r * math.cos(ang), ROBOT[1] + r * math.sin(ang)
    scan.append((px, py, 0.6))
    if r < RMAX - 1e-6 and i % 4 == 0:
        hits.append((px, py))
rcx, rcy = P(*ROBOT, 0.6)
defs.append(f'<radialGradient id="scan" gradientUnits="userSpaceOnUse" cx="{rcx:.1f}" cy="{rcy:.1f}" r="{RMAX*C*math.sqrt(2)*K:.1f}" '
            f'gradientTransform="translate({rcx:.1f} {rcy:.1f}) scale(1 {S/C:.4f}) translate({-rcx:.1f} {-rcy:.1f})">'
            f'<stop offset="0" stop-color="{ORANGE}" stop-opacity="0.24"/>'
            f'<stop offset="1" stop-color="{ORANGE}" stop-opacity="0.06"/></radialGradient>')
add(f'<polygon points="{pts(*scan)}" fill="url(#scan)"/>')
rays = "".join(f"M{rcx:.1f} {rcy:.1f}L{P(x, y, .6)[0]:.1f} {P(x, y, .6)[1]:.1f}" for x, y, _ in scan[::9])
add(f'<path d="{rays}" stroke="#FF8A3D" stroke-opacity="0.45" stroke-width="1"/>')
add(f'<polygon points="{pts(*scan)}" fill="none" stroke="#FF9D5C" stroke-opacity="0.5" stroke-width="1.2" stroke-linejoin="round"/>')
# faint rings on the floor


# --- planned path (rounded polyline) + goal target
route = [ROBOT, (ROBOT[0], 130), (GOAL[0], 130), GOAL]


def rounded(route, rad=26, step=3):
    outp = [route[0]]
    for i in range(1, len(route) - 1):
        (x0, y0), (x1, y1), (x2, y2) = route[i - 1], route[i], route[i + 1]
        d0 = math.hypot(x1 - x0, y1 - y0); d1 = math.hypot(x2 - x1, y2 - y1)
        a = (x1 - (x1 - x0) / d0 * rad, y1 - (y1 - y0) / d0 * rad)
        b = (x1 + (x2 - x1) / d1 * rad, y1 + (y2 - y1) / d1 * rad)
        for k in range(step + 1):
            t = k / step
            outp.append(((1-t)**2*a[0] + 2*(1-t)*t*x1 + t*t*b[0], (1-t)**2*a[1] + 2*(1-t)*t*y1 + t*t*b[1]))
    outp.append(route[-1])
    return outp


path_pts = rounded(route, step=10)
# simpler & robust: draw path points after the robot's front bumper
start_i = next(i for i, (x, y) in enumerate(path_pts) if y > ROBOT[1] + 32)
seg_pts = [(ROBOT[0], ROBOT[1] + 32)] + path_pts[start_i:-1] + [(GOAL[0], GOAL[1] - 16)]
dp = "M" + "L".join(f"{P(x, y, .8)[0]:.1f} {P(x, y, .8)[1]:.1f}" for x, y in seg_pts)
add(f'<path d="{dp}" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-dasharray="1 8" stroke-linecap="round" stroke-linejoin="round"/>')
gx_, gy_ = P(*GOAL, .8)
for rr, col in ((16, ORANGE), (11, "#FFFFFF"), (6, ORANGE)):
    add(f'<ellipse cx="{gx_:.1f}" cy="{gy_:.1f}" rx="{rr*C*math.sqrt(2)*K:.1f}" ry="{rr*S*math.sqrt(2)*K:.1f}" fill="{col}"/>')

# ------------------------------------------------------------------ people
SKIN_A, SKIN_B = "#9A5E3A", "#F2C7A0"


def ik(sx, sy, hx, hy, l1, l2, bend=1):
    dx, dy = hx - sx, hy - sy
    dist = min(math.hypot(dx, dy), l1 + l2 - 0.01)
    a = math.atan2(dy, dx)
    cosb = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    b = math.acos(max(-1, min(1, cosb)))
    ea = a + bend * b
    return sx + l1 * math.cos(ea), sy + l1 * math.sin(ea)


def person_body(fx, fy, p):
    """Standing figure, 3/4 view facing screen-right (+x world). Origin at feet."""
    g = []
    pants, pants_d, shoe = p["pants"], p["pants_d"], "#F7F8FA"
    top, top_d = p["top"], p["top_d"]
    skin, hair = p["skin"], p["hair"]
    # legs
    g.append(f'<path d="M-9 -50h9v44h-9z" fill="{pants_d}"/><path d="M0 -50h10v46H0z" fill="{pants}"/>')
    g.append(f'<rect x="-10" y="-7" width="14" height="7" rx="3.5" fill="#D5DBE4"/><rect x="0" y="-6" width="17" height="7" rx="3.5" fill="{shoe}"/>')
    # torso (hoodie)
    g.append(f'<path d="M-15 -48C-16 -70 -15 -86 -6 -91H8C16 -86 17 -70 16 -48Z" fill="{top}"/>')
    g.append(f'<path d="M-15 -48C-16 -70 -15 -86 -6 -91H-1C-8 -80 -9 -64 -7 -48Z" fill="{top_d}"/>')
    g.append(f'<rect x="-15" y="-52" width="31" height="5" rx="2" fill="{top_d}"/>')
    g.append(f'<path d="M-9 -91C-8 -84 8 -84 10 -91Z" fill="{top_d}"/>')  # hood collar
    if p.get("strings"):
        g.append(f'<path d="M4 -86v10M8 -86v8" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>')
    # neck + head
    g.append(f'<rect x="-3" y="-96" width="8" height="8" fill="{p["skin_d"]}"/>')
    g.append(f'<circle cx="2" cy="-106" r="12" fill="{skin}"/>')
    g.append(f'<circle cx="-7" cy="-105" r="3.2" fill="{p["skin_d"]}"/>')          # ear
    g.append(p["hair_svg"](hair))
    # face (3/4 right)
    g.append(f'<circle cx="5" cy="-106" r="1.6" fill="{INK}"/><circle cx="11" cy="-106" r="1.6" fill="{INK}"/>')
    g.append(f'<path d="M6 -100q3 2.2 6 0" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>')
    g.append(f'<circle cx="4" cy="-102" r="2.2" fill="#E77C6B" opacity="0.45"/>')
    if p.get("glasses"):
        g.append(f'<g fill="none" stroke="{INK}" stroke-width="1.3"><circle cx="5.2" cy="-106" r="3.6"/><circle cx="12" cy="-106" r="3"/><path d="M8.8 -106.5h0.4M1.6 -106.5l-6 -1"/></g>')
    return f'<g transform="translate({fx:.1f} {fy:.1f}) scale({K})">{"".join(g)}</g>'


def arm(fx, fy, shoulder, hand, p, l1=22, l2=22, bend=1, back=False):
    sx, sy = fx + shoulder[0] * K, fy + shoulder[1] * K
    l1, l2 = l1 * K, l2 * K
    hx, hy = hand
    ex, ey = ik(sx, sy, hx, hy, l1, l2, bend)
    col = p["top_d"] if back else p["top"]
    return (f'<path d="M{sx:.1f} {sy:.1f}L{ex:.1f} {ey:.1f}L{hx:.1f} {hy:.1f}" fill="none" stroke="{col}" stroke-width="{8.5*K:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{4.3*K:.1f}" fill="{p["skin"]}"/>')


def hair_curly_bun(c):
    return (f'<circle cx="-4" cy="-122" r="7" fill="{c}"/>'
            f'<path d="M-10 -104C-14 -122 4 -124 14 -114C10 -118 2 -116 -1 -112C-3 -106 -6 -104 -10 -104Z" fill="{c}"/>'
            f'<circle cx="-6" cy="-113" r="6" fill="{c}"/><circle cx="3" cy="-117" r="6" fill="{c}"/><circle cx="10" cy="-115" r="4.5" fill="{c}"/>')


def hair_short(c):
    return (f'<path d="M-11 -100C-15 -118 0 -124 12 -118C16 -115 15 -111 14 -110C8 -114 2 -114 -1 -110C-3 -106 -5 -102 -8 -100Z" fill="{c}"/>')


STU_A = dict(top=ORANGE, top_d=ALTGELD, pants=ARCHES, pants_d=INDUSTRIAL, skin=SKIN_A, skin_d="#7C4A2C",
             hair="#1B1411", hair_svg=hair_curly_bun, strings=True)
STU_B = dict(top="#2E4F86", top_d="#1E3877", pants="#5D6B80", pants_d="#46536A", skin=SKIN_B, skin_d="#D9A882",
             hair="#5A3A22", hair_svg=hair_short, glasses=True)

A_POS, B_POS = (30, 176), (30, 100)          # world feet positions (behind the bench)
BENCH = (46, 62, 60, 150, 44)                # x, y, dx(depth), dy(length), height

# bodies first (they are behind the bench)
fa, fb = P(*A_POS), P(*B_POS)
add(person_body(*fb, STU_B))
add(person_body(*fa, STU_A))

# ------------------------------------------------------------------ workbench
bx, by, bdx, bdy, bh = BENCH
for lx, ly in ((bx + 3, by + 3), (bx + bdx - 7, by + 3), (bx + 3, by + bdy - 7), (bx + bdx - 7, by + bdy - 7)):
    add(box(lx, ly, 0, 4, 4, bh - 5, METAL))
add(box(bx + 3, by + 3, 12, bdx - 6, bdy - 6, 3, METAL))                 # lower shelf
add(box(bx + 10, by + 14, 15, 30, 26, 12, ("#5B6B84", "#4A5970", "#3B475B")))  # parts bin
add(box(bx + 12, by + 96, 15, 34, 40, 20, ("#6A7890", "#4E5B72", "#3E485B")))  # power supply
add(box(bx, by, bh - 5, bdx, bdy, 5, OAK))                                 # oak top
BT = bh                                                                   # bench top z

# laptop: base on bench, lid open towards the student (we see its back)
lx0, ly0 = bx + 12, by + 8
add(box(lx0, ly0, BT, 24, 34, 2, ("#D5DBE4", "#B6BFCC", "#9AA5B4")))
add(box(lx0 + 2, ly0, BT + 2, 2.5, 34, 24, ("#E1E6ED", "#C3CBD6", "#CDD4DE")))
lid = (f'<circle cx="17" cy="11" r="5.5" fill="{ORANGE}"/>'
       f'<rect x="6" y="15" width="12" height="5" rx="1.2" fill="{BLUE}"/>')
add(f'<g transform="{m_xface(lx0 + 4.5, ly0 + 34, BT + 25)}">{lid}</g>')
# screen glow on student B
gxl, gyl = P(lx0, ly0 + 17, BT + 20)
add(f'<ellipse cx="{gxl-18:.1f}" cy="{gyl-4:.1f}" rx="32" ry="22" fill="#9CD3FF" opacity="0.18"/>')

# ---- the red + green board (TI LaunchPad F28379D on the SE 423 breakout)
def big_board():
    s = []
    BW, BH = 280, 160
    s.append(f'<rect x="6" y="8" width="{BW}" height="{BH}" rx="10" fill="#000" opacity="0.18"/>')
    s.append(f'<rect width="{BW}" height="{BH}" rx="10" fill="{PCB[1]}"/>')
    s.append(f'<rect x="4" y="4" width="{BW-8}" height="{BH-8}" rx="8" fill="none" stroke="{PCB[0]}" stroke-width="3"/>')
    for d_ in ("M22 34h40l12 12h20", "M22 128h58l14-14h28", "M204 140h40l10-10v-40", "M240 24v28l-10 10", "M40 62v40l10 10h12"):
        s.append(f'<path d="{d_}" fill="none" stroke="#3CC274" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity="0.8"/>')
    for hx, hy in ((14, 14), (BW - 14, 14), (14, BH - 14), (BW - 14, BH - 14)):
        s.append(f'<circle cx="{hx}" cy="{hy}" r="7" fill="#F2C14E"/><circle cx="{hx}" cy="{hy}" r="3" fill="{PCB[2]}"/>')
    for i in range(3):
        s.append(f'<rect x="{28+i*24}" y="{BH-42}" width="20" height="18" rx="2" fill="#35D07F"/><circle cx="{38+i*24}" cy="{BH-33}" r="4.5" fill="#B9C2CE"/>')
    s.append(f'<rect x="232" y="100" width="34" height="28" rx="3" fill="#FAFAF7"/><rect x="239" y="107" width="20" height="12" fill="#D2D2CA"/>')
    s.append(f'<circle cx="250" cy="46" r="14" fill="#23262E"/><circle cx="250" cy="46" r="3.5" fill="#555B66"/>')
    s.append(f'<rect x="186" y="118" width="38" height="30" rx="3" fill="{ARCHES}"/><rect x="199" y="127" width="12" height="12" fill="#0E1426"/>')
    s.append(f'<rect x="-10" y="58" width="24" height="46" rx="3" fill="#C9D0DA"/><rect x="-5" y="68" width="12" height="26" rx="3" fill="#6B7684"/>')
    s.append(f'<rect x="92" y="{BH-20}" width="86" height="11" rx="1" fill="#15171D"/>')
    for i in range(12):
        s.append(f'<rect x="{95+i*7}" y="{BH-17}" width="3.2" height="5" fill="#F2C14E"/>')
    t_, _ = text_path("SE 423 BREAKOUT", 30, 25, 11, MONT[800], "#EAF7EE", spacing=1.2)
    s.append(t_)
    LX, LY, LW, LH = 70, 34, 158, 80
    s.append(f'<rect x="{LX+5}" y="{LY+6}" width="{LW}" height="{LH}" rx="5" fill="#000" opacity="0.28"/>')
    s.append(f'<rect x="{LX}" y="{LY}" width="{LW}" height="{LH}" rx="5" fill="{LAUNCH[1]}"/>')
    s.append(f'<rect x="{LX+3}" y="{LY+3}" width="{LW-6}" height="{LH-6}" rx="3" fill="none" stroke="{LAUNCH[0]}" stroke-width="2.5"/>')
    for hy in (LY + 5, LY + LH - 16):
        s.append(f'<rect x="{LX+24}" y="{hy}" width="{LW-32}" height="11" rx="1.5" fill="#17181E"/>')
        for i in range(17):
            s.append(f'<rect x="{LX+27+i*7.3:.1f}" y="{hy+4}" width="3.2" height="3.2" fill="#5E6270"/>')
    s.append(f'<rect x="{LX-12}" y="{LY+28}" width="22" height="20" rx="2.5" fill="#D5DAE1"/>')
    s.append(f'<rect x="{LX+14}" y="{LY+26}" width="16" height="16" rx="1" fill="#1A1B21"/>')
    mx, my = LX + 74, LY + 22
    s.append(f'<rect x="{mx-4}" y="{my-4}" width="44" height="44" rx="2" fill="#C9CED6" opacity="0.9"/>')
    s.append(f'<rect x="{mx}" y="{my}" width="36" height="36" rx="2" fill="#1C1D24"/><circle cx="{mx+7}" cy="{my+7}" r="2.4" fill="#3A3C48"/>')
    s.append(f'<rect x="{LX+36}" y="{LY+46}" width="12" height="12" rx="2" fill="#EDEDED"/><circle cx="{LX+42}" cy="{LY+52}" r="3" fill="#3A3C48"/>')
    s.append(f'<circle cx="{LX+138}" cy="{LY+32}" r="4" fill="#FF6B6B"/><circle cx="{LX+138}" cy="{LY+32}" r="8" fill="#FF6B6B" opacity="0.35"/>')
    s.append(f'<circle cx="{LX+138}" cy="{LY+48}" r="4" fill="#63B3FF"/><circle cx="{LX+138}" cy="{LY+48}" r="8" fill="#63B3FF" opacity="0.35"/>')
    for d_, c_ in (("M150 38C150 2 238 0 248 34", "#FFD23F"), ("M178 38C186 10 226 12 236 102", "#4F8BFF"),
                   ("M106 114C112 150 62 152 46 128", "#FF5A5A")):
        s.append(f'<path d="{d_}" fill="none" stroke="#0B1222" stroke-width="7" stroke-linecap="round" opacity="0.35"/>'
                 f'<path d="{d_}" fill="none" stroke="{c_}" stroke-width="4.2" stroke-linecap="round"/>')
    return "".join(s)


# board lies on the bench, long side along +y; 280x160 local → 70x40 world
BS = 0.33
bxw, byw = bx + 4, by + 50
add(box(bxw, byw, BT, 160 * BS, 280 * BS, 1.5, PCB))      # PCB thickness
add(f'<g transform="{m_top_uy(bxw + 160*BS, byw, BT + 1.5, BS)} rotate(180 140 80)">{big_board()}</g>')

# USB cable board → laptop
c0, c1 = P(bxw + 30, byw + 2, BT + 2), P(lx0 + 12, ly0 + 34, BT + 2)
add(f'<path d="M{c0[0]:.1f} {c0[1]:.1f}C{c0[0]+10:.1f} {c0[1]-4:.1f} {c1[0]+14:.1f} {c1[1]+6:.1f} {c1[0]:.1f} {c1[1]:.1f}" fill="none" stroke="#3B4252" stroke-width="2.6" stroke-linecap="round"/>')

# arms over the bench: B types, A reaches for the board and points at the robot
hand_b = P(lx0 + 12, ly0 + 20, BT + 3)
add(arm(*fb, (6, -84), (hand_b[0], hand_b[1]), STU_B, l1=24, l2=24, bend=-1))
hand_a = P(bxw + 22, byw + 58, BT + 3)
add(arm(*fa, (-2, -84), (hand_a[0], hand_a[1]), STU_A, l1=24, l2=24, bend=1, back=True))
# pointing arm towards the robot
pa = (fa[0] + 46*K, fa[1] - 100*K)
add(arm(*fa, (8, -84), pa, STU_A, l1=21, l2=21, bend=-1))
add(f'<path d="M{pa[0]:.1f} {pa[1]:.1f}l{7*K:.1f} {-4*K:.1f}" stroke="{SKIN_A}" stroke-width="{3.2*K:.1f}" stroke-linecap="round"/>')

# ------------------------------------------------------------------ arena objects (back → front)
def ply_wall(key):
    x, y, dx, dy = WALLS[key]
    return box(x, y, 0, dx, dy, WALL_H, PLY)


add(ply_wall("back"))
add(ply_wall("left"))


# ---- the robot
def robot(rx, ry):
    g = []
    sx, sy = P(rx, ry, 0)
    g.append(f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{34*K:.1f}" ry="{19*K:.1f}" fill="#0A0F1A" opacity="0.4"/>')
    # mocap frame (behind)
    fxp = rx - 22
    for yy in (ry - 24, ry + 21):
        g.append(box(fxp, yy, 22, 3, 3, 84, METAL))
    g.append(box(fxp - 1, ry - 30, 106, 5, 60, 6, BLACK))
    g.append(box(fxp - 1.2, ry - 30, 106, 5.4, 12, 6.2, ("#F0F76A", "#E4F04B", "#C7D23A")))
    g.append(box(fxp - 1.2, ry + 18, 106, 5.4, 12, 6.2, ("#F0F76A", "#E4F04B", "#C7D23A")))
    balls = [(fxp + 1, ry - 20, 112, 128), (fxp + 1, ry + 6, 112, 136), (fxp + 1, ry + 26, 112, 124), (fxp + 1, ry - 4, 112, 120)]
    stick = []
    for bxx, byy, z0, z1 in balls:
        a_, b_ = P(bxx, byy, z0), P(bxx, byy, z1)
        stick.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#9AA5B4" stroke-width="2.2"/>')
    # sideways marker
    a_, b_ = P(fxp + 2, ry - 30, 110), P(fxp + 16, ry - 44, 114)
    stick.append(f'<path d="M{a_[0]:.1f} {a_[1]:.1f}L{b_[0]:.1f} {b_[1]:.1f}" stroke="#9AA5B4" stroke-width="1.8"/>')
    g.extend(stick)
    ball_pos = [P(bxx, byy, z1) for bxx, byy, _, z1 in balls] + [b_]
    # wheels (+y side visible)
    for wx in (rx,):
        g.append(f'<g transform="{m_yface(ry + 23, 0, 0)}"><circle cx="{wx}" cy="-11" r="11" fill="#1A1C22"/><circle cx="{wx}" cy="-11" r="4.5" fill="#B9C2CE"/></g>')
    # chassis
    g.append(box(rx - 20, ry - 20, 5, 40, 40, 17, METAL))
    g.append(box(rx - 26, ry - 26, 22, 52, 52, 3, WHITE))            # acrylic deck
    # velcro pads
    for vx, vy in ((rx + 10, ry - 22), (rx - 22, ry + 12), (rx + 12, ry + 14)):
        g.append(poly([(vx, vy, 25.1), (vx + 10, vy, 25.1), (vx + 10, vy + 8, 25.1), (vx, vy + 8, 25.1)], "#2A2D36"))
    # standoffs
    for ox_, oy_ in ((-18, -18), (18, -18), (-18, 18), (18, 18)):
        g.append(box(rx + ox_ - 1, ry + oy_ - 1, 25, 2, 2, 32, METAL))
    # green board + red launchpad on the robot
    g.append(box(rx - 16, ry - 20, 38, 32, 40, 2, PCB))
    g.append(box(rx - 9, ry - 14, 40, 18, 28, 2.5, LAUNCH))
    g.append(box(rx - 8, ry - 12, 42.5, 3, 24, 2, BLACK))
    g.append(box(rx + 4, ry - 12, 42.5, 3, 24, 2, BLACK))
    g.append(box(rx - 3, ry - 5, 42.5, 6, 6, 1.5, BLACK))
    # upper deck
    g.append(box(rx - 24, ry - 24, 57, 48, 48, 2.5, BLACK))
    # camera (faces +y)
    g.append(box(rx - 6, ry + 20, 59.5, 12, 3, 10, LAUNCH))
    g.append(f'<g transform="{m_yface(ry + 23, 0, 0)}"><circle cx="{rx}" cy="-64.5" r="3.6" fill="#1B2230"/><circle cx="{rx-1}" cy="-65.5" r="1.1" fill="#9CD3FF"/></g>')
    # LiDAR
    g.append(box(rx - 8, ry - 8, 59.5, 16, 16, 14, ("#EEF1F5", "#D5DAE1", "#B7BEC9")))
    g.append(poly([(rx - 5, ry + 8, 62), (rx + 5, ry + 8, 62), (rx + 5, ry + 8, 67), (rx - 5, ry + 8, 67)], "#F5D90A"))
    g.append(cyl(rx, ry, 73.5, 88, 7.5, "#3A3F4B", "#2C2F38", "#111318"))
    g.append(cyl(rx, ry, 88, 90, 5.5, ARCHES, "#16408A", "#0E2E66"))
    # the robot's face: two eyes on the LiDAR, looking at the students
    for dy_, dx_ in ((7.2, -3.6), (5.4, 4.6)):
        ex_, ey_ = P(rx + dx_, ry + dy_, 80.5)
        g.append(f'<ellipse cx="{ex_:.1f}" cy="{ey_:.1f}" rx="{3.4*K:.1f}" ry="{4.2*K:.1f}" fill="#FFFFFF"/><circle cx="{ex_-1.4:.1f}" cy="{ey_+0.8:.1f}" r="{2*K:.1f}" fill="{INK}"/>')
    # scan-plane glow ring
    cxr, cyr = P(rx, ry, 80.5)
    g.append(f'<ellipse cx="{cxr:.1f}" cy="{cyr:.1f}" rx="{12*C*math.sqrt(2)*K:.1f}" ry="{12*S*math.sqrt(2)*K:.1f}" fill="none" stroke="{ORANGE}" stroke-width="1.6" opacity="0.9"/>')
    # markers on top
    for bxy in ball_pos:
        g.append(f'<circle cx="{bxy[0]:.1f}" cy="{bxy[1]:.1f}" r="{4.6*K:.1f}" fill="url(#ball)"/>')
    # yellow wire loop (as on the real robot)
    w0, w1 = P(rx + 20, ry - 6, 60), P(rx + 22, ry + 10, 44)
    g.append(f'<path d="M{w0[0]:.1f} {w0[1]:.1f}C{w0[0]+12:.1f} {w0[1]+4:.1f} {w1[0]+12:.1f} {w1[1]-4:.1f} {w1[0]:.1f} {w1[1]:.1f}" fill="none" stroke="#FFD23F" stroke-width="1.8"/>')
    return "".join(g)


defs.append('<radialGradient id="ball" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#A3ABB7"/></radialGradient>')
def draw_hits(sel):
    for hx, hy in hits:
        if sel(hx + hy):
            q = P(hx, hy, 10)
            add(f'<circle cx="{q[0]:.1f}" cy="{q[1]:.1f}" r="2" fill="#FFB07A"/>')


draw_hits(lambda d: d < sum(ROBOT))
add(robot(*ROBOT))
add(ply_wall("mid"))
add(box(*BOX_OBS[:2], 0, BOX_OBS[2], BOX_OBS[3], 26, PLY))
xo, yo = BOX_OBS[:2]
tape = f'<rect x="0" y="0" width="{BOX_OBS[2]}" height="4" fill="{ORANGE}"/>'
add(f'<g transform="{m_yface(yo + BOX_OBS[3], xo, 16)}">{tape}</g><g transform="{m_xface(xo + BOX_OBS[2], yo + BOX_OBS[3], 16)}">{tape}</g>')
add(ply_wall("low"))
# LiDAR returns: dots where rays hit geometry (drawn above walls at scan height)
draw_hits(lambda d: d >= sum(ROBOT))
# goal flag
fp0, fp1 = P(*GOAL, 0), P(*GOAL, 40)
add(f'<path d="M{fp0[0]:.1f} {fp0[1]:.1f}V{fp1[1]:.1f}" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round"/>')
add(f'<g transform="{m_yface(GOAL[1], GOAL[0], 40)}"><path d="M0 0L22 6L0 12Z" fill="{ORANGE}"/></g>')

# ------------------------------------------------------------------ title block
TX = 64
t, _ = text_path("UNIVERSITY OF ILLINOIS URBANA-CHAMPAIGN", TX, 168, 13, MONT[700], ORANGE, spacing=1.9); add(t)
t, w_se = text_path("SE", TX - 5, 282, 128, MONT[900], "#FFFFFF", spacing=-2); add(t)
t, _ = text_path("423", TX - 5 + w_se + 30, 282, 128, MONT[900], ORANGE, spacing=-2); add(t)
t, _ = text_path("Introduction to", TX, 336, 30, MONT[600], "#B8C8E0"); add(t)
t, _ = text_path("Mechatronics", TX - 2, 390, 52, MONT[800], "#FFFFFF", spacing=-0.5); add(t)
# PWM waveform as the divider — the signature signal of the course
add(f'<path d="M{TX} 430h36v-14h22v14h14v-14h22v14h14v-14h22v14h36" fill="none" stroke="{ORANGE}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>')
t, _ = text_path("Microcontrollers · Sensors · Control · Robotics", TX, 474, 21, SANS[600], "#DCE5F2"); add(t)
t, _ = text_path("github.com/Marius-Juston/SE-423---Class-Material", TX, 592, 15, SANS[600], "#7489AB"); add(t)
t, _ = text_path("illustration · Claude", 1240, 618, 12.5, SANS[600], "#6F84A6", anchor="end"); add(t)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
       f'<title id="t">SE 423: Introduction to Mechatronics, University of Illinois Urbana-Champaign</title>'
       f'<desc id="d">Isometric illustration of the mechatronics lab: two partners program the red and green TI F28379D board at a workbench while the class robot scans its plywood arena with LiDAR and follows a planned path to a goal.</desc>'
       f'<defs>{"".join(defs)}</defs>{"".join(out)}</svg>\n')
OUT.write_text(svg, encoding="utf-8")
print(f"wrote {OUT} ({len(svg)/1024:.0f} KB)")
