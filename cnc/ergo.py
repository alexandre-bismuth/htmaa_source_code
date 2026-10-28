#!/usr/bin/env python3
"""Ergonomic side view of the sim rig: rig profile + chair + seated mannequins.

All numbers in mm, x from the pedal end toward the driver, z up from the floor.
Segment lengths come from stature (Drillis & Contini fractions). Posture inputs:
H-point, torso recline, thigh angle, ankle angle. The shank angle is solved so the
heel lands on the pedal deck. Prints the resulting joint angles and clearances and
writes ergo_side_view.svg.

Run:  python3 ergo.py            (defaults: 192 cm driver, 177 cm check with the chair 80 mm forward)
PNG:  rsvg-convert -w 2300 ergo_side_view.svg -o ergo_side_view.png   (Homebrew librsvg; Quick Look crops SVGs)
"""
import math, sys

# ---------------- rig (placeholders, edit here; rig.py will import these later)
T = 11.4                 # rig = 7/16 in OSB (0.45 in placeholder); chair + wheel deck + handbrake = 3/4 in plywood, see T_PLY
T_PLY = 18.0             # plywood parts
L = 1600                 # plate rear end at x = L
FRONT = 200              # plate front edge (plates are L - FRONT = 1400 long)
B, H = 190, 670          # base height, deck top
DECK0, DECK1 = 450, 990  # wheel/display deck, front and rear edge
REAR_BASE = 1260         # knee diagonal reaches the base line z = B here (window reference)
SEAT_TOP = 230           # plate top behind the knee diagonal: 60 mm of OSB above the chair bolts at z 170 (was 190)
DECK_TABS = [(510.0, 570.0), (600.0, 660.0), (780.0, 840.0), (870.0, 930.0)]   # wheel deck tabs in closed slots under the plate's top lip (glue-free); each 150 mm slot split in two by a 30 mm bridge so the 25 mm lip spans 60, not 150 (user, Fri 10/23)
DECK_EAR = 25.0          # plate top runs this far above the deck top, straight from diagonal to diagonal (a lip over the deck slots)
DECK_EAR_MARGIN = 0.0    # (no separate ears any more)
TIE_RODS = [(600.0, 590.0), (925.0, 100.0)]    # M8 threaded rods across the tower, clamp the plates onto the member shoulders
FOOT_TOP = 210           # plate height at the front (footbox diagonal starts here)
PED_HEEL_X, PED_HEEL_Z = 720, 15   # pedal deck heel end (bottom face); moved back 100 with the chair for the 11 deg backrest
PED_LEN, PED_ANG = 480, math.radians(22.5)
DASH_RIB = (DECK0 + T, 100)        # x, depth under the deck
DECK_RIB = (720, 80)
TIES = [800, 1050]                 # floor ties, 80 tall
BEAMS = [1280, 1560]               # seat beams, 89 tall, bottom at 60
FRAME = 150              # uniform frame width around the window, measured perpendicular to each edge
def foot_diag_x(z):      # footbox diagonal, from (FRONT+80, FOOT_TOP) up to (DECK0, H)
    return FRONT + 80 + (z - FOOT_TOP) * (DECK0 - FRONT - 80) / (H - FOOT_TOP)
def knee_diag_x(z):      # knee diagonal, from (DECK1, H) down to (REAR_BASE, B)
    return DECK1 + (H - z) * (REAR_BASE - DECK1) / (H - B)
def window():
    """Inward offset of the tower outline (base line z=B, both diagonals, deck edge z=H) by FRAME:
    every window edge is parallel to the plate edge it faces, at the same perpendicular distance."""
    a_f = math.atan2(H - FOOT_TOP, DECK0 - FRONT - 80)     # footbox diagonal angle from horizontal
    a_k = math.atan2(H - B, REAR_BASE - DECK1)             # knee diagonal angle
    z0, z1 = B + FRAME, H - FRAME
    dx_f, dx_k = FRAME / math.sin(a_f), FRAME / math.sin(a_k)   # horizontal offsets that give FRAME perpendicular
    return [[foot_diag_x(z0) + dx_f, z0], [knee_diag_x(z0) - dx_k, z0], [knee_diag_x(z1) - dx_k, z1], [foot_diag_x(z1) + dx_f, z1]]
