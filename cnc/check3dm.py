#!/usr/bin/env python3
"""Check a Rhino .3dm drawing before emailing it to archshops@mit.edu.

Gert's principles (received 2026-10-22) + conventions observed in Jen's osb2026.3dm:
  units inches; ONE 48 (x) by 96 (y) sheet rectangle with its lower-left corner at the origin;
  everything at z = 0; cut geometry = CLOSED curves on Default; no duplicates;
  points on layer "drill points" sit exactly on INTERIOR (concave) corners, one per corner,
  never on a convex corner; every interior corner has one; parts >= 1 in apart; nothing outside the sheet.
Added for the sim rig files: points on layer "pilot holes" (pilots for bolt holes and M5 grids) must sit
inside part material, clear of every cut edge; thin webs between a cutout and the outline (or two cutouts)
are flagged (problem < MIN_WEB_PROBLEM, note < MIN_WEB_NOTE).

Install once (rhino3dm, next to this script):
  PIP_REQUIRE_VIRTUALENV=false python3 -m pip install --target "$(dirname check3dm.py)/pylib" rhino3dm
Run:
  python3 -I check3dm.py my_drawing.3dm
  env knobs: SHEET_W=48 SHEET_H=96 MIN_GAP=1.0 MARGIN=1.0 ALLOW_MISSING_RELIEF=1 MIN_WEB_PROBLEM=0.5 MIN_WEB_NOTE=0.75
"""
import math, os, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
for lib in (os.path.join(HERE, "pylib"), os.environ.get("RHINO3DM_LIB", "")):
    if lib and os.path.isdir(lib):
        sys.path.insert(0, lib)
import rhino3dm  # noqa: E402

SHEET_W = float(os.environ.get("SHEET_W", 48))
SHEET_H = float(os.environ.get("SHEET_H", 96))
MIN_GAP = float(os.environ.get("MIN_GAP", 1.0))
MARGIN = float(os.environ.get("MARGIN", 1.0))
ALLOW_MISSING = os.environ.get("ALLOW_MISSING_RELIEF", "") not in ("", "0")
MIN_WEB_PROBLEM = float(os.environ.get("MIN_WEB_PROBLEM", 0.5))
MIN_WEB_NOTE = float(os.environ.get("MIN_WEB_NOTE", 0.75))
PILOT_LAYER = "pilot holes"
PILOT_CLEAR = 0.12   # a 1/8 in pilot opened to M5/M8 must stay off the cut edges
TOL = 0.001          # coincidence tolerance, inches
CORNER_DEG = 1.0     # direction change below this is not a corner
STEP = 0.1           # sampling step for gap / containment checks
CUT_LAYERS = {"Default"}
EXPECTED_LAYERS = ["Default", "drill points", "no cut", "lower vacuum areas"]


def bbox(g):
    b = g.GetBoundingBox()
    return b.Min.X, b.Min.Y, b.Max.X, b.Max.Y, b.Min.Z, b.Max.Z


def est_len(g):
    """Length for polylines, generous estimate (bbox perimeter) for anything else; rhino3dm has no GetLength."""
    if isinstance(g, rhino3dm.PolylineCurve):
        pts = [g.Point(i) for i in range(g.PointCount)]
        return sum(math.hypot(b.X - a.X, b.Y - a.Y) for a, b in zip(pts, pts[1:]))
    if isinstance(g, rhino3dm.PolyCurve):
        return sum(est_len(g.SegmentCurve(i)) for i in range(g.SegmentCount))
    x0, y0, x1, y1, _, _ = bbox(g)
    return 2 * ((x1 - x0) + (y1 - y0))


