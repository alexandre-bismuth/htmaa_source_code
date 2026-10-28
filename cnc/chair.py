#!/usr/bin/env python3
"""chair.py: the plywood parts (chair + wheel/display deck + pedal doubler) -> part sheet, nest on ONE 4 x 4 ft
3/4 in plywood panel, bismuth_ply_v1.3dm (+ .dxf), and the side-view check with the chair and the handbrake box.

Chair = Liu's two-side-profiles-and-slats chair with a flat base, on the rig's seat beams, bolted through the plates.
Joints: the pan (3 tenons per end) and the 7 back slats (1 tenon per end) pass through mortises in the sides,
tenons flush outside, tips chamfered 2 mm for the lead-in. Mortise = t_ply - 0.005 in thick (firm press),
tenon width = mortise length (no clearance). Assembly: one side flat, pan and slats standing in it with glue,
second side pressed on.
Outer width = plates' clear width - 2 x 1 mm = 498 (sides bear on the plates). The side's edge stands RIM mm
proud of the pan and slats so every mortise is closed.

Run:   python3 chair.py            (same T_OSB_IN / T_PLY_IN environment knobs as rig.py)
Checks: SHEET_W=48 SHEET_H=48 python3 -I check3dm.py bismuth_ply_v1.3dm
"""
import itertools, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geo, ergo, rig
from geo import IN, add, sub, mul, unit, left, Part, fillet_loop, poly_loop, rect_pts, oriented_rect

t, tp = rig.t, rig.tp
MORT = (rig.T_PLY_IN + rig.FIT_PLY_IN) * IN      # mortise thickness in the chair sides
CHAIR_OUT = rig.CLEAR - 2 * 1.0                   # 498
RIM = 15.0                                        # side edge proud of the pan / slats
BASE_Z = 149.0                                    # chair base sits on the seat beams' tops
CH = [(x, z - BASE_Z) for x, z in ergo.CHAIR]     # (u, v) from the chair's front-bottom corner
J = CH[2]                                         # seat line meets the backrest line (330, 115)
P_DIR = unit(sub(CH[2], CH[1]))                   # along the pan top, front -> rear (2 deg)
P_UP = left(P_DIR)                                # up, normal to the pan
B_DIR = unit(sub(CH[3], CH[2]))                   # up the backrest front line (11 deg from vertical)
B_BACK = (B_DIR[1], -B_DIR[0])                    # normal pointing back, into the slats
BACK_LEN = geo.dist(CH[2], CH[3])                 # 600
PAN_D = 320.0
PAN_TENONS = [(20.0, 80.0), (130.0, 190.0), (240.0, 300.0)]   # from the pan's front edge
SLAT_W, N_SLATS, SLAT_TENON = 60.0, 7, (10.0, 50.0)          # tenon across the slat width
SLAT0 = 35.0                                                  # along the backrest line from the junction
SLAT_END = None                                                # set below from BACK_LEN
SLAT_END = BACK_LEN - 5.0
SLAT_GAP = (SLAT_END - SLAT0 - N_SLATS * SLAT_W) / (N_SLATS - 1)
CHAMFER = 2.0
CHAIR_HOLES = [(70.0, 21.0), (310.0, 21.0)]       # M8 holes (8.5 mm), 170 above the floor; plate holes 1300/1540 (and 1220/1460)
DECK_GRID_X = [595.0 + 50 * k for k in range(8)]  # unused: the deck grid was removed (wheelbase holes drilled at assembly)

def slat_starts():
    return [SLAT0 + i * (SLAT_W + SLAT_GAP) for i in range(N_SLATS)]