WIN = window()
# chair (Liu-style profile, placeholder; drawn relative to CHAIR_X = front of its base)
# pan tilts up 2 deg (front 237, rear 226 above the floor), backrest 11 deg from vertical. The hip joint (H-point) sits ~90 mm above a hard
# pan with a folded blanket (audit Thu night: 52 mm was too low), so the pan was lowered 38 mm and the backrest lengthened to keep its top at 853.
CHAIR = [(0, 149), (20, 237), (330, 226), (451.4, 853), (489.4, 859), (512.4, 835), (418, 335), (370, 149)]   # pan 237 front / 226 rear = 2 deg up
HIP_ABOVE_PAN = 90       # hip joint above the hard pan top (verify.py checks the chair against it)
CHAIR_X = 1230
# hardware
WHEEL = (1034, 745, 140)           # wheel plane x, centre z, radius
WHEELBASE = (734, 954, 670, 820)   # x0, x1, z0, z1
DISPLAY_X, DISP_BOTTOM, DISP_H = 560, 670 + 110, 362   # panel plane, bottom edge, panel height
PEDAL_PAD_UP = 150                 # pad height above the pivot on the pedal arm (ilge pedals, approx.)

def deck_surface_z(x):
    """Top surface of the pedal deck at x, or None if x is off the deck."""
    toe_x = PED_HEEL_X - PED_LEN * math.cos(PED_ANG)
    if x < toe_x or x > PED_HEEL_X:
        return None
    return PED_HEEL_Z + T / math.cos(PED_ANG) + (PED_HEEL_X - x) * math.tan(PED_ANG)   # top face, thickness normal to the deck

def ang(u, v):
    """Interior angle between vectors u and v, degrees."""
    d = (u[0]*v[0] + u[1]*v[1]) / (math.hypot(*u) * math.hypot(*v))
    return math.degrees(math.acos(max(-1, min(1, d))))

def mannequin(stature, hip, recline_deg=11, thigh_deg=15, ankle_deg=95):
    """Returns joint points and derived numbers for a driver of this stature seated at hip (H-point)."""
    S = stature
    thigh, shank, foot = 0.245*S, 0.246*S, 0.152*S
    torso, uarm, farm = 0.288*S, 0.186*S, 0.146*S
    eye_up, head_r = 0.118*S, 0.065*S
    rec, th = math.radians(recline_deg), math.radians(thigh_deg)
    knee = (hip[0] - thigh*math.cos(th), hip[1] + thigh*math.sin(th))
    # solve shank angle so the heel (20 behind, 75 below the ankle) sits on the pedal deck
    def heel_gap(sig):
        a = (knee[0] - shank*math.cos(sig), knee[1] - shank*math.sin(sig))
        heel = (a[0] + 20, a[1] - 75)
        zs = deck_surface_z(heel[0])
        return (heel[1] - zs) if zs is not None else None, a, heel
    lo, hi = math.radians(15), math.radians(85)
    best = None
    for _ in range(60):
        mid = (lo + hi) / 2
        g, a, heel = heel_gap(mid)
        if g is None:            # heel off the deck: behind the heel end -> flatter shank; ahead of the toe -> steeper
            if heel[0] > PED_HEEL_X: hi = mid
            else: lo = mid
            continue
        best = (mid, a, heel, g)
        if g > 0: lo = mid       # heel above the deck: steeper shank lowers it
        else: hi = mid
    if best is None:
        raise SystemExit(f"heel never reaches the pedal deck for hip {hip}: move the hip or the deck")
    sig, ankle, heel, gap = best
    # foot: from the heel, ankle angle between shank (ankle->knee) and foot (heel->ball)
    shank_dir = math.atan2(knee[1] - ankle[1], knee[0] - ankle[0])
    foot_dir = shank_dir + math.radians(ankle_deg)
    ball = (heel[0] + 0.68*foot*math.cos(foot_dir), heel[1] + 0.68*foot*math.sin(foot_dir))
    toe = (heel[0] + foot*math.cos(foot_dir), heel[1] + foot*math.sin(foot_dir))
    shoulder = (hip[0] + torso*math.sin(rec), hip[1] + torso*math.cos(rec))
    head_c = (shoulder[0] - 0.02*S, shoulder[1] + eye_up + 0.02*S)
    eye = (head_c[0] - 0.045*S, shoulder[1] + eye_up)
    # arm to the wheel centre, elbow below the shoulder-wheel line
    W = (WHEEL[0], WHEEL[1])
    d = math.hypot(W[0] - shoulder[0], W[1] - shoulder[1])
    cos_e = (uarm**2 + farm**2 - d**2) / (2*uarm*farm)
    elbow_deg = math.degrees(math.acos(max(-1, min(1, cos_e)))) if abs(cos_e) <= 1 else None
    if elbow_deg is not None:
        # elbow position: intersection of two circles, pick the lower one
        ax = (uarm**2 - farm**2 + d**2) / (2*d)
        hh = math.sqrt(max(0, uarm**2 - ax**2))
        ux, uz = (W[0] - shoulder[0]) / d, (W[1] - shoulder[1]) / d
        px, pz = shoulder[0] + ax*ux, shoulder[1] + ax*uz
        e1 = (px + hh*uz, pz - hh*ux); e2 = (px - hh*uz, pz + hh*ux)
        elbow = e1 if e1[1] < e2[1] else e2
    else:
        elbow = None
    knee_deg = ang((hip[0]-knee[0], hip[1]-knee[1]), (ankle[0]-knee[0], ankle[1]-knee[1]))
    disp_c = (DISPLAY_X, DISP_BOTTOM + DISP_H/2)
    gaze = math.degrees(math.atan2(eye[1] - disp_c[1], eye[0] - disp_c[0]))
    pad_z_above_deck = ball[1] - (deck_surface_z(ball[0]) or 0)
    # clearances
    knee_top = knee[1] + 0.03*S
    under_deck = H - T_PLY - (DECK_RIB[1] if abs(knee[0] - DECK_RIB[0]) < 60 else 0)   # plywood deck underside
    shank_at_tie = []
    for tx in TIES:
        if ankle[0] <= tx <= knee[0]:
            zt = ankle[1] + (tx - ankle[0]) * (knee[1] - ankle[1]) / (knee[0] - ankle[0])
            shank_at_tie.append((tx, zt - 80))
    return dict(S=S, hip=hip, knee=knee, ankle=ankle, heel=heel, ball=ball, toe=toe, shoulder=shoulder, head_c=head_c,
                head_r=head_r, eye=eye, elbow=elbow, elbow_deg=elbow_deg, knee_deg=knee_deg, thigh_deg=thigh_deg,
                shank_deg=math.degrees(sig), reach=d, gaze_down=gaze, eye_to_screen=math.hypot(eye[0]-disp_c[0], eye[1]-disp_c[1]),
                pad_above_deck=pad_z_above_deck, heel_gap=gap, knee_clear=under_deck - knee_top, shank_tie_clear=shank_at_tie,
                wheel_above_hip=W[1] - hip[1], wheel_fwd_of_hip=hip[0] - W[0])

