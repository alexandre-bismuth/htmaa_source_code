#!/usr/bin/env python3
"""rig.py: the OSB parts of the sim rig -> part sheet, nest on the shop's 4 x 8 OSB, bismuth_rig_v1.3dm (+ .dxf).

Geometry comes from ergo.py (the side view and the posture use the same numbers). Millimetres inside,
inches at export. Fits (see spec.md):
  OSB slot          = 0.42 in, the tight fit on Jen's comb for this year's OSB (osb2026.3dm notches 0.39..0.50 in)
  plywood mortise   = measured t_ply - 0.005 in  (chair, chair.py)
  in-plane widths   = no clearance (tab length = slot length); every tab tip chamfered 2 mm for the lead-in
The wheel deck's plywood tabs sit in closed slots (t_ply + 0.005 in tall) under the plates' straight top lip,
25 mm above the deck, so the deck cannot lift. Joints first; bolts only where a joint cannot hold (two M8 tie rods).

Run:   python3 rig.py                     (placeholders t_osb 0.42 in, t_ply 0.71 in; OSB slots 0.42 in)
Monday: T_OSB_IN=0.418 T_PLY_IN=0.70 python3 rig.py     (caliper averages: tab lengths follow; SLOT_OSB_IN only if a new comb says so)
Checks: python3 -I check3dm.py bismuth_rig_v1.3dm
"""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geo
from geo import IN, add, sub, mul, Part, fillet_loop, poly_loop, rect_pts, oriented_rect
import ergo

# ---------------------------------------------------------------- parameters
T_OSB_IN = float(os.environ.get("T_OSB_IN", 0.42))      # placeholder until the calipers; sets tab lengths (flush) and the box/finger depths
SLOT_OSB_IN = float(os.environ.get("SLOT_OSB_IN", 0.42))  # OSB slot width: the tight fit on Jen's comb for this year's OSB (user, Thu night)
T_PLY_IN = float(os.environ.get("T_PLY_IN", 0.48))      # MEASURED at the shop: 0.478-0.482 in, the panel is 1/2 in plywood (was the 3/4 in placeholder 0.71)
FIT_PLY_IN = -0.005
TAB_CHAMFER = 2.0                       # in-plane lead-in at every tab tip (mm)
t = T_OSB_IN * IN                       # OSB thickness, mm
SLOT = SLOT_OSB_IN * IN                 # slot width for an OSB tab
tp = T_PLY_IN * IN                      # plywood thickness, mm
CLEAR = 500.0                           # clear width between the plates
OVER = CLEAR + 2 * t                    # length of a cross member over its tabs (tabs flush outside)