# ---------------------------------------------------------------- chair parts
def side():
    top = BACK_LEN + 20.0
    A, Bp = (0.0, 0.0), (370.0, 0.0)
    C = add(add(J, mul(B_DIR, 75)), mul(B_BACK, 75))
    D = add(add(J, mul(B_DIR, top)), mul(B_BACK, 48))
    E = add(add(J, mul(B_DIR, top)), mul(B_BACK, -RIM))
    F = geo.line_intersect(add(J, mul(B_BACK, -RIM)), B_DIR, add(J, mul(P_UP, RIM)), P_DIR)
    G = geo.line_intersect(add(J, mul(P_UP, RIM)), P_DIR, (0.0, 0.0), (0.0, 1.0))
    outer = fillet_loop([A, Bp, C, D, E, F, G], [5, 10, 60, 25, 25, 30, 15])
    holes = []
    band = ((tp - MORT) / 2, (tp + MORT) / 2)
    pan_front = sub(J, mul(P_DIR, PAN_D))
    down = mul(P_UP, -1)
    for a, b in PAN_TENONS:
        holes.append(poly_loop(oriented_rect(pan_front, P_DIR, down, a, b, *band)))
    for s0 in slat_starts():
        holes.append(poly_loop(oriented_rect(J, B_DIR, B_BACK, s0 + SLAT_TENON[0], s0 + SLAT_TENON[1], *band)))
    xs = [q[0] for q in geo.loop_samples(outer, 2)]; ys = [q[1] for q in geo.loop_samples(outer, 2)]
    info = dict(size="%.0f x %.0f" % (max(xs) - min(xs), max(ys) - min(ys)), qty=2,
                joints=f"3 pan + 7 slat mortises {MORT:.2f} thick (t_ply - 0.005 in), tenon width long",
                holes="2 M8 holes (8.5 mm) at 170 high (both sides identical, one flipped)")
    return Part("chair side", "ply", outer, holes, CHAIR_HOLES, label=(185.0, 60.0), info=info)

def tenoned_board(name, depth, tenons, info):
    """Board CHAIR_OUT long (u) x depth (v), tenons tp long at both ends over the given v ranges, chamfered tips."""
    a_, b_ = tp, CHAIR_OUT - tp
    c = CHAMFER
    pts = [(a_, 0.0), (b_, 0.0)]
    for v0, v1 in tenons:               # right end, going up
        pts += [(b_, v0), (CHAIR_OUT - c, v0), (CHAIR_OUT, v0 + c), (CHAIR_OUT, v1 - c), (CHAIR_OUT - c, v1), (b_, v1)]
    pts += [(b_, depth), (a_, depth)]
    for v0, v1 in reversed(tenons):     # left end, going down
        pts += [(a_, v1), (c, v1), (0.0, v1 - c), (0.0, v0 + c), (c, v0), (a_, v0)]
    pts = [p for i, p in enumerate(pts) if p != pts[i - 1]]
    return Part(name, "ply", poly_loop(pts), [], [], label=(CHAIR_OUT / 2, depth / 2), info=info, rot_ok=(0, 180))

def pan():
    return tenoned_board("chair pan", PAN_D, PAN_TENONS, dict(size=f"{CHAIR_OUT:.0f} x {PAN_D:.0f}", qty=1,
                         joints=f"3 tenons per end, 60 wide x {tp:.2f} long, tips chamfered {CHAMFER:.0f}", holes="front edge = tenon side with the 20 mm shoulder"))

def slat(i):
    return tenoned_board(f"slat {i + 1}", SLAT_W, [SLAT_TENON], dict(size=f"{CHAIR_OUT:.0f} x {SLAT_W:.0f}", qty=1,
                         joints=f"1 tenon per end, 40 wide x {tp:.2f} long, tips chamfered {CHAMFER:.0f}", holes=""))

# ---------------------------------------------------------------- rig parts in plywood
def wheel_deck():
    D = rig.DECK1 - rig.DECK0
    lo, hi = t, rig.CLEAR + t
    tabs = [(x0 - rig.DECK0, x1 - rig.DECK0) for x0, x1 in rig.DECK_TABS]
    c = rig.TAB_CHAMFER
    pts = [(0.0, lo)]
    for d0, d1 in tabs:
        pts += [(d0, lo), (d0, c), (d0 + c, 0.0), (d1 - c, 0.0), (d1, c), (d1, lo)]
    pts += [(D, lo), (D, hi)]
    for d0, d1 in reversed(tabs):
        pts += [(d1, hi), (d1, hi + t - c), (d1 - c, hi + t), (d0 + c, hi + t), (d0, hi + t - c), (d0, hi)]
    pts += [(0.0, hi)]
    rad = [10 if p in ((0.0, lo), (D, lo), (D, hi), (0.0, hi)) else 0 for p in pts]
    pilots = []   # no mounting grid: the wheelbase's 4 holes are drilled at assembly (user, Thu night)
    info = dict(size=f"{D:.0f} x {rig.OVER:.1f} over the tabs", qty=1,
                joints=f"{len(tabs)} tabs per side {tabs[0][1] - tabs[0][0]:.0f} x {t:.2f}, in closed slots under the plates' top lip",
                holes="no factory holes: drill the frame's M5 holes at assembly")
    return Part("wheel deck", "ply", fillet_loop(pts, rad), [], pilots, label=(D / 2, lo + 40), info=info)