def report(m, label):
    print(f"== {label}: stature {m['S']:.0f} mm, H-point ({m['hip'][0]:.0f}, {m['hip'][1]:.0f})")
    print(f"   knee ({m['knee'][0]:.0f},{m['knee'][1]:.0f}) angle {m['knee_deg']:.0f} deg | shank {m['shank_deg']:.0f} deg from horizontal | heel ({m['heel'][0]:.0f},{m['heel'][1]:.0f}) on deck (gap {m['heel_gap']:.1f})")
    print(f"   pedal pad (ball of foot) at ({m['ball'][0]:.0f},{m['ball'][1]:.0f}), {m['pad_above_deck']:.0f} mm above the deck surface")
    print(f"   shoulder ({m['shoulder'][0]:.0f},{m['shoulder'][1]:.0f}) | reach to wheel {m['reach']:.0f} | elbow {m['elbow_deg'] and round(m['elbow_deg'])} deg | wheel {m['wheel_above_hip']:.0f} above and {m['wheel_fwd_of_hip']:.0f} forward of the H-point")
    print(f"   eye ({m['eye'][0]:.0f},{m['eye'][1]:.0f}) | eye to screen centre {m['eye_to_screen']:.0f} mm, gaze {m['gaze_down']:.1f} deg down")
    print(f"   knee top clearance under deck/rib {m['knee_clear']:.0f} mm | shank over floor ties: " + ", ".join(f"x={t:.0f}: {c:.0f} mm" for t, c in m['shank_tie_clear']))