FRONT, L, B, H = ergo.FRONT, ergo.L, ergo.B, ergo.H
DECK0, DECK1, REAR_BASE, FOOT_TOP = ergo.DECK0, ergo.DECK1, ergo.REAR_BASE, ergo.FOOT_TOP
DECK_TABS = ergo.DECK_TABS                         # wheel deck tabs: closed slots under ears on the plate top (glue-free: the deck cannot lift)
DECK_EAR, DECK_EAR_MARGIN = ergo.DECK_EAR, ergo.DECK_EAR_MARGIN
DECK_SLOT_CLR = 0.005 * IN                         # plywood tab in an OSB slot: slot height = t_ply + 0.005 in (snug, the tab is uniform plywood)
TIE_RODS = ergo.TIE_RODS                           # M8 threaded rods across the tower (glue-free: they clamp the plates onto the member shoulders)
PED_HEEL = (ergo.PED_HEEL_X, ergo.PED_HEEL_Z)     # bottom face, heel end
PED_LEN, PED_ANG = ergo.PED_LEN, ergo.PED_ANG
PED_TABS = [(60.0, 150.0), (200.0, 290.0), (340.0, 430.0)]   # along the deck from the heel end
DECK_TOP_UNDER = H - tp                            # underside of the plywood deck: rib tops
# cross members: name, x (centre of thickness), z0, z1, tab z0, tab z1 (shoulders above and below the tab)
MEMBERS = [
    ("dash rib", DECK0 + t, DECK_TOP_UNDER - 100, DECK_TOP_UNDER, DECK_TOP_UNDER - 90, DECK_TOP_UNDER - 40),
    ("deck rib", 720.0, DECK_TOP_UNDER - 80, DECK_TOP_UNDER, DECK_TOP_UNDER - 65, DECK_TOP_UNDER - 15),
    ("floor tie 800", 800.0, 0.0, 80.0, 25.0, 65.0),
    ("floor tie 1050", 1050.0, 0.0, 80.0, 25.0, 65.0),
    ("seat beam 1280", 1280.0, 60.0, 149.0, 75.0, 134.0),
    ("seat beam 1560", 1560.0, 60.0, 149.0, 75.0, 134.0),
]
CHAIR_BOLTS = [(1220.0, 170.0), (1300.0, 170.0), (1460.0, 170.0), (1540.0, 170.0)]   # M8; chair rear = 1300/1540, 80 fwd = 1220/1460
# handbrake electronics box, PLYWOOD (cut on the plywood panel by chair.py), outside the right plate below the window,
# beside the knee diagonal. A plywood backing plate on the inside face sandwiches the OSB, so the bolts never bear on OSB alone.
BOX_CAV = (90.0, 70.0, 45.0)            # cavity x (along the rig), z (up), y (out from the plate)
BOX_C = (1080.0, 310.0)                 # box centre on the plate = lever pivot; backing must clear the chair's forward position (front at 1150)
BOX_BOLT = (37.0, 27.0)                 # 4 M5 rods at centre +- these (8 mm inside the cavity corners): lid, cavity, back, plate, backing
CABLE_SLOT = (18.0, 8.0)                # bottom wall, for a 5-pin JST housing
FINGERS = (3, 3, 3)                     # finger count along x, z, y (odd): 30 / 23 / 15 mm fingers
# (unused since the grids were removed; kept for reference) M5 grid on the pedal deck
PED_GRID_D = [40.0 + 50 * k for k in range(9)]
GRID_Y = [CLEAR / 2 + s * (25 + 50 * j) for j in range(4) for s in (-1, 1)]

# ---------------------------------------------------------------- parts
def plate(right):
    lip = H + DECK_EAR                       # straight top edge 25 mm above the deck, diagonal to diagonal (no steps)
    pts = [((FRONT + 60, 0), 10), ((L, 0), 5), ((L, ergo.SEAT_TOP), 10), ((ergo.knee_diag_x(ergo.SEAT_TOP), ergo.SEAT_TOP), 40),
           ((ergo.knee_diag_x(lip), lip), 10), ((ergo.foot_diag_x(lip), lip), 10), ((FRONT + 80, FOOT_TOP), 40), ((FRONT, FOOT_TOP), 10), ((FRONT, 60), 10)]
    outer = fillet_loop([p for p, r in pts], [r for p, r in pts])
    holes = [fillet_loop([tuple(p) for p in ergo.window()], 25)]
    for x0, x1 in DECK_TABS:
        holes.append(poly_loop(rect_pts(x0, H - tp, x1, H + DECK_SLOT_CLR)))
    for name, x, z0, z1, a, b in MEMBERS:
        holes.append(poly_loop(rect_pts(x - SLOT / 2, a, x + SLOT / 2, b)))
    u = (-math.cos(PED_ANG), math.sin(PED_ANG)); v = (math.sin(PED_ANG), math.cos(PED_ANG))   # v = unit normal to u (deck thickness)
    for d0, d1 in PED_TABS:
        holes.append(poly_loop(oriented_rect(PED_HEEL, u, v, d0, d1, -(SLOT - t) / 2, t + (SLOT - t) / 2)))
    pilots = list(CHAIR_BOLTS) + list(TIE_RODS)
    if right:
        pilots += [(BOX_C[0] + sx * BOX_BOLT[0], BOX_C[1] + sz * BOX_BOLT[1]) for sx in (-1, 1) for sz in (-1, 1)]
    name = "plate R (box holes)" if right else "plate L"
    info = dict(size=f"{L - FRONT:.0f} x {H + DECK_EAR:.0f}", qty=1,
                joints=f"6 member slots {SLOT:.2f} wide, 3 pedal-deck slots {SLOT:.2f} x 90, {len(DECK_TABS)} deck slots {DECK_TABS[0][1] - DECK_TABS[0][0]:.0f} x {tp + DECK_SLOT_CLR:.2f} under the top lip (30 mm bridges)",
                holes=f"holes: 4 chair M8 at z 170, 2 M8 tie rods" + (", 4 box M5" if right else "") + " (8.5 / 5.5 mm circles)")
    return Part(name, "osb", outer, holes, pilots, label=(900.0, 95.0), info=info)