def all_parts():
    s = side()
    return [s, s.placed(0, 0, 0, flip=True), pan()] + [slat(i) for i in range(N_SLATS)] + [wheel_deck()] + rig.box_parts(tp)   # doubler moved to the OSB sheet

# ---------------------------------------------------------------- checks on the design
def design_checks(parts):
    probs = []
    for p in parts:
        w = geo.webs(p)
        if w:
            d, what = min(w)
            print(f"  {p.name:14s} thinnest web {d:5.1f} mm ({what})")
            if d < 10:
                probs.append(f"{p.name}: {d:.1f} mm web ({what})")
    s = parts[0]
    # pan and slats clear each other (cross-sections in the side's plane), and stay inside the side's outline
    secs = []
    pan_front = sub(J, mul(P_DIR, PAN_D))
    secs.append(("pan", oriented_rect(pan_front, P_DIR, mul(P_UP, -1), 0, PAN_D, 0, tp)))
    for i, s0 in enumerate(slat_starts()):
        secs.append((f"slat {i + 1}", oriented_rect(J, B_DIR, B_BACK, s0, s0 + SLAT_W, 0, tp)))
    for (na, a), (nb, b) in itertools.combinations(secs, 2):
        d = geo.min_dist(geo.loop_samples(poly_loop(a), 0.5), geo.loop_samples(poly_loop(b), 0.5), 50)
        if d < 3:
            probs.append(f"{na} and {nb} are {d:.1f} mm apart in section")
    # the boards' ends (tenons through the side) stay inside the side outline with RIM to spare
    outer = geo.loop_samples(s.outer, 0.5)
    for na, a in secs:
        for q in a:
            if not geo.point_in_pts(q[0], q[1], outer):
                probs.append(f"{na} corner ({q[0]:.0f},{q[1]:.0f}) outside the side profile")
    # chair holes line up with the plate pilots at both positions
    for dx in (0.0, -80.0):
        for u, v in CHAIR_HOLES:
            hit = (ergo.CHAIR_X + dx + u, BASE_Z + v)
            if hit not in rig.CHAIR_BOLTS:
                probs.append(f"chair hole at plate {hit} has no plate pilot")
    print(f"  pan and slat sections: {len(secs)} pieces, gaps between slats {SLAT_GAP:.1f} mm")
    probs += rig.box_check([p for p in parts if p.name.startswith("box ") and p.name != "box backing"], tp)
    return probs