def samples(g, step=STEP):
    """Dense 2D points along a curve (for area, containment and gap checks), segment by segment."""
    if isinstance(g, rhino3dm.PolyCurve):
        out = []
        for i in range(g.SegmentCount):
            out += samples(g.SegmentCurve(i), step)[:-1]
        return out + [(g.PointAtEnd.X, g.PointAtEnd.Y)]
    if isinstance(g, rhino3dm.PolylineCurve):
        pts = [(g.Point(i).X, g.Point(i).Y) for i in range(g.PointCount)]
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        return out + pts[-1:]
    n = max(16, int(math.ceil(2.0 * est_len(g) / step)))   # uniform in parameter: fine for arcs/circles, ok for nurbs
    d = g.Domain
    return [(q.X, q.Y) for q in (g.PointAt(d.T0 + (d.T1 - d.T0) * k / n) for k in range(n + 1))]


def poly_len(pts):
    return sum(math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(pts, pts[1:]))


def signed_area(pts):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2


def inside(x, y, pts):
    """Ray casting point-in-polygon."""
    c = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xi > x:
                c = not c
    return c


def corners(g):
    """Direction changes of a closed curve: [(x, y, turn_deg)], turn > 0 = left turn."""
    segs = []  # (end point, tangent in, tangent out) per segment
    if isinstance(g, rhino3dm.PolyCurve):
        for i in range(g.SegmentCount):
            s = g.SegmentCurve(i)
            segs.append((s.PointAtEnd, s.TangentAtStart, s.TangentAtEnd))
    elif isinstance(g, rhino3dm.PolylineCurve):
        pts = [g.Point(i) for i in range(g.PointCount)]
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b.X - a.X, b.Y - a.Y)
            if d > TOL:
                t = rhino3dm.Vector3d((b.X - a.X) / d, (b.Y - a.Y) / d, 0)
                segs.append((b, t, t))
    else:
        return []  # one smooth closed curve (circle, ellipse, nurbs): no corners
    out = []
    for i in range(len(segs)):
        tin = segs[i][2]
        tout = segs[(i + 1) % len(segs)][1]
        cross = tin.X * tout.Y - tin.Y * tout.X
        dot = tin.X * tout.X + tin.Y * tout.Y
        ang = math.degrees(math.atan2(cross, dot))
        if abs(ang) > CORNER_DEG:
            out.append((segs[i][0].X, segs[i][0].Y, ang))
    return out