def member(name, x, z0, z1, a, b):
    """Cross member on edge, u across the rig (0..OVER), v = z. Shouldered through-tabs flush outside the plates."""
    c = TAB_CHAMFER
    assert a > z0 and b < z1, f"{name}: tabs need shoulders"
    pts = [(t, z0), (CLEAR + t, z0)]
    pts += [(CLEAR + t, a), (OVER - c, a), (OVER, a + c), (OVER, b - c), (OVER - c, b), (CLEAR + t, b)]
    pts += [(CLEAR + t, z1), (t, z1)]
    pts += [(t, b), (c, b), (0, b - c), (0, a + c), (c, a), (t, a)]
    pts = [p for i, p in enumerate(pts) if p != pts[i - 1]]
    info = dict(size=f"{OVER:.1f} x {z1 - z0:.0f}", qty=1, joints=f"tabs {t:.2f} long x {b - a:.0f} tall, tips chamfered {TAB_CHAMFER:.0f}, shoulders {a - z0:.0f} below / {z1 - b:.0f} above",
                holes="top edge up" if name in ("dash rib", "deck rib") else "")
    return Part(name, "osb", poly_loop(pts), [], [], label=(OVER / 2, (z0 + z1) / 2), info=info)

def pedal_deck():
    lo, hi = t, CLEAR + t
    c = TAB_CHAMFER
    pts = [(0, lo)]
    for d0, d1 in PED_TABS:
        pts += [(d0, lo), (d0, c), (d0 + c, 0), (d1 - c, 0), (d1, c), (d1, lo)]
    pts += [(PED_LEN, lo), (PED_LEN, hi)]
    for d0, d1 in reversed(PED_TABS):
        pts += [(d1, hi), (d1, hi + t - c), (d1 - c, hi + t), (d0 + c, hi + t), (d0, hi + t - c), (d0, hi)]
    pts += [(0, hi)]
    rad = [10 if p in ((0, lo), (PED_LEN, lo), (PED_LEN, hi), (0, hi)) else 0 for p in pts]
    pilots = []   # no mounting grid: the pedal frame's 4 holes are drilled at assembly (user, Thu night)
    info = dict(size=f"{PED_LEN:.0f} x {OVER:.1f} over the tabs", qty=1, joints=f"3 tabs per side, {t:.2f} long x 90, tips chamfered {TAB_CHAMFER:.0f}", holes="no factory holes: drill the frame's M5 holes at assembly")
    return Part("pedal deck", "osb", fillet_loop(pts, rad), [], pilots, label=(PED_LEN / 2, lo + 30), info=info)

def doubler():
    """OSB, under the pedal deck, clamped by the pedal bolts (23 mm of OSB). No factory holes: drilled through with the deck at assembly."""
    pilots = []   # drilled together with the pedal deck at assembly
    return Part("pedal doubler", "osb", fillet_loop(rect_pts(0, 0, 190, 300), 5), [], pilots,
                info=dict(size="190 x 300", qty=1, joints="under the pedal deck, clamped by the pedal bolts", holes="no factory holes: drilled through with the pedal deck at assembly"))

def cell_union_loop(bu, bv, filled):
    """Boundary of a union of grid cells (simply connected) as a polygon loop."""
    edges = {}
    for (i, j) in filled:
        for e in (((i, j), (i + 1, j)), ((i + 1, j), (i + 1, j + 1)), ((i + 1, j + 1), (i, j + 1)), ((i, j + 1), (i, j))):
            if (e[1], e[0]) in edges:
                del edges[(e[1], e[0])]
            else:
                edges[e] = True
    nxt = {}
    for a, b in edges:
        assert a not in nxt, "pinched outline"
        nxt[a] = b
    start = min(nxt)
    loop, cur = [start], nxt[start]
    while cur != start:
        loop.append(cur); cur = nxt[cur]
    assert len(loop) == len(nxt), "more than one boundary"
    pts = [(bu[i], bv[j]) for i, j in loop]
    out = []
    n = len(pts)
    for k in range(n):   # drop collinear points
        a, b, c = pts[k - 1], pts[k], pts[(k + 1) % n]
        if abs(geo.cross(sub(b, a), sub(c, b))) > 1e-9:
            out.append(b)
    return out