# ---------------------------------------------------------------- part sheet
def part_sheet(parts, path):
    k = 0.5
    show = [parts[0], parts[2], parts[3], parts[10]]
    body, x, y = [], 30, 80
    for i, p in enumerate(show):
        if i == 2:
            x, y = 30, y + 440
        x0, y0, x1, y1 = p.bbox()
        P = geo.Pen(k, x0 - x / k, y0, (y1 - y0) + (y + 28) / k)
        body += geo.svg_part(p, P)
        title = p.name if p.name != "slat 1" else "back slat (x7)"
        body.append(geo.text(x, y + 12, f"{title}  ({p.info.get('size', '')}, qty {p.info.get('qty', 1) if p.name != 'slat 1' else 7})", 12, weight="bold"))
        h = (y1 - y0) * k
        for j, s in enumerate([l for l in (p.info.get("joints", ""), p.info.get("holes", "")) if l]):
            body.append(geo.text(x, y + 28 + h + 14 + 13 * j, s, 10.5, fill="#444"))
        x += max((x1 - x0) * k, 280) + 50
    # handbrake box row, zoomed
    y += 330
    kb = 1.0
    body.append(geo.text(30, y - 10, "Handbrake box (plywood), drawn at 2x the scale above. Tray glued; lid and backing plate held by 4 M5 rods through lid, box, OSB plate and backing.", 12, fill="#7a5a1e", weight="bold"))
    x = 30
    for p in [q for q in parts if q.name.startswith("box ")]:
        x0, y0, x1, y1 = p.bbox()
        P = geo.Pen(kb, x0 - x / kb, y0, (y1 - y0) + (y + 28) / kb)
        body += geo.svg_part(p, P)
        body.append(geo.text(x, y + 12, f"{p.name} ({p.info.get('size', '')})", 11, weight="bold"))
        x += max((x1 - x0) * kb, 120) + 70
    y += 150
    Wpx, Hpx = 1500, y + 60
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx}" height="{Hpx:.0f}" viewBox="0 0 {Wpx} {Hpx:.0f}">',
            '<rect width="100%" height="100%" fill="#f7f5f0"/>',
            geo.text(30, 28, f"Plywood parts (checkpoint 3). t_ply {tp:.2f} mm ({rig.T_PLY_IN} in placeholder), mortises {MORT:.2f} mm (t - 0.005 in), chair 498 outside / {CHAIR_OUT - 2 * tp:.0f} inside. Scale {k} px/mm.", 14, weight="bold"),
            geo.text(30, 48, "Red dots: relief drills on interior corners. Blue circles: bolt holes at finished size (8.5 mm M8, 5.5 mm M5), cut with the 1/8 in bit. The two chair sides are the same part, one flipped.", 11.5, fill="#444")]
    open(path, "w").write("\n".join(head + body + ["</svg>"]))
    return geo.render_png(path, 1500)

# ---------------------------------------------------------------- nest on one 4 x 4 panel
PANEL = 48 * IN
MARGIN = GAP = 1.0 * IN

def nest_structured(parts, cell=2.5):
    """Long parts pinned in two columns with the face grain along x (deck span, pan, slats), then the chair sides and
    the box pieces packed by the raster search into what is left. Returns the placed parts or None."""
    G = GAP + 0.5                                   # hand-stacked parts keep a little more than 1 in
    sides, boards, deck = parts[:2], parts[2:10], parts[10]
    box = {p.name: p for p in parts if p.name.startswith("box ")}
    def at(p, ang, x0, y0):
        q = p.placed(ang, 0, 0); b = q.bbox()
        return q.placed(0, x0 - b[0], y0 - b[1])
    placed = [at(deck, 90, MARGIN, MARGIN)]          # deck span (local y) along x = along the grain
    y = placed[0].bbox()[3] + G
    for s_ in boards[:4]:                            # pan + 3 slats above the deck
        q = at(s_, 0, MARGIN, y); placed.append(q); y = q.bbox()[3] + G
    xr = max(p.bbox()[2] for p in placed) + G
    y = PANEL - MARGIN
    for s_ in boards[4:8]:                           # 4 slats down from the top edge, right column
        q = at(s_, 0, xr, 0); q = q.placed(0, 0, y - q.bbox()[3]); placed.append(q); y = q.bbox()[1] - G
    xw, yw = max(p.bbox()[2] for p in placed[-4:]) + G, PANEL - MARGIN
    for nm in ("box front", "box rear"):             # two box walls beside those slats
        q = at(box[nm], 0, xw, 0); q = q.placed(0, 0, yw - q.bbox()[3]); placed.append(q); yw = q.bbox()[1] - G
    if max(p.bbox()[2] for p in placed) > PANEL - MARGIN:
        return None
    n = geo.Nest(PANEL, PANEL, MARGIN, GAP, cell=cell)
    for p in placed:
        n.occupy(p)
    all8 = [(a, f) for a in (0, 90, 180, 270) for f in (False, True)]
    rot4 = [(a, False) for a in (0, 90, 180, 270)]
    for p, ors in [(sides[0], all8), (sides[1], all8)] + [(box[nm], rot4) for nm in ("box back", "box lid", "box backing", "box bottom", "box top")]:
        q = n.fit(p, ors)
        if q is None:
            return None
        placed.append(q)
    return placed