# ---------------- svg
def svg(men, path, extra=(), notes=(), draw_chair=True):
    """extra: [(points in rig mm, svg style)] drawn over the rig (chair.py adds the real chair and the handbrake box)."""
    W_, H_ = 2300, 1620 + 45 * len(notes)
    BOT = 220 + 45 * len(notes)   # bottom margin below the floor, mm
    sc = 0.5
    def P(x, z): return f"{(x+150)*sc:.1f},{(H_-BOT-z)*sc:.1f}"
    def poly(pts, style): return f'<polygon points="{" ".join(P(*p) for p in pts)}" style="{style}"/>'
    def line(a, b, style): return f'<line x1="{P(*a).split(",")[0]}" y1="{P(*a).split(",")[1]}" x2="{P(*b).split(",")[0]}" y2="{P(*b).split(",")[1]}" style="{style}"/>'
    def pl(pts, style): return f'<polyline points="{" ".join(P(*p) for p in pts)}" style="{style}"/>'
    def circ(c, r, style): x, y = P(*c).split(","); return f'<circle cx="{x}" cy="{y}" r="{r*sc:.1f}" style="{style}"/>'
    def text(x, z, s, size=26, anchor="start", fill="#333"):
        px, py = P(x, z).split(","); return f'<text x="{px}" y="{py}" font-size="{size*sc:.1f}" text-anchor="{anchor}" fill="{fill}" font-family="Helvetica, Arial, sans-serif">{s}</text>'
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_*sc:.0f}" height="{H_*sc:.0f}" viewBox="0 0 {W_*sc:.0f} {H_*sc:.0f}">',
           f'<rect width="100%" height="100%" fill="#f7f5f0"/>']
    # floor + grid every 100 mm
    for gx in range(0, 2100, 100):
        out.append(line((gx, 0), (gx, 1350), "stroke:#e4e0d8;stroke-width:0.6"))
    for gz in range(0, 1400, 100):
        out.append(line((0, gz), (2100, gz), "stroke:#e4e0d8;stroke-width:0.6"))
    out.append(line((-100, 0), (2100, 0), "stroke:#555;stroke-width:1.5"))
    # rig profile
    top = H + DECK_EAR
    prof = [(FRONT+60, 0), (L, 0), (L, SEAT_TOP), (knee_diag_x(SEAT_TOP), SEAT_TOP), (knee_diag_x(top), top), (foot_diag_x(top), top), (FRONT+80, FOOT_TOP), (FRONT, FOOT_TOP), (FRONT, 60)]
    out.append(poly(prof, "fill:#d9b97a;fill-opacity:0.55;stroke:#8a6a2a;stroke-width:1.2"))
    out.append(poly(WIN, "fill:#f7f5f0;stroke:#8a6a2a;stroke-width:1"))
    for rx, rz in TIE_RODS:
        out.append(circ((rx, rz), 9, "fill:#555;stroke:#222;stroke-width:1"))
    # decks, ribs, ties, beams
    out.append(poly([(DECK0, H-T_PLY), (DECK1, H-T_PLY), (DECK1, H), (DECK0, H)], "fill:#d9c08f;stroke:#6b4e1b;stroke-width:1"))
    for x, dpt in (DASH_RIB, DECK_RIB):
        out.append(poly([(x-T/2, H-T_PLY-dpt), (x+T/2, H-T_PLY-dpt), (x+T/2, H-T_PLY), (x-T/2, H-T_PLY)], "fill:#c49a52;stroke:#6b4e1b;stroke-width:1"))
    for x in TIES:
        out.append(poly([(x-T/2, 0), (x+T/2, 0), (x+T/2, 80), (x-T/2, 80)], "fill:#c49a52;stroke:#6b4e1b;stroke-width:1"))
    for x in BEAMS:
        out.append(poly([(x-T/2, 60), (x+T/2, 60), (x+T/2, 149), (x-T/2, 149)], "fill:#c49a52;stroke:#6b4e1b;stroke-width:1"))
    c, s_ = math.cos(PED_ANG), math.sin(PED_ANG)
    hx, hz = PED_HEEL_X, PED_HEEL_Z
    ped = [(hx, hz), (hx - PED_LEN*c, hz + PED_LEN*s_), (hx - PED_LEN*c + T*s_, hz + PED_LEN*s_ + T*c), (hx + T*s_, hz + T*c)]
    out.append(poly(ped, "fill:#c49a52;stroke:#6b4e1b;stroke-width:1"))
    # chair
    if draw_chair:
        out.append(poly([(CHAIR_X + x, z) for x, z in CHAIR], "fill:#b07a3a;fill-opacity:0.45;stroke:#6b4e1b;stroke-width:1.2"))
    for pts, style in extra:
        out.append(poly(pts, style))
    # hardware
    x0, x1, z0, z1 = WHEELBASE
    out.append(poly([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], "fill:#444;stroke:#222;stroke-width:1"))
    out.append(line((x1, (z0+z1)/2), (WHEEL[0], WHEEL[1]), "stroke:#222;stroke-width:6"))
    out.append(line((WHEEL[0], WHEEL[1]-WHEEL[2]), (WHEEL[0], WHEEL[1]+WHEEL[2]), "stroke:#222;stroke-width:9;stroke-linecap:round"))
    out.append(poly([(DISPLAY_X-7, DISP_BOTTOM), (DISPLAY_X+7, DISP_BOTTOM), (DISPLAY_X+7, DISP_BOTTOM+DISP_H), (DISPLAY_X-7, DISP_BOTTOM+DISP_H)], "fill:#333;stroke:#111"))
    out.append(poly([(DISPLAY_X-80, H), (DISPLAY_X+88, H), (DISPLAY_X+88, H+10), (DISPLAY_X-80, H+10)], "fill:#555"))
    out.append(poly([(DISPLAY_X-68, H+10), (DISPLAY_X-52, H+10), (DISPLAY_X-52, DISP_BOTTOM+40), (DISPLAY_X-68, DISP_BOTTOM+40)], "fill:#555"))
    # mannequins
    for m, col, dash in men:
        st = f"stroke:{col};stroke-width:7;fill:none;stroke-linecap:round;stroke-linejoin:round" + (";stroke-dasharray:14,10" if dash else "")
        out.append(pl([m['toe'], m['heel'], m['ankle'], m['knee'], m['hip'], m['shoulder']], st))
        if m['elbow']:
            out.append(pl([m['shoulder'], m['elbow'], (WHEEL[0], WHEEL[1])], st))
        out.append(circ(m['head_c'], m['head_r'], f"stroke:{col};stroke-width:5;fill:none" + (";stroke-dasharray:14,10" if dash else "")))
        for p in (m['hip'], m['knee'], m['ankle'], m['shoulder']):
            out.append(circ(p, 9, f"fill:{col};stroke:none"))
        out.append(circ(m['eye'], 6, f"fill:{col}"))
        out.append(circ(m['ball'], 11, f"fill:none;stroke:{col};stroke-width:3"))
        # gaze line
        out.append(line(m['eye'], (DISPLAY_X, DISP_BOTTOM + DISP_H/2), f"stroke:{col};stroke-width:1.2;stroke-dasharray:6,8"))
    # annotations
    m = men[0][0]
    out.append(text(FRONT, -38, f"pedal deck {PED_LEN} long at 22.5°, heel end x={PED_HEEL_X}", 24))
    out.append(text(DECK0+40, 600, f"deck {DECK0}–{DECK1}, top at {H}", 24))
    out.append(text(m['hip'][0]+40, m['hip'][1]-40, f"H-point ({m['hip'][0]:.0f}, {m['hip'][1]:.0f})", 24, fill=men[0][1]))
    out.append(text(m['knee'][0]-60, m['knee'][1]+45, f"knee {m['knee_deg']:.0f}°", 24, "end", men[0][1]))
    out.append(text(m['elbow'][0]+30, m['elbow'][1]-40, f"elbow {m['elbow_deg']:.0f}°", 24, fill=men[0][1]) if m['elbow'] else "")
    out.append(text(WHEEL[0]+30, WHEEL[1]+160, f"wheel centre ({WHEEL[0]}, {WHEEL[1]})", 24))
    out.append(text(DISPLAY_X+20, DISP_BOTTOM+DISP_H+40, f"screen centre {DISP_BOTTOM+DISP_H/2:.0f} high, {m['eye_to_screen']:.0f} from the eye, gaze {m['gaze_down']:.0f}° down", 24))
    out.append(text(m['ball'][0]-30, m['ball'][1]+60, f"pad {m['pad_above_deck']:.0f} above deck", 22, "end", men[0][1]))
    y = -95
    for mm_, col, dash in men:
        out.append(text(-100, y, f"{mm_['S']/10:.0f} cm driver: knee {mm_['knee_deg']:.0f}°, elbow {mm_['elbow_deg']:.0f}°, eye {mm_['eye'][1]:.0f} high, {mm_['eye_to_screen']:.0f} to screen", 28, fill=col)); y -= 45
    out.append(text(-100, -190, "Sim rig side view, mm, placeholder rig numbers. Backrest 11°, pan 2° up. Solid = 192 cm, dashed = 177 cm with the chair 80 mm forward.", 30))
    for i, n in enumerate(notes):
        out.append(text(-100, -240 - 45 * i, n, 28, fill="#7a5a1e"))
    out.append("</svg>")
    open(path, "w").write("\n".join(o for o in out if o))

if __name__ == "__main__":
    hip192 = (1440, 320)
    m192 = mannequin(1920, hip192)
    m177 = mannequin(1770, (hip192[0]-80, hip192[1]))
    report(m192, "192 cm, chair rear position")
    report(m177, "177 cm, chair 80 mm forward")
    svg([(m192, "#1f5fbf", False), (m177, "#d2691e", True)], "ergo_side_view.svg")
    print("wrote ergo_side_view.svg")