def box_parts(th):
    """Tray = back + 4 walls, finger-jointed and glued. Lid = plain plate. Four long M5 bolts run through the lid,
    the cavity corners, the back and the plate: they clamp the box to the rig and carry the lever's pivot load,
    and the lid comes off with four nuts."""
    CX, CZ, CY = BOX_CAV
    t = th
    X, Z, Y = CX + 2 * t, CZ + 2 * t, CY + 2 * t
    nX, nZ, nY = FINGERS
    def br(Lc, n): return [0.0, t] + [t + Lc * k / n for k in range(1, n)] + [Lc + t, Lc + 2 * t]
    def face(name, cw, ch, nw, nh, own, corners, holes=(), pilots=(), info=None):
        """own = (bottom v=0, top v=H, left u=0, right u=W) strip ownership, each a function of the segment index;
        corners = (bl, br, tl, tr) corner squares owned."""
        bu, bv = br(cw, nw), br(ch, nh)
        filled = set()
        for i in range(nw + 2):
            for j in range(nh + 2):
                li, ri, bj, tj = i == 0, i == nw + 1, j == 0, j == nh + 1
                if not (li or ri or bj or tj): f = True
                elif (li or ri) and (bj or tj): f = corners[(1 if ri else 0) + (2 if tj else 0)]
                elif bj: f = own[0](i - 1)
                elif tj: f = own[1](i - 1)
                elif li: f = own[2](j - 1)
                else: f = own[3](j - 1)
                if f: filled.add((i, j))
        pts = cell_union_loop(bu, bv, filled)
        return Part(name, "ply", poly_loop(pts), holes, pilots, label=(bu[-1] / 2, bv[-1] / 2), info=info)
    even = lambda k: k % 2 == 0
    odd = lambda k: k % 2 == 1
    alls = lambda k: True
    none = lambda k: False
    bolts = [(X / 2 + sx * BOX_BOLT[0], Z / 2 + sz * BOX_BOLT[1]) for sx in (-1, 1) for sz in (-1, 1)]
    slot = poly_loop(rect_pts(X / 2 - CABLE_SLOT[0] / 2, Y / 2 - CABLE_SLOT[1] / 2, X / 2 + CABLE_SLOT[0] / 2, Y / 2 + CABLE_SLOT[1] / 2))
    fi = f"finger joints {t:.2f} deep, glued"
    sz = lambda w, h: f"{w:.1f} x {h:.1f}"
    # walls: u or v = 0 is the back side; the lid side is a straight edge (the lid is a plain plate)
    return [
        face("box back", CX, CZ, nX, nZ, (even, even, even, even), (True,) * 4, pilots=bolts,
             info=dict(size=sz(X, Z), qty=1, joints=fi, holes="4 M5 holes (5.5 mm) for the long box rods")),
        face("box lid", CX, CZ, nX, nZ, (alls, alls, alls, alls), (True,) * 4, pilots=bolts + [(X / 2, Z / 2)],
             info=dict(size=sz(X, Z), qty=1, joints="plain plate on the walls, held by the 4 bolts (comes off with 4 nuts)", holes="4 M5 holes (5.5 mm) + the pivot hole (8.5 mm)")),
        face("box bottom", CX, CY, nX, nY, (odd, none, even, even), (False,) * 4, holes=[slot],
             info=dict(size=sz(X, Y - t), qty=1, joints=fi, holes=f"cable slot {CABLE_SLOT[0]:.0f} x {CABLE_SLOT[1]:.0f}")),
        face("box top", CX, CY, nX, nY, (odd, none, even, even), (False,) * 4,
             info=dict(size=sz(X, Y - t), qty=1, joints=fi, holes="")),
        face("box front", CY, CZ, nY, nZ, (odd, odd, odd, none), (False,) * 4,
             info=dict(size=sz(Y - t, Z), qty=1, joints=fi, holes="")),
        face("box rear", CY, CZ, nY, nZ, (odd, odd, odd, none), (False,) * 4,
             info=dict(size=sz(Y - t, Z), qty=1, joints=fi, holes="")),
        face("box backing", CX, CZ, nX, nZ, (alls, alls, alls, alls), (True,) * 4, pilots=bolts,
             info=dict(size=sz(X, Z), qty=1, joints="inside face of the right plate: the OSB is clamped between two plywood plates", holes="4 M5 holes (5.5 mm)")),
    ]