def nest(parts, cell=2.5, tries=300):
    st = nest_structured(parts, cell)
    if st:
        return st, 0, "structured"
    """Bottom-left greedy over orders of the big pieces; pan + slats all the same way (face grain)."""
    import random
    sides, boards, deck = parts[:2], parts[2:10], parts[10]
    box = [p for p in parts if p.name.startswith("box ")]
    plates = [b for b in box if b.name in ("box back", "box lid", "box backing")]
    walls = [b for b in box if b not in plates]
    all8 = [(a, f) for a in (0, 90, 180, 270) for f in (False, True)]
    rot4 = [(a, False) for a in (0, 90, 180, 270)]
    two = lambda base: [(base, False), (base + 180, False)]
    rnd = random.Random(int(os.environ.get("NEST_SEED", 3)))
    orders = [[2, 0, 1, 6, 4, 3, 5]]      # found by the search: deck, sides, box backing, box back, pan, box lid
    for _ in range(tries):
        o = list(range(7)); rnd.shuffle(o); orders.append(o)
    for order in orders:
        for board_ang in (0, 90):
            deck_ors = [((board_ang + 90) % 360, False), ((board_ang + 270) % 360, False)]   # deck span (local y) along the face grain, like the slats
            items = [(sides[0], all8), (sides[1], all8), (deck, deck_ors), (boards[0], two(board_ang))] + [(b, rot4) for b in plates]
            seq = [items[k] for k in order] + [(b, two(board_ang)) for b in boards[1:]] + [(b, rot4) for b in walls]
            n = geo.Nest(PANEL, PANEL, MARGIN, GAP, cell=cell)
            placed = []
            for p, ors in seq:
                pl = n.fit(p, ors)
                if pl is None:
                    break
                placed.append(pl)
            else:
                return placed, board_ang, order
    return None, None, None

def nest_svg(placed, path, title):
    k = 0.62
    Wpx, Hpx = PANEL * k + 60, PANEL * k + 130
    P = geo.Pen(k, -30 / k, 0, PANEL + 90 / k)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx:.0f}" height="{Hpx:.0f}" viewBox="0 0 {Wpx:.0f} {Hpx:.0f}">',
           '<rect width="100%" height="100%" fill="#f7f5f0"/>',
           f'<path d="{geo.loop_path(poly_loop(rect_pts(0, 0, PANEL, PANEL)), P)}" fill="#fffdf8" stroke="#333" stroke-width="1.2"/>']
    for p in placed:
        out += geo.svg_part(p, P)
        x, y = P.xy(p.label)
        out.append(geo.text(x, y + 4, p.name, 10, "middle"))
    for i, s in enumerate(title):
        out.append(geo.text(30, 22 + 17 * i, s, 13 if i == 0 else 12, weight="bold" if i == 0 else "normal"))
    out.append("</svg>")
    open(path, "w").write("\n".join(out))
    return geo.render_png(path, int(Wpx * 2))

