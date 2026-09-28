#!/usr/bin/env python3
"""Generate the SE 423 GitHub repo card (1280x640 SVG)."""
import sys

W, H = 1280, 640
OUT = sys.argv[1] if len(sys.argv) > 1 else "repo-card.svg"

# UIUC palette
BLUE = "#13294B"      # Illini Blue
ORANGE = "#FF5F05"    # Illini Orange
ALTGELD = "#C84113"
ARCHES = "#1D58A7"
INK = "#0A1428"       # outline colour
CLOUD = "#E8E9EB"

p = []  # svg parts
a = p.append

a(f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
<title id="title">SE 423: Introduction to Mechatronics</title>
<desc id="desc">Two students at a lab workbench program a red and green TI microcontroller board while the class robot, with its LiDAR, camera and motion-capture markers, scans the room. University of Illinois Urbana-Champaign.</desc>
<defs>
  <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#1B3766"/>
    <stop offset="1" stop-color="{BLUE}"/>
  </linearGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0B1830"/>
    <stop offset="1" stop-color="#081225"/>
  </linearGradient>
  <radialGradient id="lamp" cx="0.5" cy="0" r="1">
    <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.22"/>
    <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="screenGlow" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#9CD3FF" stop-opacity="0.35"/>
    <stop offset="1" stop-color="#9CD3FF" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="ball" cx="0.35" cy="0.3" r="0.8">
    <stop offset="0" stop-color="#F4F5F7"/>
    <stop offset="1" stop-color="#9DA4AE"/>
  </radialGradient>
  <linearGradient id="alu" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#8E98A6"/>
    <stop offset="0.45" stop-color="#E3E7EC"/>
    <stop offset="1" stop-color="#9AA4B1"/>
  </linearGradient>
  <linearGradient id="oak" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#E4B06C"/>
    <stop offset="1" stop-color="#D39A52"/>
  </linearGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
    <path d="M32 0H0V32" fill="none" stroke="#FFFFFF" stroke-opacity="0.045" stroke-width="1"/>
  </pattern>
  <pattern id="plate" width="18" height="12" patternUnits="userSpaceOnUse">
    <path d="M3 3l5 3M12 9l5-3" stroke="#FFFFFF" stroke-opacity="0.06" stroke-width="2" stroke-linecap="round"/>
  </pattern>
  <pattern id="velcro" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="4" fill="#1B1B1F"/>
    <circle cx="2" cy="2" r="0.9" fill="#3A3A42"/>
  </pattern>
  <style>
    .o{{stroke:{INK};stroke-width:3.5;stroke-linejoin:round;stroke-linecap:round}}
    .t{{stroke:{INK};stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}}
    .ln{{fill:none;stroke-linecap:round;stroke-linejoin:round}}
    .sans{{font-family:'Segoe UI','Helvetica Neue',Helvetica,Arial,'Liberation Sans',sans-serif}}
    .mono{{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace}}
  </style>
</defs>
''')

# ---------------------------------------------------------------- background
a(f'<rect width="{W}" height="{H}" fill="url(#wall)"/>')
a(f'<rect width="{W}" height="{H}" fill="url(#grid)"/>')

# ceiling pendant lights (like the lab)
for x0, x1 in ((560, 800), (880, 1220)):
    a(f'<path d="M{x0+30} 0V16M{x1-30} 0V16" stroke="#6F83A6" stroke-width="1.5"/>')
    a(f'<rect x="{x0}" y="16" width="{x1-x0}" height="9" rx="3" fill="#F7FAFF" class="t"/>')

# whiteboard with course scribbles
a('<g>')
a(f'<rect x="572" y="50" width="452" height="136" rx="6" fill="#F4F6F9" class="o"/>')
a('<rect x="580" y="58" width="436" height="120" rx="3" fill="#FFFFFF"/>')
a(f'<rect x="700" y="186" width="200" height="7" rx="2" fill="#AAB3C0" class="t"/>')
hand = 'font-style="italic" font-weight="700"'
a(f'<text x="594" y="88" class="sans" font-size="19" fill="{ARCHES}" {hand}>u = K<tspan font-size="13" dy="4">p</tspan><tspan dy="-4"> e + K</tspan><tspan font-size="13" dy="4">i</tspan><tspan dy="-4"> ∫ e dt</tspan></text>')
a(f'<text x="594" y="118" class="sans" font-size="17" fill="{ALTGELD}" {hand}>ẋ = v cos θ,  ẏ = v sin θ</text>')
# PWM sketch
a(f'<path d="M594 162h10v-20h14v20h10v-20h14v20h10v-20h12" class="ln" stroke="{BLUE}" stroke-width="2.5"/>')
a(f'<text x="784" y="160" class="sans" font-size="14" fill="{BLUE}" {hand}>ePWM → ADC SOC</text>')
# top-down diff-drive sketch
a(f'<circle cx="925" cy="110" r="30" class="ln" stroke="{BLUE}" stroke-width="2.5"/>')
a(f'<path d="M897 96v28M953 96v28" class="ln" stroke="{BLUE}" stroke-width="5"/>')
a(f'<path d="M925 110h44m-9-6 9 6-9 6" class="ln" stroke="{ALTGELD}" stroke-width="2.5"/>')
a(f'<path d="M925 110l-18 -28" class="ln" stroke="{ARCHES}" stroke-width="2" stroke-dasharray="3 4"/>')
a(f'<text x="836" y="92" class="sans" font-size="17" fill="{ALTGELD}" {hand}>SLAM!</text>')
a('</g>')

# ---------------------------------------------------------------- floor
a(f'<rect x="0" y="540" width="{W}" height="{H-540}" fill="url(#floor)"/>')
a(f'<rect x="0" y="540" width="{W}" height="{H-540}" fill="url(#plate)"/>')
a(f'<path d="M0 540H{W}" stroke="#2A4677" stroke-width="2"/>')
# orange tape "L" corner marks from the arena floor
for x, y, s in ((610, 612, 1), (910, 592, -1), (470, 575, -1)):
    a(f'<path d="M{x} {y-12}v12h{14*s}" class="ln" stroke="{ORANGE}" stroke-width="4" opacity="0.85"/>')

# ---------------------------------------------------------------- student A (orange hoodie, probing the board)
def student_a(cx, cy):
    skin, skin_d, hair = "#8D5A3B", "#6E4229", "#1E140F"
    s = []
    # torso / hoodie
    s.append(f'<path d="M{cx-86} 400C{cx-90} 300 {cx-58} 262 {cx} 258C{cx+58} 262 {cx+90} 300 {cx+86} 400Z" fill="{ORANGE}" class="o"/>')
    s.append(f'<path d="M{cx+40} 272C{cx+70} 290 {cx+80} 330 {cx+80} 400H{cx+50}C{cx+56} 340 {cx+52} 300 {cx+40} 272Z" fill="{ALTGELD}" opacity="0.55"/>')
    # hood collar
    s.append(f'<path d="M{cx-46} 268C{cx-30} 292 {cx+30} 292 {cx+46} 268C{cx+30} 256 {cx-30} 256 {cx-46} 268Z" fill="{ALTGELD}" class="t"/>')
    s.append(f'<path d="M{cx-12} 286v34M{cx+12} 286v30" class="ln" stroke="#FFF3EA" stroke-width="3"/>')
    # neck + head
    s.append(f'<rect x="{cx-13}" y="{cy+30}" width="26" height="30" fill="{skin_d}" class="t"/>')
    s.append(f'<circle cx="{cx-41}" cy="{cy+4}" r="9" fill="{skin}" class="t"/>')
    s.append(f'<circle cx="{cx+41}" cy="{cy+4}" r="9" fill="{skin}" class="t"/>')
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="41" ry="45" fill="{skin}" class="o"/>')
    # curly hair (cluster of bumps)
    bumps = [(-34, -22, 13), (-22, -36, 15), (-4, -43, 16), (16, -40, 15), (32, -28, 13), (39, -12, 9), (-40, -8, 9)]
    for dx, dy, r in bumps:
        s.append(f'<circle cx="{cx+dx}" cy="{cy+dy}" r="{r}" fill="{hair}" class="t"/>')
    s.append(f'<path d="M{cx-38} {cy-16}C{cx-20} {cy-30} {cx+20} {cy-30} {cx+38} {cy-16}L{cx+34} {cy-36}H{cx-34}Z" fill="{hair}"/>')
    # face
    s.append(f'<path d="M{cx-24} {cy-8}q9-6 16-1M{cx+8} {cy-9}q8-5 16 1" class="ln" stroke="{hair}" stroke-width="3.5"/>')
    for ex in (cx - 15, cx + 15):
        s.append(f'<ellipse cx="{ex}" cy="{cy+5}" rx="5" ry="6.5" fill="{INK}"/><circle cx="{ex-2}" cy="{cy+2}" r="1.8" fill="#FFF"/>')
    s.append(f'<ellipse cx="{cx-26}" cy="{cy+18}" rx="7" ry="4" fill="#E0736A" opacity="0.5"/><ellipse cx="{cx+26}" cy="{cy+18}" rx="7" ry="4" fill="#E0736A" opacity="0.5"/>')
    s.append(f'<path d="M{cx-12} {cy+22}q12 13 24 0Z" fill="#5A1A14" class="t"/>')
    s.append(f'<path d="M{cx-8} {cy+24}h16" stroke="#FFF" stroke-width="3"/>')
    return "\n".join(s)

# ---------------------------------------------------------------- student B (blue hoodie, glasses, on the laptop)
def student_b(cx, cy):
    skin, skin_d, hair = "#F2C9A0", "#D9A87E", "#231A2E"
    s = []
    # hair behind head (long)
    s.append(f'<path d="M{cx-46} {cy}C{cx-54} {cy+50} {cx-50} {cy+80} {cx-38} {cy+96}H{cx+38}C{cx+50} {cy+80} {cx+54} {cy+50} {cx+46} {cy}Z" fill="{hair}" class="o"/>')
    # torso
    s.append(f'<path d="M{cx-86} 400C{cx-90} 300 {cx-58} 262 {cx} 258C{cx+58} 262 {cx+90} 300 {cx+86} 400Z" fill="{ARCHES}" class="o"/>')
    s.append(f'<path d="M{cx-40} 272C{cx-70} 290 {cx-80} 330 {cx-80} 400H{cx-50}C{cx-56} 340 {cx-52} 300 {cx-40} 272Z" fill="{BLUE}" opacity="0.45"/>')
    s.append(f'<path d="M{cx-46} 268C{cx-30} 292 {cx+30} 292 {cx+46} 268C{cx+30} 256 {cx-30} 256 {cx-46} 268Z" fill="{BLUE}" class="t"/>')
    # small orange chest stripe
    s.append(f'<path d="M{cx-86} 340C{cx-40} 348 {cx+40} 348 {cx+86} 340" class="ln" stroke="{ORANGE}" stroke-width="6"/>')
    # neck + head
    s.append(f'<rect x="{cx-12}" y="{cy+30}" width="24" height="30" fill="{skin_d}" class="t"/>')
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="40" ry="44" fill="{skin}" class="o"/>')
    # fringe + bun
    s.append(f'<circle cx="{cx+4}" cy="{cy-56}" r="17" fill="{hair}" class="o"/>')
    s.append(f'<path d="M{cx-42} {cy+8}C{cx-46} {cy-40} {cx+40} {cy-58} {cx+43} {cy-2}C{cx+30} {cy-20} {cx+4} {cy-26} {cx-12} {cy-18}C{cx-22} {cy-10} {cx-32} {cy-6} {cx-42} {cy+8}Z" fill="{hair}" class="o"/>')
    s.append(f'<path d="M{cx-6} {cy-60}q8 6 20 0" class="ln" stroke="{ORANGE}" stroke-width="4"/>')
    # eyes looking down at the laptop
    for ex in (cx - 15, cx + 15):
        s.append(f'<ellipse cx="{ex}" cy="{cy+9}" rx="4.5" ry="5" fill="{INK}"/><circle cx="{ex-1.5}" cy="{cy+7}" r="1.5" fill="#FFF"/>')
    # glasses
    s.append(f'<circle cx="{cx-15}" cy="{cy+7}" r="11" fill="#FFFFFF" fill-opacity="0.18" class="ln" stroke="{INK}" stroke-width="2.5"/>')
    s.append(f'<circle cx="{cx+15}" cy="{cy+7}" r="11" fill="#FFFFFF" fill-opacity="0.18" class="ln" stroke="{INK}" stroke-width="2.5"/>')
    s.append(f'<path d="M{cx-4} {cy+6}q4-3 8 0M{cx-26} {cy+5}l-13-3M{cx+26} {cy+5}l13-3" class="ln" stroke="{INK}" stroke-width="2.5"/>')
    s.append(f'<ellipse cx="{cx-25}" cy="{cy+24}" rx="7" ry="4" fill="#F08A8A" opacity="0.55"/><ellipse cx="{cx+25}" cy="{cy+24}" rx="7" ry="4" fill="#F08A8A" opacity="0.55"/>')
    s.append(f'<path d="M{cx-9} {cy+27}q9 8 18 0" class="ln" stroke="{INK}" stroke-width="3"/>')
    # screen glow on face
    s.append(f'<ellipse cx="{cx}" cy="{cy+30}" rx="60" ry="40" fill="url(#screenGlow)"/>')
    return "\n".join(s)

A_CX, B_CX = 720, 985
a(student_a(A_CX, 205))
a(student_b(B_CX, 208))

# ---------------------------------------------------------------- workbench
a('<g>')
a(f'<rect x="522" y="452" width="564" height="112" fill="#9A6532" class="o"/>')
for i, x in enumerate((536, 722, 908)):
    a(f'<rect x="{x}" y="466" width="164" height="38" rx="3" fill="#B07638" class="t"/>')
    a(f'<rect x="{x}" y="512" width="164" height="38" rx="3" fill="#B07638" class="t"/>')
    a(f'<rect x="{x+62}" y="480" width="40" height="7" rx="3.5" fill="#D6DCE4" class="t"/>')
    a(f'<rect x="{x+62}" y="526" width="40" height="7" rx="3.5" fill="#D6DCE4" class="t"/>')
a(f'<ellipse cx="804" cy="566" rx="300" ry="8" fill="#000" opacity="0.35"/>')
a(f'<path d="M526 392H1082L1098 440H510Z" fill="url(#oak)" class="o"/>')
for y, x0, x1 in ((404, 560, 700), (416, 780, 1000), (428, 540, 640), (400, 900, 1060)):
    a(f'<path d="M{x0} {y}C{(x0+x1)/2} {y-3} {(x0+x1)/2} {y+3} {x1} {y}" class="ln" stroke="#B9823F" stroke-width="1.6" opacity="0.7"/>')
a(f'<rect x="510" y="440" width="588" height="14" fill="#B8783A" class="o"/>')
# yellow ruler tape on the bench edge (like the lab benches)
a(f'<rect x="530" y="443" width="120" height="7" fill="#F2D541" opacity="0.9"/>')
a('</g>')

# ---------------------------------------------------------------- oscilloscope (back-left of bench)
a('<g>')
a(f'<path d="M540 318q0-12 30-12h10q30 0 30 12" class="ln" stroke="#2B3340" stroke-width="5"/>')
a(f'<rect x="520" y="316" width="112" height="82" rx="7" fill="#3A4556" class="o"/>')
a(f'<rect x="529" y="326" width="64" height="50" rx="3" fill="#07111F" class="t"/>')
for gx in range(537, 593, 12):
    a(f'<path d="M{gx} 327v48" stroke="#2C4C6E" stroke-width="0.8"/>')
for gy in range(335, 376, 10):
    a(f'<path d="M530 {gy}h62" stroke="#2C4C6E" stroke-width="0.8"/>')
a(f'<path d="M531 362h8v-18h12v18h8v-18h12v18h8v-18h12v18h2" class="ln" stroke="{ORANGE}" stroke-width="2.2"/>')
a(f'<path d="M531 350c8-14 16 14 24 0s16 14 24 0 10 8 13 4" class="ln" stroke="#5FD0FF" stroke-width="1.8"/>')
for kx, ky, r in ((606, 334, 7), (622, 334, 5), (606, 356, 5), (622, 356, 7)):
    a(f'<circle cx="{kx}" cy="{ky}" r="{r}" fill="#C7CED8" class="t"/>')
for bx in range(531, 591, 12):
    a(f'<rect x="{bx}" y="382" width="9" height="6" rx="1.5" fill="#8E9AAB"/>')
a(f'<circle cx="614" cy="382" r="4" fill="#FFC857" class="t"/><circle cx="626" cy="382" r="4" fill="#5FD0FF" class="t"/>')
a('</g>')

# ---------------------------------------------------------------- laptop (lid back towards viewer)
a('<g>')
a(f'<path d="M898 396H1074L1082 406H890Z" fill="#AEB6C2" class="t"/>')
a(f'<rect x="908" y="312" width="156" height="88" rx="9" fill="#CDD3DC" class="o"/>')
a(f'<path d="M918 322h60" class="ln" stroke="#FFFFFF" stroke-width="3" opacity="0.8"/>')
# stickers
a(f'<circle cx="962" cy="356" r="17" fill="{ORANGE}" class="t"/>')
a(f'<text x="962" y="362" text-anchor="middle" class="mono" font-size="16" font-weight="700" fill="#FFF">{{ }}</text>')
a(f'<rect x="992" y="336" width="54" height="24" rx="5" fill="{BLUE}" class="t" transform="rotate(-8 1019 348)"/>')
a(f'<text x="1019" y="353" text-anchor="middle" class="sans" font-size="12" font-weight="800" fill="#FFF" transform="rotate(-8 1019 348)">SE 423</text>')
a(f'<g transform="rotate(10 1030 382)"><rect x="1016" y="372" width="28" height="20" rx="4" fill="#E8E9EB" class="t"/><circle cx="1025" cy="382" r="3" fill="{INK}"/><circle cx="1035" cy="382" r="3" fill="{INK}"/></g>')
a('</g>')

# ---------------------------------------------------------------- the red + green board (TI LaunchPad on the SE 423 breakout)
def board():
    s = []
    BW, BH = 280, 160
    s.append(f'<rect x="4" y="6" width="{BW}" height="{BH}" rx="8" fill="#000" opacity="0.3"/>')  # shadow
    s.append(f'<rect width="{BW}" height="{BH}" rx="8" fill="#1E8A4A" class="o"/>')
    # traces
    for d in ("M20 30h40l12 12h20", "M20 130h60l14-14h30", "M200 138h40l10-10v-40", "M236 22v30l-10 10",
              "M40 60v40l10 10h14", "M150 140h30", "M256 70h14"):
        s.append(f'<path d="{d}" class="ln" stroke="#35B26A" stroke-width="2.4" opacity="0.8"/>')
    # mounting holes
    for hx, hy in ((12, 12), (BW-12, 12), (12, BH-12), (BW-12, BH-12)):
        s.append(f'<circle cx="{hx}" cy="{hy}" r="6" fill="#E3B341" class="t"/><circle cx="{hx}" cy="{hy}" r="2.6" fill="{INK}"/>')
    # serial DB-9 on the left edge
    s.append(f'<path d="M-6 58h22v44H-6l-6-6V64Z" fill="#C3CAD3" class="t"/>')
    s.append(f'<rect x="-2" y="68" width="12" height="24" rx="3" fill="#6B7684"/>')
    # green screw terminals
    for i in range(3):
        s.append(f'<rect x="{26+i*22}" y="{BH-40}" width="18" height="16" rx="2" fill="#2FCB7A" class="t"/><circle cx="{35+i*22}" cy="{BH-32}" r="3.5" fill="#9AA4B1" stroke="{INK}" stroke-width="1.2"/>')
    # white JST connector
    s.append(f'<rect x="232" y="104" width="30" height="24" rx="2" fill="#F4F4F0" class="t"/><rect x="238" y="110" width="18" height="10" fill="#C9C9C2"/>')
    # buzzer
    s.append(f'<circle cx="248" cy="46" r="13" fill="#1F1F24" class="t"/><circle cx="248" cy="46" r="3" fill="#555"/>')
    # blue IMU breakout
    s.append(f'<rect x="184" y="118" width="36" height="28" rx="3" fill="{ARCHES}" class="t"/><rect x="196" y="126" width="12" height="12" fill="#111"/>')
    # male header row along bottom
    s.append(f'<rect x="92" y="{BH-20}" width="84" height="10" fill="#15151A"/>')
    for i in range(12):
        s.append(f'<rect x="{95+i*7}" y="{BH-18}" width="3" height="6" fill="#E3B341"/>')
    s.append(f'<text x="30" y="24" class="sans" font-size="9" font-weight="700" fill="#EAF7EE" letter-spacing="1">SE423 BREAKOUT</text>')
    # red LaunchPad
    LX, LY, LW, LH = 70, 34, 158, 78
    s.append(f'<rect x="{LX+3}" y="{LY+4}" width="{LW}" height="{LH}" rx="4" fill="#000" opacity="0.35"/>')
    s.append(f'<rect x="{LX}" y="{LY}" width="{LW}" height="{LH}" rx="4" fill="#C8102E" class="o"/>')
    for hy in (LY + 4, LY + LH - 14):
        s.append(f'<rect x="{LX+22}" y="{hy}" width="{LW-30}" height="10" rx="1" fill="#17171C"/>')
        for i in range(18):
            s.append(f'<rect x="{LX+25+i*7}" y="{hy+3.5}" width="3" height="3" fill="#6E6E78"/>')
    # USB + debug side
    s.append(f'<rect x="{LX-10}" y="{LY+27}" width="20" height="18" rx="2" fill="#D5DAE1" class="t"/>')
    s.append(f'<rect x="{LX+14}" y="{LY+22}" width="16" height="16" fill="#1A1A1F"/>')
    # MCU (QFP) with pins
    mx, my = LX + 74, LY + 22
    for i in range(6):
        s.append(f'<rect x="{mx+4+i*6}" y="{my-4}" width="2.5" height="4" fill="#C9CED6"/><rect x="{mx+4+i*6}" y="{my+34}" width="2.5" height="4" fill="#C9CED6"/>')
        s.append(f'<rect x="{mx-4}" y="{my+4+i*5}" width="4" height="2.5" fill="#C9CED6"/><rect x="{mx+34}" y="{my+4+i*5}" width="4" height="2.5" fill="#C9CED6"/>')
    s.append(f'<rect x="{mx}" y="{my}" width="34" height="34" rx="2" fill="#1C1C22" class="t"/>')
    s.append(f'<circle cx="{mx+6}" cy="{my+6}" r="2" fill="#3A3A44"/>')
    # buttons + LEDs
    s.append(f'<rect x="{LX+36}" y="{LY+44}" width="11" height="11" rx="2" fill="#E8E8E8" class="t"/><circle cx="{LX+41.5}" cy="{LY+49.5}" r="2.5" fill="#333"/>')
    s.append(f'<circle cx="{LX+134}" cy="{LY+30}" r="3.5" fill="#FF3B3B"/><circle cx="{LX+134}" cy="{LY+30}" r="7" fill="#FF3B3B" opacity="0.3"/>')
    s.append(f'<circle cx="{LX+134}" cy="{LY+44}" r="3.5" fill="#4FA8FF"/><circle cx="{LX+134}" cy="{LY+44}" r="7" fill="#4FA8FF" opacity="0.3"/>')
    s.append(f'<text x="{LX+120}" y="{LY+64}" class="sans" font-size="7.5" font-weight="700" fill="#FFD9DE">F28379D</text>')
    # jumper wires arcing over the board
    for d, c in (("M150 36C150 0 238 -2 246 34", "#F2D541"), ("M176 36C184 8 222 10 232 108", "#3E7BFF"),
                 ("M104 112C110 146 60 150 44 124", "#FF4D4D"), ("M198 112C204 150 236 150 244 128", "#F2D541")):
        s.append(f'<path d="{d}" class="ln" stroke="{INK}" stroke-width="5.5"/><path d="{d}" class="ln" stroke="{c}" stroke-width="3"/>')
    return "\n".join(s)

# oblique projection: board lying tilted back on the bench
a(f'<g transform="matrix(1 0 -0.22 0.72 640 306)">{board()}</g>')

# USB cable board -> laptop
usb = "M902 368C918 392 900 404 926 402"
a(f'<path d="{usb}" class="ln" stroke="{INK}" stroke-width="7"/><path d="{usb}" class="ln" stroke="#5B6574" stroke-width="3.5"/>')

# student A's arm holding the scope probe on the header pins
probe = "M626 384C636 420 656 414 662 398"
a(f'<path d="{probe}" class="ln" stroke="{INK}" stroke-width="6"/><path d="{probe}" class="ln" stroke="#2C323C" stroke-width="3"/>')
arm = "M656 296Q636 350 676 386"
a(f'<path d="{arm}" class="ln" stroke="{INK}" stroke-width="27"/><path d="{arm}" class="ln" stroke="{ORANGE}" stroke-width="20"/>')
a(f'<path d="M652 306Q640 346 656 366" class="ln" stroke="{ALTGELD}" stroke-width="5" opacity="0.5"/>')
a(f'<rect x="660" y="384" width="30" height="9" rx="4" transform="rotate(35 675 388)" fill="#2C323C" class="t"/>')
a(f'<path d="M663 394l-8 9" class="ln" stroke="#C9CED6" stroke-width="3"/>')
a(f'<path d="M662 372l10 18" class="ln" stroke="{INK}" stroke-width="11"/><path d="M662 372l10 18" class="ln" stroke="{ALTGELD}" stroke-width="6"/>')
a(f'<ellipse cx="682" cy="386" rx="13" ry="11" fill="#8D5A3B" class="o"/>')

# ---------------------------------------------------------------- LiDAR "ping" rings
LX, LY = 1152, 326
for r, op in ((70, 0.9), (100, 0.55), (130, 0.28)):
    a(f'<path d="M{LX-r*0.866:.1f} {LY-r*0.5:.1f}A{r} {r} 0 0 0 {LX-r*0.866:.1f} {LY+r*0.5:.1f}" class="ln" stroke="{ORANGE}" stroke-width="4" opacity="{op}"/>')
# scan hits on the bench front


# ---------------------------------------------------------------- robot
def robot():
    s = []
    s.append(f'<ellipse cx="1156" cy="624" rx="118" ry="10" fill="#000" opacity="0.45"/>')
    # mocap arch frame (behind everything)
    for x in (1064, 1240):
        s.append(f'<rect x="{x}" y="282" width="11" height="286" fill="url(#alu)" class="t"/>')
    rods = ((1082, 272, 1082, 214), (1168, 272, 1172, 196), (1234, 272, 1244, 224), (1066, 284, 1030, 262))
    for x0, y0, x1, y1 in rods:
        s.append(f'<path d="M{x0} {y0}L{x1} {y1}" class="ln" stroke="{INK}" stroke-width="5"/><path d="M{x0} {y0}L{x1} {y1}" class="ln" stroke="#B7BFCA" stroke-width="2.5"/>')
    s.append(f'<rect x="1052" y="268" width="206" height="22" rx="3" fill="#1C1D22" class="o"/>')
    s.append(f'<rect x="1054" y="270" width="30" height="18" fill="#E4F04B"/><rect x="1226" y="270" width="30" height="18" fill="#E4F04B"/>')
    s.append(f'<path d="M1130 270h40l-6 18h-40Z" fill="#9BA3AE" opacity="0.9"/>')
    for _, _, x1, y1 in rods:
        s.append(f'<circle cx="{x1}" cy="{y1}" r="11" fill="url(#ball)" class="t"/>')
    # wheels
    for x in (1046, 1236):
        s.append(f'<rect x="{x}" y="556" width="30" height="66" rx="11" fill="#1A1B20" class="o"/>')
        for ty in range(566, 616, 9):
            s.append(f'<path d="M{x+5} {ty}l6 4 6-4 6 4" class="ln" stroke="#3B3D46" stroke-width="2"/>')
    # aluminium chassis
    s.append(f'<rect x="1072" y="536" width="166" height="56" rx="4" fill="#C3CAD3" class="o"/>')
    s.append(f'<rect x="1072" y="536" width="166" height="12" fill="#E3E7EC" opacity="0.8"/>')
    for rx in (1084, 1226):
        s.append(f'<circle cx="{rx}" cy="580" r="3" fill="#8A94A1"/>')
    # white acrylic skirt + velcro
    s.append(f'<path d="M1080 584H1230L1244 608H1066Z" fill="#EEF1F4" class="o"/>')
    for vx in (1090, 1140, 1190):
        s.append(f'<path d="M{vx} 590h30l2 12h-34Z" fill="url(#velcro)"/>')
    # bumper
    s.append(f'<path d="M1054 594V616Q1054 622 1062 622H1250Q1258 622 1258 616V594" class="ln" stroke="{INK}" stroke-width="8"/>')
    s.append(f'<path d="M1054 594V616Q1054 622 1062 622H1250Q1258 622 1258 616V594" class="ln" stroke="#2E3038" stroke-width="4"/>')
    # standoffs
    for x in (1090, 1220):
        s.append(f'<rect x="{x}" y="404" width="7" height="134" fill="url(#alu)" class="t"/>')
    # lower amp board
    s.append(f'<rect x="1082" y="468" width="146" height="70" rx="3" fill="#1E8A4A" class="o"/>')
    s.append(f'<path d="M1090 530h40l8-8h20M1200 476v30" class="ln" stroke="#35B26A" stroke-width="2"/>')
    for bx in (1168, 1200):
        s.append(f'<rect x="{bx}" y="476" width="26" height="46" rx="2" fill="#16171B" class="t"/>')
        s.append(f'<text x="{bx+13}" y="503" text-anchor="middle" class="sans" font-size="11" font-weight="800" fill="#FFF">5V</text>')
    # character LCD
    s.append(f'<rect x="1090" y="480" width="70" height="32" rx="3" fill="#1C2A1A" class="t"/>')
    s.append(f'<rect x="1095" y="485" width="60" height="22" fill="#B9D63A"/>')
    s.append(f'<text x="1125" y="501" text-anchor="middle" class="mono" font-size="12" font-weight="700" fill="#27340C">SE 423</text>')
    # mid deck + mini red/green board stack
    s.append(f'<rect x="1072" y="454" width="166" height="12" rx="2" fill="#1C1D22" class="o"/>')
    s.append(f'<rect x="1098" y="440" width="96" height="14" fill="#1E8A4A" class="t"/>')
    s.append(f'<rect x="1112" y="430" width="62" height="12" fill="#C8102E" class="t"/>')
    s.append(f'<path d="M1180 440c10-6 22-2 24 14" class="ln" stroke="#D5D8DE" stroke-width="5"/>')
    # upper white deck
    s.append(f'<rect x="1080" y="398" width="152" height="10" rx="2" fill="#EEF1F4" class="o"/>')
    # serial board top-left
    s.append(f'<rect x="1082" y="370" width="38" height="28" rx="2" fill="#1E8A4A" class="t"/>')
    s.append(f'<rect x="1088" y="378" width="16" height="12" rx="2" fill="#C3CAD3" class="t"/>')
    # LiDAR body
    s.append(f'<rect x="1124" y="346" width="56" height="52" rx="3" fill="#DADFE5" class="o"/>')
    s.append(f'<rect x="1130" y="372" width="30" height="14" fill="#F5D90A" class="t"/>')
    s.append(f'<path d="M1134 377h22M1134 381h16" stroke="{INK}" stroke-width="1.4"/>')
    # LiDAR head (black cylinder) with cartoon eyes
    s.append(f'<rect x="1128" y="298" width="48" height="52" rx="5" fill="#15161A" class="o"/>')
    s.append(f'<rect x="1128" y="314" width="48" height="20" fill="#4A0F14" opacity="0.8"/>')
    s.append(f'<ellipse cx="1152" cy="298" rx="24" ry="6" fill="#2A2C33" class="t"/>')
    s.append(f'<ellipse cx="1152" cy="297" rx="12" ry="3" fill="{ARCHES}"/>')
    for ex in (1139, 1165):
        s.append(f'<ellipse cx="{ex}" cy="318" rx="12" ry="15" fill="#FFFFFF" class="o"/>')
        s.append(f'<circle cx="{ex-5}" cy="320" r="6.5" fill="{INK}"/><circle cx="{ex-7}" cy="317" r="2.2" fill="#FFF"/>')
    # camera (red board + lens)
    s.append(f'<rect x="1182" y="362" width="36" height="34" rx="3" fill="#D2362B" class="o"/>')
    s.append(f'<circle cx="1200" cy="379" r="12" fill="#C9CED6" class="t"/><circle cx="1200" cy="379" r="7.5" fill="#1B2230"/><circle cx="1197" cy="376" r="2.2" fill="#9CD3FF"/>')
    # yellow wire bundle + twisted pairs
    for dx in (0, 4, 8):
        s.append(f'<path d="M{1214+dx} 364C{1250+dx} 350 {1256+dx} 420 {1222+dx} 440" class="ln" stroke="{INK}" stroke-width="3.6"/>')
        s.append(f'<path d="M{1214+dx} 364C{1250+dx} 350 {1256+dx} 420 {1222+dx} 440" class="ln" stroke="#F2D541" stroke-width="2"/>')
    s.append(f'<path d="M1100 408c-14 20 14 30 0 50" class="ln" stroke="#E23B3B" stroke-width="2.5"/>')
    s.append(f'<path d="M1104 408c14 20-14 30 0 50" class="ln" stroke="#3E7BFF" stroke-width="2.5"/>')
    return "\n".join(s)

a(robot())

# ---------------------------------------------------------------- title block
a('<g>')
a(f'<rect x="60" y="92" width="232" height="32" rx="16" fill="{ORANGE}"/>')
a(f'<text x="176" y="114" text-anchor="middle" class="sans" font-size="15" font-weight="800" fill="{BLUE}" letter-spacing="2">UIUC · SPRING 2026</text>')
a(f'<text x="56" y="240" class="sans" font-size="124" font-weight="900" fill="#FFFFFF" letter-spacing="-2">SE <tspan fill="{ORANGE}">423</tspan></text>')
a(f'<text x="62" y="292" class="sans" font-size="34" font-weight="600" fill="#C9D6EA">Introduction to</text>')
a(f'<text x="60" y="346" class="sans" font-size="54" font-weight="800" fill="#FFFFFF">Mechatronics</text>')
a(f'<rect x="62" y="366" width="96" height="6" rx="3" fill="{ORANGE}"/>')
a(f'<text x="62" y="404" class="sans" font-size="19" font-weight="600" fill="#C9D6EA">University of Illinois Urbana-Champaign</text>')
x = 62
for chip in ("Embedded C", "TI C2000", "Control", "LiDAR SLAM"):
    w = 18 + len(chip) * 8.6
    a(f'<rect x="{x}" y="428" width="{w:.0f}" height="30" rx="15" fill="#FFFFFF" fill-opacity="0.06" stroke="{ORANGE}" stroke-width="2"/>')
    a(f'<text x="{x+w/2:.0f}" y="448" text-anchor="middle" class="sans" font-size="14.5" font-weight="700" fill="#FFFFFF">{chip}</text>')
    x += w + 10
a(f'<text x="62" y="598" class="mono" font-size="14" fill="#8FA3C2">github.com/Marius-Juston/SE-423---Class-Material</text>')
a('</g>')

# signature
a(f'<text x="1010" y="628" text-anchor="end" class="sans" font-size="13" font-style="italic" font-weight="700" fill="{ORANGE}" opacity="0.9">drawn by Claude ✎</text>')

a('</svg>\n')

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(p))
print("wrote", OUT)