def all_parts():
    return [plate(False), plate(True), pedal_deck()] + [member(*m) for m in MEMBERS] + [doubler()]      # the box is plywood: chair.py

# ---------------------------------------------------------------- checks on the design itself
def design_checks(parts):
    problems = []
    for p in parts:
        w = geo.webs(p)
        if w:
            d, what = min(w)
            lim = 20.0 if p.name.startswith("plate") else 8.0
            flag = "  <-- THIN" if d < lim else ""
            print(f"  {p.name:22s} thinnest web {d:5.1f} mm ({what}){flag}")
            if d < lim:
                problems.append(f"{p.name}: {d:.1f} mm web ({what})")
    # box sits on plate material, bolts and pivot clear of the window and the edge
    pr = [p for p in parts if p.name.startswith("plate R")][0]
    X, Z = BOX_CAV[0] + 2 * tp, BOX_CAV[1] + 2 * tp
    for cx in (BOX_C[0] - X / 2, BOX_C[0] + X / 2):
        for cz in (BOX_C[1] - Z / 2, BOX_C[1] + Z / 2):
            if not pr.material_contains(cx, cz):
                problems.append(f"box corner ({cx:.0f},{cz:.0f}) hangs off the plate")
    # the backing plate (inside the right plate) must clear the chair side in its forward position
    chair_front_fwd = ergo.CHAIR_X - 80
    if BOX_C[0] + X / 2 + 5 > chair_front_fwd:
        problems.append(f"box backing reaches x {BOX_C[0] + X / 2:.0f}, chair front (forward position) at {chair_front_fwd}")
    print(f"  box backing x {BOX_C[0] - X / 2:.0f}..{BOX_C[0] + X / 2:.0f}, chair front in the forward position at {chair_front_fwd}: {chair_front_fwd - BOX_C[0] - X / 2:.0f} mm clear")
    # members and slots agree
    for name, x, z0, z1, a, b in MEMBERS:
        assert z0 <= a < b <= z1, name
    return problems

def box_check(box, t):
    """Every cell of the box shell is covered by exactly one of the six pieces (finger joints consistent)."""
    CX, CZ, CY = BOX_CAV
    X, Z, Y = CX + 2 * t, CZ + 2 * t, CY + 2 * t
    nX, nZ, nY = FINGERS
    def br(Lc, n): return [0.0, t] + [t + Lc * k / n for k in range(1, n)] + [Lc + t, Lc + 2 * t]
    bx, by, bz = br(CX, nX), br(CY, nY), br(CZ, nZ)
    mid = lambda b, i: (b[i] + b[i + 1]) / 2
    pc = {p.name: p for p in box}
    # (piece, axis of thickness, slab index, (u-axis, u-breaks), (v-axis, v-breaks))
    spec = [("box back", "y", 0, "x", "z"), ("box lid", "y", -1, "x", "z"), ("box bottom", "z", 0, "x", "y"),
            ("box top", "z", -1, "x", "y"), ("box front", "x", 0, "y", "z"), ("box rear", "x", -1, "y", "z")]
    brk = {"x": bx, "y": by, "z": bz}
    cover = {}
    for name, ax, slab, ua, va in spec:
        part = pc[name]
        nb = len(brk[ax]) - 1
        si = 0 if slab == 0 else nb - 1
        for i in range(len(brk[ua]) - 1):
            for j in range(len(brk[va]) - 1):
                if geo.point_in_pts(mid(brk[ua], i), mid(brk[va], j), geo.loop_samples(part.outer, 1)):   # holes (cable slot) count as covered
                    key = {ax: si, ua: i, va: j}
                    cell = (key["x"], key["y"], key["z"])
                    cover[cell] = cover.get(cell, 0) + 1
    probs = []
    for i in range(len(bx) - 1):
        for j in range(len(by) - 1):
            for k in range(len(bz) - 1):
                shell = i in (0, len(bx) - 2) or j in (0, len(by) - 2) or k in (0, len(bz) - 2)
                c = cover.get((i, j, k), 0)
                if shell and c != 1:
                    probs.append(f"box shell cell {(i, j, k)} covered {c} times")
                if not shell and c:
                    probs.append(f"box cavity cell {(i, j, k)} filled")
    print(f"  box tiling: {len(cover)} shell cells, {len(probs)} problems")
    return probs[:5]