# ---------------------------------------------------------------- side view check (checkpoints 3 and 4)
def side_view(path):
    hip = (1440, 320)
    m192 = ergo.mannequin(1920, hip)
    m177 = ergo.mannequin(1770, (hip[0] - 80, hip[1]))
    s = side()
    ab = lambda q: (q[0] + ergo.CHAIR_X, q[1] + BASE_Z)
    extra = []
    side_pts = [ab(q) for q in geo.loop_samples(s.outer, 3)]
    extra.append((side_pts, "fill:#e6cf98;fill-opacity:0.85;stroke:#6b4e1b;stroke-width:1.2"))
    pan_front = sub(J, mul(P_DIR, PAN_D))
    extra.append(([ab(q) for q in oriented_rect(pan_front, P_DIR, mul(P_UP, -1), 0, PAN_D, 0, tp)], "fill:#c9a35a;stroke:#6b4e1b;stroke-width:1"))
    for s0 in slat_starts():
        extra.append(([ab(q) for q in oriented_rect(J, B_DIR, B_BACK, s0, s0 + SLAT_W, 0, tp)], "fill:#c9a35a;stroke:#6b4e1b;stroke-width:1"))
    for u, v in CHAIR_HOLES:
        c = ab((u, v)); extra.append(([(c[0] + 6 * math.cos(a), c[1] + 6 * math.sin(a)) for a in [i * math.pi / 6 for i in range(12)]], "fill:#333"))
    # handbrake box (outside the right plate) and a lever drawn 260 long, 20 deg back from vertical
    X, Z = rig.BOX_CAV[0] + 2 * tp, rig.BOX_CAV[1] + 2 * tp
    bx, bz = rig.BOX_C
    extra.append((rect_pts(bx - X / 2, bz - Z / 2, bx + X / 2, bz + Z / 2), "fill:#d9b97a;fill-opacity:0.9;stroke:#7a5a1e;stroke-width:1.2;stroke-dasharray:6,4"))
    a = math.radians(20)
    grip = (bx + 260 * math.sin(a), bz + 260 * math.cos(a))
    extra.append(([(bx - 4, bz), (grip[0] - 4, grip[1]), (grip[0] + 4, grip[1]), (bx + 4, bz)], "fill:#555;stroke:#333"))
    extra.append(([(grip[0] + 16 * math.cos(q), grip[1] + 16 * math.sin(q)) for q in [i * math.pi / 8 for i in range(16)]], "fill:#555"))
    sh = m192["shoulder"]
    reach = geo.dist(sh, grip); arm = (0.186 + 0.146) * 1920
    notes = [f"chair as cut: side profile, pan and 7 slats; handbrake box dashed (outside the right plate), lever drawn 260 long",
             f"192 cm: shoulder to lever grip {reach:.0f} mm, arm {arm:.0f} mm: grip at {100 * reach / arm:.0f}% of full reach, beside the right hip"]
    ergo.svg([(m192, "#1f5fbf", False), (m177, "#d2691e", True)], path, extra=extra, notes=notes, draw_chair=False)
    return geo.render_png(path, 2300), reach, arm

# ---------------------------------------------------------------- main
if __name__ == "__main__":
    parts = geo.set_hole_sizes(all_parts())
    print(f"t_ply {tp:.3f} mm, mortise {MORT:.3f} mm, chair inside {CHAIR_OUT - 2 * tp:.1f}, slat gap {SLAT_GAP:.1f}")
    print("design checks:")
    probs = design_checks(parts)
    for p in probs:
        print("  PROBLEM:", p)
    print("wrote", part_sheet(parts, os.path.join(HERE, "ply_parts.svg")))
    png, reach, arm = side_view(os.path.join(HERE, "chair_side_view.svg"))
    print(f"wrote {png} (shoulder to grip {reach:.0f} of {arm:.0f} mm)")
    area = sum(p.area() for p in parts) / 1e6
    print(f"plywood parts: {len(parts)}, {area:.3f} m2 of {PANEL * PANEL / 1e6:.3f} ({100 * area / (PANEL * PANEL / 1e6):.0f}%)")
    placed, ang, perm = nest(parts)
    if placed is None:
        raise SystemExit("does not fit on one 4 x 4 panel with these orientations")
    prob2, rep = geo.verify_layout(placed, PANEL, PANEL, MARGIN, GAP)
    print(f"nest: one 4 x 4 panel, boards at {ang} deg, closest pair {rep['closest pair'][0]:.1f} mm ({rep['closest pair'][1]} / {rep['closest pair'][2]}), edge {rep['edge']:.1f} mm")
    for p in prob2:
        print("  NEST PROBLEM:", p)
    grain = "up-down" if ang == 90 else "left-right"
    title = [f"bismuth_ply_v1: one 4 x 4 ft panel of 3/4 in plywood, 48 x 48 in, origin lower left",
             f"{len(placed)} parts, 1 in gaps and margins (closest pair {rep['closest pair'][0] / IN:.2f} in), {100 * area / (PANEL * PANEL / 1e6):.0f}% of the panel",
             f"Pan and slats all run {grain}: lay the panel with its face grain {grain} in this view."]
    print("wrote", nest_svg(placed, os.path.join(HERE, "ply_nest.svg"), title))
    if probs or prob2:
        sys.exit(1)
    out = os.path.join(HERE, "bismuth_ply_v1.3dm")
    nr, npl = geo.export_3dm(placed, PANEL, PANEL, out)
    geo.export_dxf(placed, PANEL, PANEL, out[:-4] + ".dxf")
    print(f"wrote {out} (+ .dxf): {nr} relief points, {npl} bolt holes")