def main(path):
    m = rhino3dm.File3dm.Read(path)
    if m is None:
        print("could not read", path); return 2
    problems, notes = [], []
    layers = [l.Name for l in m.Layers]
    print("file  :", path)
    print("units :", m.Settings.ModelUnitSystem)
    if "Inches" not in str(m.Settings.ModelUnitSystem):
        problems.append("units are not inches")
    print("layers:", layers)
    for name in EXPECTED_LAYERS:
        if name not in layers:
            notes.append(f"no layer {name!r} (Jen's file has it; optional)")

    counts = Counter()
    sheet = None
    open_cut, outside, cut_curves, points, off_z = [], [], [], [], 0
    for o in m.Objects:
        g = o.Geometry
        li = o.Attributes.LayerIndex
        layer = layers[li] if 0 <= li < len(layers) else "?"
        counts[(layer, type(g).__name__)] += 1
        if isinstance(g, rhino3dm.Point):
            points.append((layer, g.Location.X, g.Location.Y))
            if abs(g.Location.Z) > TOL:
                off_z += 1
            continue
        try:
            x0, y0, x1, y1, z0, z1 = bbox(g)
        except Exception:
            continue
        if abs(z0) > TOL or abs(z1) > TOL:
            off_z += 1
        if isinstance(g, rhino3dm.Curve):
            w, h = x1 - x0, y1 - y0
            if (abs(w - SHEET_W) < TOL and abs(h - SHEET_H) < TOL) or (abs(w - SHEET_H) < TOL and abs(h - SHEET_W) < TOL):
                sheet = (x0, y0, x1, y1)
                continue
            if layer in CUT_LAYERS:
                if not g.IsClosed:
                    open_cut.append((layer, round(x0, 2), round(y0, 2), round(w, 2), round(h, 2)))
                else:
                    cut_curves.append((g, (x0, y0, x1, y1)))
        outside.append((layer, type(g).__name__, x0, y0, x1, y1))

    print("objects by layer/type:")
    for k, v in counts.most_common():
        print(f"   {v:4d}  {k}")
    if off_z:
        problems.append(f"{off_z} object(s) not at z = 0 (Gert: no height difference between lines)")

    # ---- sheet
    if sheet is None:
        problems.append(f"no {SHEET_W:g}x{SHEET_H:g} sheet rectangle found")
    else:
        sw, sh = sheet[2] - sheet[0], sheet[3] - sheet[1]
        print(f"sheet : at ({sheet[0]:.3f},{sheet[1]:.3f}) size {sw:.1f} x {sh:.1f}")
        if abs(sheet[0]) > TOL or abs(sheet[1]) > TOL:
            problems.append("sheet lower-left corner is not at the origin (Gert: zero point at the lower-left)")
        if not (abs(sw - SHEET_W) < TOL and abs(sh - SHEET_H) < TOL):
            problems.append(f"sheet is {sw:g} along x, {sh:g} along y (Gert: {SHEET_W:g} along x, {SHEET_H:g} along y)")
        out = [o for o in outside if o[2] < sheet[0] - TOL or o[3] < sheet[1] - TOL or o[4] > sheet[2] + TOL or o[5] > sheet[3] + TOL]
        if out:
            problems.append(f"{len(out)} object(s) outside the sheet (first: {out[0][:2]} at {out[0][2]:.2f},{out[0][3]:.2f})")
        for layer, x, y in points:
            if x < sheet[0] - TOL or y < sheet[1] - TOL or x > sheet[2] + TOL or y > sheet[3] + TOL:
                problems.append(f"drill point outside the sheet at ({x:.3f},{y:.3f})"); break

    if open_cut:
        problems.append(f"{len(open_cut)} OPEN curve(s) on cut layer(s), first: {open_cut[0]}")

    # ---- curve records (only curves inside the sheet; outside ones are already flagged), then duplicates
    if sheet:
        cut_curves = [(g, bb) for g, bb in cut_curves
                      if bb[0] >= sheet[0] - TOL and bb[1] >= sheet[1] - TOL and bb[2] <= sheet[2] + TOL and bb[3] <= sheet[3] + TOL]
    curves = []
    for g, bb in cut_curves:
        pts = samples(g)
        curves.append({"g": g, "bb": bb, "pts": pts, "len": poly_len(pts), "area": abs(signed_area(pts)),
                       "ccw": signed_area(pts) > 0, "corners": corners(g)})
    seen = Counter(tuple(round(v, 3) for v in c["bb"]) + (round(c["len"], 2),) for c in curves)
    dups = sum(v - 1 for v in seen.values() if v > 1)
    if dups:
        problems.append(f"{dups} duplicate cut curve(s) (same bbox and length): they would be cut twice")

    # ---- parts, holes, corners
    for c in curves:
        x, y = c["pts"][0]
        containers = [d for d in curves if d is not c and d["area"] > c["area"]
                      and d["bb"][0] - TOL <= x <= d["bb"][2] + TOL and d["bb"][1] - TOL <= y <= d["bb"][3] + TOL
                      and inside(x, y, d["pts"])]
        c["hole"] = len(containers) % 2 == 1
        c["parent"] = min(containers, key=lambda d: d["area"]) if containers else None
    outers = [c for c in curves if not c["hole"]]
    for i, c in enumerate(outers):
        c["part"] = i
    for c in curves:
        if c["hole"]:
            c["part"] = c["parent"]["part"]
    print(f"parts : {len(outers)} outlines, {len(curves) - len(outers)} interior cutouts (inside the sheet)")

    # material-reflex corners = where the bit cannot reach = need a drill point
    reflex, convex = [], []
    for c in curves:
        for x, y, ang in c["corners"]:
            left = ang > 0
            is_reflex = (left != c["ccw"]) if not c["hole"] else (left == c["ccw"])
            (reflex if is_reflex else convex).append((x, y))

    drill = [(x, y) for layer, x, y in points if layer == "drill points"]
    stray = [(layer, x, y) for layer, x, y in points if layer not in ("drill points", PILOT_LAYER)]
    if stray:
        problems.append(f"{len(stray)} point(s) not on layer 'drill points', first: {stray[0]}")

    def near(p, lst):
        return any(math.hypot(p[0] - q[0], p[1] - q[1]) <= TOL for q in lst)

    on_convex = [p for p in drill if near(p, convex) and not near(p, reflex)]
    nowhere = [p for p in drill if not near(p, convex) and not near(p, reflex)]
    missing = [p for p in reflex if not near(p, drill)]
    dup_pts = Counter((round(x, 3), round(y, 3)) for x, y in drill)
    doubled = sum(v - 1 for v in dup_pts.values() if v > 1)
    print(f"corners: {len(reflex)} interior (need relief), {len(convex)} convex")
    print(f"drill points: {len(drill)} | on convex corners: {len(on_convex)} | not on any corner: {len(nowhere)} | interior corners without a point: {len(missing)} | doubled: {doubled}")
    if on_convex:
        problems.append(f"{len(on_convex)} drill point(s) on a CONVEX corner (Gert: concave only), first: ({on_convex[0][0]:.3f},{on_convex[0][1]:.3f})")
    if nowhere:
        problems.append(f"{len(nowhere)} drill point(s) not on any corner vertex, first: ({nowhere[0][0]:.3f},{nowhere[0][1]:.3f})")
    if missing:
        msg = f"{len(missing)} interior corner(s) without a drill point, first: ({missing[0][0]:.3f},{missing[0][1]:.3f})"
        (notes if ALLOW_MISSING else problems).append(msg)
    if doubled:
        notes.append(f"{doubled} doubled drill point(s) (two points on one corner)")

    # ---- pilots (pilot holes): inside material, clear of edges
    pilots = [(x, y) for layer, x, y in points if layer == PILOT_LAYER]
    if pilots:
        allpts = [(x, y) for c in curves for x, y in c["pts"]]
        cellp = 1.0
        gridp = defaultdict(list)
        for x, y in allpts:
            gridp[(int(math.floor(x / cellp)), int(math.floor(y / cellp)))].append((x, y))
        bad_in, bad_edge = [], []
        for x, y in pilots:
            inn = [c for c in curves if c["bb"][0] <= x <= c["bb"][2] and c["bb"][1] <= y <= c["bb"][3] and inside(x, y, c["pts"])]
            if len(inn) % 2 == 0:
                bad_in.append((x, y))
            cx, cy = int(math.floor(x / cellp)), int(math.floor(y / cellp))
            d = min((math.hypot(x - q[0], y - q[1]) for i in (-1, 0, 1) for j in (-1, 0, 1) for q in gridp.get((cx + i, cy + j), ())), default=math.inf)
            if d < PILOT_CLEAR:
                bad_edge.append((x, y, d))
        print(f"pilots: {len(pilots)} on {PILOT_LAYER!r} | outside material: {len(bad_in)} | closer than {PILOT_CLEAR} in to an edge: {len(bad_edge)}")
        if bad_in:
            problems.append(f"{len(bad_in)} pilot point(s) not inside part material, first: ({bad_in[0][0]:.3f},{bad_in[0][1]:.3f})")
        if bad_edge:
            problems.append(f"{len(bad_edge)} pilot point(s) within {PILOT_CLEAR} in of a cut edge, first: ({bad_edge[0][0]:.3f},{bad_edge[0][1]:.3f})")

    # ---- webs: thinnest material between a cutout and its outline, or between two cutouts of one part
    def setdist(a, b):
        cellw = 1.0
        g = defaultdict(list)
        for x, y in b:
            g[(int(math.floor(x / cellw)), int(math.floor(y / cellw)))].append((x, y))
        best = math.inf
        for x, y in a:
            cx, cy = int(math.floor(x / cellw)), int(math.floor(y / cellw))
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    for q in g.get((cx + i, cy + j), ()):
                        d = math.hypot(x - q[0], y - q[1])
                        if d < best:
                            best = d
        return best
    thin = []
    for o in outers:
        hs = [c for c in curves if c["hole"] and c["part"] == o["part"]]
        for i, h in enumerate(hs):
            thin.append((setdist(h["pts"], o["pts"]), h["pts"][0]))
            for h2 in hs[i + 1:]:
                if h2["bb"][0] - 1 > h["bb"][2] or h["bb"][0] - 1 > h2["bb"][2] or h2["bb"][1] - 1 > h["bb"][3] or h["bb"][1] - 1 > h2["bb"][3]:
                    continue
                thin.append((setdist(h["pts"], h2["pts"]), h["pts"][0]))
    if thin:
        wmin = min(thin)
        print(f"webs  : thinnest material next to a cutout is {wmin[0]:.2f} in ({wmin[0] * 25.4:.0f} mm) near ({wmin[1][0]:.1f},{wmin[1][1]:.1f})")
        tp = [t for t in thin if t[0] < MIN_WEB_PROBLEM]
        tn = [t for t in thin if MIN_WEB_PROBLEM <= t[0] < MIN_WEB_NOTE]
        if tp:
            problems.append(f"{len(tp)} web(s) thinner than {MIN_WEB_PROBLEM} in next to a cutout, thinnest {min(tp)[0]:.2f} in")
        if tn:
            notes.append(f"{len(tn)} web(s) between {MIN_WEB_PROBLEM} and {MIN_WEB_NOTE} in next to a cutout")

    # ---- gaps between parts, and margin to the sheet edge
    if len(outers) > 1 or sheet:
        cell = max(MIN_GAP, 0.5)
        grid = defaultdict(list)
        for c in curves:
            for x, y in c["pts"]:
                grid[(int(math.floor(x / cell)), int(math.floor(y / cell)))].append((x, y, c["part"]))
        pair_min = {}
        for (cx, cy), lst in grid.items():
            neigh = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neigh += grid.get((cx + dx, cy + dy), [])
            for x, y, p in lst:
                for x2, y2, p2 in neigh:
                    if p2 <= p:
                        continue
                    d = math.hypot(x - x2, y - y2)
                    key = (p, p2)
                    if d < pair_min.get(key, (math.inf,))[0]:
                        pair_min[key] = (d, x, y)
        close = sorted((v, k) for k, v in pair_min.items() if v[0] < MIN_GAP - 0.5 * STEP)
        if pair_min:
            dmin = min(v[0] for v in pair_min.values())
            print(f"gaps  : closest two parts are {dmin:.2f} in apart (rule >= {MIN_GAP:g})")
        if close:
            (d, x, y), (p, p2) = close[0]
            problems.append(f"{len(close)} part pair(s) closer than {MIN_GAP:g} in, worst: {d:.2f} in near ({x:.1f},{y:.1f})")
        if sheet:
            em = min(min(x - sheet[0], sheet[2] - x, y - sheet[1], sheet[3] - y) for c in curves for x, y in c["pts"]) if curves else math.inf
            if curves:
                print(f"margin: closest part to the sheet edge is {em:.2f} in")
                if em < MARGIN - 0.5 * STEP:
                    notes.append(f"part(s) within {MARGIN:g} in of the sheet edge (closest {em:.2f} in)")

    print()
    for n in notes:
        print("  note:", n)
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: no problems found")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    sys.exit(main(sys.argv[1]))