# ---------------------------------------------------------------- part sheet (checkpoint 1)
def part_sheet(parts, path):
    k = 0.42
    rows = [[parts[0]], [parts[1]], [parts[2]] + parts[3:5] + [parts[9]], parts[5:9]]
    zoom = {9: 1.6}       # row index -> scale factor (box pieces)
    out, y = [], 70
    Wpx = 1500
    body = []
    for ri, row in enumerate(rows):
        x = 30
        hmax = 0
        k = 0.42 * (3.2 if ri == 4 else 1)
        if ri == 4:
            body.append(geo.text(30, y - 8, "Handbrake box pieces, drawn at 3.2x the scale above", 12, fill="#7a5a1e", weight="bold"))
            y += 10
        for p in row:
            x0, y0, x1, y1 = p.bbox()
            w, h = (x1 - x0) * k, (y1 - y0) * k
            P = geo.Pen(k, x0 - x / k, y0, 0)
            P.H = (y1 - y0) + (y + 28) / k
            body += geo.svg_part(p, P)
            body.append(geo.text(x, y + 12, f"{p.name}  ({p.info.get('size', '')})", 12, weight="bold"))
            inf = p.info
            lines = [inf.get("joints", ""), inf.get("holes", "")]
            for i, s in enumerate([l for l in lines if l]):
                body.append(geo.text(x, y + 28 + h + 14 + 13 * i, s, 10.5, fill="#444"))
            x += max(w, 260 if ri < 4 else 225) + (40 if ri < 4 else 18)
            hmax = max(hmax, h)
        y += hmax + 85
    Hpx = y + 40
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx}" height="{Hpx:.0f}" viewBox="0 0 {Wpx} {Hpx:.0f}">',
            '<rect width="100%" height="100%" fill="#f7f5f0"/>',
            geo.text(30, 28, f"Sim rig, OSB parts (checkpoint 1). t_osb {t:.2f} mm ({T_OSB_IN} in placeholder), slots {SLOT:.2f} mm ({SLOT_OSB_IN} in, Jen's comb), deck notches {tp:.2f} deep (t_ply {T_PLY_IN} in). Scale 0.42 px/mm.", 14, weight="bold"),
            geo.text(30, 48, "Red dots: 1/8 in relief drills on interior corners (layer drill points). Blue circles: bolt holes at finished size (8.5 mm M8, 5.5 mm M5), cut with the 1/8 in bit. Curved corners are true arcs and need no relief.", 11.5, fill="#444")]
    open(path, "w").write("\n".join(head + body + ["</svg>"]))
    return geo.render_png(path, 1500)

# ---------------------------------------------------------------- nest (checkpoint 2)
SHEET_W, SHEET_H = 48 * IN, 96 * IN
MARGIN = GAP = 1.0 * IN

def nest(parts):
    plates = [p for p in parts if p.name.startswith("plate")]
    rest = [p for p in parts if not p.name.startswith("plate")]
    # plate A along y, tower toward +x, front end at the top of the sheet; plate B turned 180 deg, its tower
    # interleaved with A's (the two knee diagonals run parallel). Search B's y for the shortest total length.
    A0 = plates[1].placed(270, 0, 0)       # right plate (box holes) as A
    ax0, ay0, ax1, ay1 = A0.bbox()
    A = A0.placed(0, MARGIN - ax0, SHEET_H - MARGIN - ay1)
    B0 = plates[0].placed(90, 0, 0)
    bx0, by0, bx1, by1 = B0.bbox()
    sA = geo.loop_samples(A.outer, 1.0) + sum((geo.loop_samples(h, 1.0) for h in A.holes), [])
    best = None
    lo, hi = MARGIN - by0, SHEET_H - MARGIN - by1      # B's y shift range
    for step in (20.0, 2.0, 0.25):
        rng = [lo + i * step for i in range(int((hi - lo) / step) + 1)]
        for dy in reversed(rng):
            Bc = B0.placed(0, SHEET_W - MARGIN - bx1, dy)
            sB = geo.loop_samples(Bc.outer, 1.0) + sum((geo.loop_samples(h, 1.0) for h in Bc.holes), [])
            d = geo.min_dist(sA, sB, 60)
            if d >= GAP + 0.6 and not A.material_contains(*Bc.outer[0][1]):
                best = (dy, d)
                break
        if best is None:
            raise SystemExit("plates do not interleave")
        lo, hi = best[0], min(best[0] + step, SHEET_H - MARGIN - by1)
    Bp = B0.placed(0, SHEET_W - MARGIN - bx1, best[0])
    n = geo.Nest(SHEET_W, SHEET_H, MARGIN, GAP, cell=2.5)
    n.occupy(A); n.occupy(Bp)
    placed = [A, Bp]
    rot4 = [(0, False), (90, False), (180, False), (270, False)]
    for p in sorted(rest, key=lambda q: -q.area()):
        pl = n.fit(p, rot4)
        if pl is None:
            raise SystemExit(f"no room for {p.name}")
        placed.append(pl)
    return placed

def nest_svg(placed, path, title):
    k = 0.36
    Wpx, Hpx = SHEET_W * k + 60, SHEET_H * k + 120
    P = geo.Pen(k, -30 / k, 0, SHEET_H + 75 / k)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx:.0f}" height="{Hpx:.0f}" viewBox="0 0 {Wpx:.0f} {Hpx:.0f}">',
           '<rect width="100%" height="100%" fill="#f7f5f0"/>']
    out.append(f'<path d="{geo.loop_path(poly_loop(rect_pts(0, 0, SHEET_W, SHEET_H)), P)}" fill="#fffdf8" stroke="#333" stroke-width="1.2"/>')
    for p in placed:
        out += geo.svg_part(p, P)
        x, y = P.xy(p.label)
        out.append(geo.text(x, y + 4, p.name, 9.5, "middle", "#222"))
    for i, s in enumerate(title):
        out.append(geo.text(30, 22 + 16 * i, s, 12 if i else 13, weight="bold" if i == 0 else "normal"))
    out.append("</svg>")
    open(path, "w").write("\n".join(out))
    return geo.render_png(path, int(Wpx * 2))

# ---------------------------------------------------------------- main
if __name__ == "__main__":
    parts = geo.set_hole_sizes(all_parts())
    print(f"t_osb {t:.3f} mm, OSB slot {SLOT:.3f} mm, t_ply {tp:.3f} mm, member length {OVER:.2f} mm")
    print("design checks (webs between slots/holes and edges):")
    probs = design_checks(parts)
    for p in probs:
        print("  PROBLEM:", p)
    png = part_sheet(parts, os.path.join(HERE, "rig_parts.svg"))
    print("wrote", png)
    area = sum(p.area() for p in parts) / 1e6
    print(f"OSB parts: {len(parts)}, {area:.2f} m2 of {SHEET_W * SHEET_H / 1e6:.2f} ({100 * area / (SHEET_W * SHEET_H / 1e6):.0f}%)")
    if "--parts-only" in sys.argv:
        sys.exit(1 if probs else 0)
    placed = nest(parts)
    prob2, rep = geo.verify_layout(placed, SHEET_W, SHEET_H, MARGIN, GAP)
    ymax = max(p.bbox()[3] for p in placed); ymin = min(p.bbox()[1] for p in placed)
    print(f"nest: closest pair {rep['closest pair'][0]:.1f} mm ({rep['closest pair'][1]} / {rep['closest pair'][2]}), closest to the sheet edge {rep['edge']:.1f} mm, parts span y {ymin:.0f}..{ymax:.0f} of {SHEET_H:.0f}")
    for p in prob2:
        print("  NEST PROBLEM:", p)
    title = [f"bismuth_rig_v1: 4 x 8 ft OSB, 48 x 96 in, origin lower left",
             f"{len(placed)} parts, 1 in gaps and margins (closest pair {rep['closest pair'][0] / IN:.2f} in)",
             f"t_osb {T_OSB_IN} in placeholder, OSB slots {SLOT_OSB_IN} in (Jen's comb). Red: relief drills. Blue: bolt holes (8.5 / 5.5 mm)."]
    png2 = nest_svg(placed, os.path.join(HERE, "rig_nest.svg"), title)
    print("wrote", png2)
    if prob2 or probs:
        sys.exit(1)
    out = os.path.join(HERE, "bismuth_rig_v1.3dm")
    nr, npl = geo.export_3dm(placed, SHEET_W, SHEET_H, out)
    geo.export_dxf(placed, SHEET_W, SHEET_H, out[:-4] + ".dxf")
    print(f"wrote {out} (+ .dxf): {nr} relief points, {npl} bolt holes")
