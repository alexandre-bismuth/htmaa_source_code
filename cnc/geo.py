#!/usr/bin/env python3
"""geo.py: 2D geometry, nesting, checks and export for the sim rig files.

Millimetres everywhere inside; inches only at export (.3dm / .dxf), as the N51 shop wants.
A loop is a list of segments: ('L', a, b) or ('A', a, m, b) (arc from a through m to b).
A Part has one outer loop (exported clockwise), holes (counter-clockwise), bolt-hole centres (`pilots`, with
diameters in `pilot_d`, exported as finished circles on Default for the 1/8 in bit) and a label. Drill-relief points (layer 'drill points')
are NOT stored: they are computed at export from the final coordinates in inches, at every
sharp material-reflex corner, so they sit exactly on the vertices (Gert's rule).
Fillets are true arcs: a filleted corner is not a corner and needs no relief.
"""
import math, os, sys

IN = 25.4
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- vectors
def add(a, b): return (a[0] + b[0], a[1] + b[1])
def sub(a, b): return (a[0] - b[0], a[1] - b[1])
def mul(a, k): return (a[0] * k, a[1] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1]
def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def length(a): return math.hypot(a[0], a[1])
def unit(a):
    l = length(a)
    return (a[0] / l, a[1] / l)
def left(a): return (-a[1], a[0])          # rotate +90
def dist(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])

def line_intersect(p, d, q, e):
    """Intersection of p + s d and q + t e."""
    den = cross(d, e)
    s = cross(sub(q, p), e) / den
    return add(p, mul(d, s))

# ---------------------------------------------------------------- loops
def poly_loop(pts):
    n = len(pts)
    return [('L', pts[i], pts[(i + 1) % n]) for i in range(n) if dist(pts[i], pts[(i + 1) % n]) > 1e-9]

def arc_center(a, m, b):
    ax, ay = a; bx, by = m; cx, cy = b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy)

def arc_info(seg):
    """center, radius, start angle, signed sweep (rad) of an arc segment."""
    _, a, m, b = seg
    c = arc_center(a, m, b)
    r = dist(a, c)
    ccw = cross(sub(m, a), sub(b, m)) > 0
    ta = math.atan2(a[1] - c[1], a[0] - c[0]); tb = math.atan2(b[1] - c[1], b[0] - c[0])
    sweep = (tb - ta) % (2 * math.pi) if ccw else -((ta - tb) % (2 * math.pi))
    return c, r, ta, sweep

def seg_tangents(seg):
    """unit tangent at start and end of a segment, in traversal direction."""
    if seg[0] == 'L':
        t = unit(sub(seg[2], seg[1]))
        return t, t
    c, r, ta, sweep = arc_info(seg)
    a, b = seg[1], seg[3]
    s = 1 if sweep > 0 else -1
    ta_ = unit(left(sub(a, c))); tb_ = unit(left(sub(b, c)))
    return mul(ta_, s), mul(tb_, s)

def seg_points(seg, step):
    """points along a segment, start included, end excluded."""
    if seg[0] == 'L':
        a, b = seg[1], seg[2]
        n = max(1, int(math.ceil(dist(a, b) / step)))
        return [lerp(a, b, k / n) for k in range(n)]
    c, r, ta, sweep = arc_info(seg)
    n = max(2, int(math.ceil(abs(sweep) * r / step)))
    return [(c[0] + r * math.cos(ta + sweep * k / n), c[1] + r * math.sin(ta + sweep * k / n)) for k in range(n)]

def lerp(a, b, t): return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

def loop_samples(loop, step=1.0):
    out = []
    for s in loop:
        out += seg_points(s, step)
    return out

def signed_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2

def loop_area(loop): return signed_area(loop_samples(loop, 0.5))

def reverse_loop(loop):
    out = []
    for s in reversed(loop):
        out.append(('L', s[2], s[1]) if s[0] == 'L' else ('A', s[3], s[2], s[1]))
    return out

def map_loop(loop, f):
    return [('L', f(s[1]), f(s[2])) if s[0] == 'L' else ('A', f(s[1]), f(s[2]), f(s[3])) for s in loop]

def fillet_loop(pts, radii):
    """Closed polygon with a fillet radius per vertex (0 = sharp). Returns a loop with true arcs."""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    ent, ext, arcs = [], [], []
    for i in range(n):
        p, q, s = pts[i], pts[i - 1], pts[(i + 1) % n]
        r = radii[i]
        if r <= 0:
            ent.append(p); ext.append(p); arcs.append(None); continue
        uin, uout = unit(sub(p, q)), unit(sub(s, p))
        turn = math.atan2(cross(uin, uout), dot(uin, uout))
        th = abs(turn)
        if th < 1e-6:
            ent.append(p); ext.append(p); arcs.append(None); continue
        d = r * math.tan(th / 2)
        t1, t2 = sub(p, mul(uin, d)), add(p, mul(uout, d))
        nrm = left(uin) if turn > 0 else mul(left(uin), -1)
        c = add(t1, mul(nrm, r))
        mid = add(c, mul(unit(sub(p, c)), r))
        ent.append(t1); ext.append(t2); arcs.append((t1, mid, t2))
    for i in range(n):   # fillets must not overlap along an edge
        j = (i + 1) % n
        e = dist(pts[i], pts[j])
        used = dist(pts[i], ext[i]) + dist(pts[j], ent[j])
        if used > e + 1e-6:
            raise ValueError(f"fillets at vertices {i} and {j} overlap on an edge of {e:.1f} mm (need {used:.1f})")
    loop = []
    for i in range(n):
        if arcs[i]:
            loop.append(('A',) + arcs[i])
        j = (i + 1) % n
        if dist(ext[i], ent[j]) > 1e-9:
            loop.append(('L', ext[i], ent[j]))
    return loop

def loop_corners(loop, tol_deg=1.0):
    """[(point, turn_deg)] at junctions where the direction changes; turn > 0 = left turn."""
    out = []
    n = len(loop)
    for i in range(n):
        _, tout_i = seg_tangents(loop[i])
        tin_j, _ = seg_tangents(loop[(i + 1) % n])
        ang = math.degrees(math.atan2(cross(tout_i, tin_j), dot(tout_i, tin_j)))
        if abs(ang) > tol_deg:
            end = loop[i][2] if loop[i][0] == 'L' else loop[i][3]
            out.append((end, ang))
    return out

def reflex_corners(loop, is_hole):
    """Sharp corners where the material is concave (the bit cannot reach): need a drill point."""
    ccw = loop_area(loop) > 0
    return [p for p, ang in loop_corners(loop) if ((ang < 0) != (not ccw)) != is_hole]

def point_in_pts(x, y, pts):
    c = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c

def rect_pts(x0, y0, x1, y1): return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

def oriented_rect(origin, u, v, a0, a1, b0, b1):
    """Rectangle {origin + a u + b v : a in [a0,a1], b in [b0,b1]} (u, v unit, orthogonal)."""
    P = lambda a, b: add(origin, add(mul(u, a), mul(v, b)))
    return [P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1)]

# ---------------------------------------------------------------- parts
class Part:
    def __init__(self, name, kind, outer, holes=(), pilots=(), label=None, info=None, rot_ok=(0, 90, 180, 270), flip_ok=True):
        self.name, self.kind = name, kind
        self.outer = outer
        self.holes = list(holes)
        self.pilots = list(pilots)
        self.info = info or {}
        self.rot_ok, self.flip_ok = rot_ok, flip_ok
        xs = [p[0] for p in loop_samples(outer, 5)]; ys = [p[1] for p in loop_samples(outer, 5)]
        self.label = label or ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        self.normalize()

    def normalize(self):
        if loop_area(self.outer) > 0:
            self.outer = reverse_loop(self.outer)            # perimeter clockwise
        self.holes = [h if loop_area(h) > 0 else reverse_loop(h) for h in self.holes]   # cutouts counter-clockwise
        return self

    def mapped(self, f):
        p = Part.__new__(Part)
        p.name, p.kind, p.info, p.rot_ok, p.flip_ok = self.name, self.kind, self.info, self.rot_ok, self.flip_ok
        p.outer = map_loop(self.outer, f)
        p.holes = [map_loop(h, f) for h in self.holes]
        p.pilots = [f(q) for q in self.pilots]
        p.pilot_d = getattr(self, 'pilot_d', None)
        p.label = f(self.label)
        return p.normalize()

    def placed(self, ang_deg=0, dx=0, dy=0, flip=False):
        c, s = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
        def f(p):
            x, y = (-p[0], p[1]) if flip else p
            return (c * x - s * y + dx, s * x + c * y + dy)
        return self.mapped(f)

    def bbox(self):
        pts = loop_samples(self.outer, 2)
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def area(self):
        return abs(loop_area(self.outer)) - sum(abs(loop_area(h)) for h in self.holes)

    def loops(self):
        return [(self.outer, False)] + [(h, True) for h in self.holes]

    def relief_points(self):
        out = []
        for lp, hole in self.loops():
            out += reflex_corners(lp, hole)
        return out

    def material_contains(self, x, y):
        if not point_in_pts(x, y, loop_samples(self.outer, 2)):
            return False
        return not any(point_in_pts(x, y, loop_samples(h, 2)) for h in self.holes)

# ---------------------------------------------------------------- distances
def _hash(points, cell):
    g = {}
    for k, (x, y) in enumerate(points):
        g.setdefault((int(math.floor(x / cell)), int(math.floor(y / cell))), []).append((x, y))
    return g

def min_dist(pa, pb, cut=200.0):
    """Min distance between two point sets (inf if > cut)."""
    g = _hash(pb, cut)
    best = math.inf
    for x, y in pa:
        cx, cy = int(math.floor(x / cut)), int(math.floor(y / cut))
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for q in g.get((cx + i, cy + j), ()):
                    d = math.hypot(x - q[0], y - q[1])
                    if d < best:
                        best = d
    return best

def webs(part, step=0.5):
    """Thinnest material between holes and the outline, and between holes: [(mm, what)]."""
    out = []
    outer = loop_samples(part.outer, step)
    hs = [loop_samples(h, step) for h in part.holes]
    for i, h in enumerate(hs):
        out.append((min_dist(h, outer, 60), f"hole {i} to outline"))
        for j in range(i + 1, len(hs)):
            out.append((min_dist(h, hs[j], 60), f"hole {i} to hole {j}"))
    for k, p in enumerate(part.pilots):
        d = min(min(math.hypot(p[0] - x, p[1] - y) for x, y in lp) for lp in [outer] + hs)
        out.append((d, f"pilot {k} at ({p[0]:.0f},{p[1]:.0f}) to an edge"))
    return out

def verify_layout(placed, W, H, margin, gap, step=0.5):
    """Exact-ish checks on a nest: pairwise gaps, nothing inside another part, inside the sheet."""
    problems, report = [], {}
    samp = [loop_samples(p.outer, step) + sum((loop_samples(h, step) for h in p.holes), []) for p in placed]
    worst = (math.inf, None, None)
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            bi, bj = placed[i].bbox(), placed[j].bbox()
            g2 = 2 * gap                      # pairs whose boxes are within 2 gaps get an exact distance
            if bi[0] - g2 > bj[2] or bj[0] - g2 > bi[2] or bi[1] - g2 > bj[3] or bj[1] - g2 > bi[3]:
                continue
            d = min_dist(samp[i], samp[j], 2 * gap)
            if d < worst[0]:
                worst = (d, placed[i].name, placed[j].name)
            if d < gap - 0.05:
                problems.append(f"{placed[i].name} / {placed[j].name}: {d:.1f} mm apart (< {gap:.1f})")
            # containment: a part sitting inside another's material would never show up as a gap
            x, y = samp[j][0]
            if placed[i].material_contains(x, y):
                problems.append(f"{placed[j].name} lies inside {placed[i].name}")
            x, y = samp[i][0]
            if placed[j].material_contains(x, y):
                problems.append(f"{placed[i].name} lies inside {placed[j].name}")
    edge = min(min(x, W - x, y, H - y) for s in samp for x, y in s)
    if edge < margin - 0.05:
        problems.append(f"a part is {edge:.1f} mm from the sheet edge (< {margin:.1f})")
    report["closest pair"] = worst
    report["edge"] = edge
    return problems, report

# ---------------------------------------------------------------- raster nesting
def _smear(x, n):
    y, cov = x, 1
    while cov < n:
        st = min(cov, n - cov)
        y |= y >> st
        cov += st
    return y

class Raster:
    """A part (or the sheet) as rows of bits, dilated so that non-overlapping rasters keep the gap."""
    def __init__(self, part, cell, grow):
        pts_loops = [loop_samples(lp, cell / 2) for lp, _ in part.loops()]
        allp = [p for l in pts_loops for p in l]
        x0 = math.floor((min(p[0] for p in allp) - grow) / cell) * cell   # snapped to the sheet grid
        y0 = math.floor((min(p[1] for p in allp) - grow) / cell) * cell
        x1 = max(p[0] for p in allp) + grow; y1 = max(p[1] for p in allp) + grow
        self.ox, self.oy = x0, y0
        self.w = int(math.ceil((x1 - x0) / cell)) + 1
        self.h = int(math.ceil((y1 - y0) / cell)) + 1
        rows = [0] * self.h
        # interior by scanline (even-odd over all loops)
        segs = []
        for l in pts_loops:
            n = len(l)
            segs += [(l[k], l[(k + 1) % n]) for k in range(n)]
        for j in range(self.h):
            yc = y0 + (j + 0.5) * cell
            xs = sorted(a[0] + (yc - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) for a, b in segs if (a[1] > yc) != (b[1] > yc))
            for k in range(0, len(xs) - 1, 2):
                i0 = int(math.ceil((xs[k] - x0) / cell - 0.5)); i1 = int(math.floor((xs[k + 1] - x0) / cell - 0.5))
                if i1 >= i0:
                    rows[j] |= ((1 << (i1 - i0 + 1)) - 1) << i0
        # dilation: stamp disks around boundary samples
        R = grow
        rr = int(math.ceil(R / cell)) + 1
        for x, y in allp:
            ci, cj = int((x - x0) / cell), int((y - y0) / cell)
            for dj in range(-rr, rr + 1):
                j = cj + dj
                if j < 0 or j >= self.h:
                    continue
                yc = y0 + (j + 0.5) * cell
                dy = yc - y
                if abs(dy) > R:
                    continue
                half = math.sqrt(R * R - dy * dy)
                i0 = max(0, int(math.ceil((x - half - x0) / cell - 0.5))); i1 = min(self.w - 1, int(math.floor((x + half - x0) / cell - 0.5)))
                if i1 >= i0:
                    rows[j] |= ((1 << (i1 - i0 + 1)) - 1) << i0
        self.rows = rows
        self.runs = []
        for r in rows:
            runs, i = [], 0
            while r:
                if r & 1:
                    k = 0
                    while r & 1:
                        r >>= 1; k += 1
                    runs.append((i, k)); i += k
                else:
                    tz = (r & -r).bit_length() - 1
                    r >>= tz; i += tz
            self.runs.append(runs)

class Nest:
    def __init__(self, W, H, margin, gap, cell=4.0):
        self.W, self.H, self.margin, self.gap, self.cell = W, H, margin, gap, cell
        self.grow = gap / 2 + cell * 0.7072 + cell / 4
        self.nw = int(W // cell); self.nh = int(H // cell)
        self.rows = [0] * self.nh
        # keep the dilated parts inside the sheet shrunk by (margin - gap/2)
        b = int(math.ceil((margin - gap / 2) / cell))
        full = (1 << self.nw) - 1
        edge_mask = ((1 << b) - 1) | (((1 << b) - 1) << (self.nw - b)) if b > 0 else 0
        for j in range(self.nh):
            self.rows[j] = full if (j < b or j >= self.nh - b) else edge_mask
        self.placed = []

    def occupy(self, part):
        r = Raster(part, self.cell, self.grow)
        oi = int(round(r.ox / self.cell)); oj = int(round(r.oy / self.cell))
        for j, row in enumerate(r.rows):
            jj = oj + j
            if 0 <= jj < self.nh:
                self.rows[jj] |= (row << oi) if oi >= 0 else (row >> -oi)
        self.placed.append(part)

    def fit(self, part, orientations, region=None, order="bl"):
        """Best bottom-left position over the given orientations [(ang, flip)]. Returns the placed Part or None."""
        best = None
        for ang, flip in orientations:
            p0 = part.placed(ang, 0, 0, flip)
            r = Raster(p0, self.cell, self.grow)
            j_lo, j_hi = 0, self.nh - r.h
            i_lo, i_hi = 0, self.nw - r.w
            if region:
                i_lo = max(i_lo, int(region[0] // self.cell)); j_lo = max(j_lo, int(region[1] // self.cell))
                i_hi = min(i_hi, int(region[2] // self.cell) - r.w); j_hi = min(j_hi, int(region[3] // self.cell) - r.h)
            if i_hi < i_lo or j_hi < j_lo:
                continue
            okmask = ((1 << (i_hi - i_lo + 1)) - 1) << i_lo
            for oj in range(j_lo, j_hi + 1):
                if best and order == "bl" and oj > best[0]:
                    break
                F = 0
                for j in range(r.h):
                    s = self.rows[oj + j]
                    for k0, ln in r.runs[j]:
                        F |= _smear(s >> k0, ln)
                    if (~F & okmask) == 0:
                        break
                free = ~F & okmask
                if free:
                    oi = (free & -free).bit_length() - 1
                    key = (oj, oi) if order == "bl" else (oi, oj)
                    if best is None or key < best[2]:
                        best = (oj, oi, key, ang, flip, r)
                    break
        if best is None:
            return None
        oj, oi, _, ang, flip, r = best
        pl = part.placed(ang, oi * self.cell - r.ox, oj * self.cell - r.oy, flip)
        self.occupy(pl)
        return pl

# ---------------------------------------------------------------- export
LAYERS = ["Default", "drill points", "pilot holes", "no cut", "lower vacuum areas"]

def _to_in(p): return (round(p[0] / IN, 5), round(p[1] / IN, 5))

def circle_loop(c, r):
    """Full circle as two arcs, counter-clockwise (a cutout)."""
    p0, p1 = (c[0] + r, c[1]), (c[0] - r, c[1])
    return [('A', p0, (c[0], c[1] + r), p1), ('A', p1, (c[0], c[1] - r), p0)]

def hole_circles(part):
    """Bolt holes as real cut circles in inches (pilot centres + part.pilot_d in mm), cut by the shop's 1/8 in bit."""
    if not getattr(part, "pilot_d", None):
        return []
    return [circle_loop(_to_in(q), d / IN / 2) for q, d in zip(part.pilots, part.pilot_d)]

def set_hole_sizes(parts):
    """M8 = 8.5 mm (chair bolts, tie rods, lever pivot), M5 = 5.5 mm (everything else)."""
    for p in parts:
        n = len(p.pilots)
        if p.name.startswith("plate"):
            p.pilot_d = [8.5] * 6 + [5.5] * (n - 6)          # 4 chair bolts + 2 tie rods first, then box rods
        elif p.name == "chair side":
            p.pilot_d = [8.5] * n
        elif p.name == "box lid":
            p.pilot_d = [5.5] * (n - 1) + [8.5]              # 4 rods, then the pivot
        else:
            p.pilot_d = [5.5] * n
    return parts

def export_3dm(placed, W, H, path, lib=os.path.join(HERE, "pylib")):
    """placed: Parts in sheet mm with the sheet's lower-left corner at (0,0)."""
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import rhino3dm as r3
    m = r3.File3dm()
    m.Settings.ModelUnitSystem = r3.UnitSystem.Inches
    for n in LAYERS:
        L = r3.Layer(); L.Name = n; m.Layers.Add(L)
    att = {}
    for k, n in enumerate(LAYERS):
        a = r3.ObjectAttributes(); a.LayerIndex = k; att[n] = a
    P = lambda p: r3.Point3d(p[0], p[1], 0)
    def add_loop(loop):
        if all(s[0] == 'L' for s in loop):
            pl = r3.Polyline([P(s[1]) for s in loop] + [P(loop[0][1])])
            return m.Objects.AddPolyline(pl, att["Default"])
        pc = r3.PolyCurve()
        for s in loop:
            if s[0] == 'L':
                pc.Append(r3.LineCurve(P(s[1]), P(s[2])))
            else:
                pc.Append(r3.ArcCurve.CreateFromArc(r3.Arc(P(s[1]), P(s[2]), P(s[3]))))
        return m.Objects.AddCurve(pc, att["Default"])
    sheet = r3.Polyline([P((0, 0)), P((W / IN, 0)), P((W / IN, H / IN)), P((0, H / IN)), P((0, 0))])
    m.Objects.AddPolyline(sheet, att["no cut"])
    n_relief = n_pilot = 0
    for part in placed:
        pi = part.mapped(_to_in)          # inches once; relief points from these exact vertices
        for lp, hole in pi.loops():
            add_loop(lp)
        for q in pi.relief_points():
            m.Objects.AddPoint(P(q), att["drill points"]); n_relief += 1
        for q in pi.pilots:
            n_pilot += 1
        for lp in hole_circles(part):
            add_loop(lp)
        m.Objects.AddTextDot(part.name, P(pi.label), att["no cut"])
    m.Write(path, 8)      # Rhino 8 file
    return n_relief, n_pilot

def export_dxf(placed, W, H, path, lib=os.path.join(HERE, "pylib")):
    """DXF R2010 in inches ($INSUNITS = 1): every cut loop is one closed LWPOLYLINE (arcs as bulges) on Default,
    perimeters clockwise and cutouts counter-clockwise; relief POINTs on 'drill points', bolt holes as
    closed circles on Default ('pilot holes' stays empty), the sheet outline and part names (TEXT) on 'no cut'. Same geometry as export_3dm."""
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    doc = ezdxf.new("R2010", units=ezdxf.units.IN)
    doc.header["$MEASUREMENT"] = 0
    doc.header["$LUNITS"] = 2
    for k, n in enumerate(LAYERS):
        doc.layers.add(n, color=[7, 1, 5, 8, 3][k])
    msp = doc.modelspace()
    def lw(loop, layer):
        pts = []
        for seg in loop:
            bul = 0.0 if seg[0] == 'L' else math.tan(arc_info(seg)[3] / 4)
            pts.append((seg[1][0], seg[1][1], 0.0, 0.0, bul))
        msp.add_lwpolyline(pts, format="xyseb", close=True, dxfattribs={"layer": layer})
    lw(poly_loop(rect_pts(0, 0, W / IN, H / IN)), "no cut")
    n_relief = n_pilot = 0
    for part in placed:
        pi = part.mapped(_to_in)
        for lp, hole in pi.loops():
            lw(lp, "Default")
        for q in pi.relief_points():
            msp.add_point((q[0], q[1], 0.0), dxfattribs={"layer": "drill points"}); n_relief += 1
        for q in pi.pilots:
            n_pilot += 1
        for lp in hole_circles(part):
            lw(lp, "Default")
        msp.add_text(part.name, height=0.6, dxfattribs={"layer": "no cut"}).set_placement(pi.label, align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(path)
    return n_relief, n_pilot

# ---------------------------------------------------------------- svg
COL = {"osb": ("#d9b97a", "#7a5a1e"), "ply": ("#ecdcae", "#8a6a2a")}

def loop_path(loop, P):
    s = loop[0][1]
    d = [f"M{P(s)}"]
    for seg in loop:
        if seg[0] == 'L':
            d.append(f"L{P(seg[2])}")
        else:
            c, r, ta, sweep = arc_info(seg)
            d.append(f"A{r * P.k:.2f},{r * P.k:.2f} 0 {1 if abs(sweep) > math.pi else 0},{0 if sweep > 0 else 1} {P(seg[3])}")
    return " ".join(d) + " Z"

class Pen:
    """mm -> svg px with y up."""
    def __init__(self, k, ox, oy, H):
        self.k, self.ox, self.oy, self.H = k, ox, oy, H
    def __call__(self, p):
        return f"{(p[0] - self.ox) * self.k:.2f},{(self.H - (p[1] - self.oy)) * self.k:.2f}"
    def xy(self, p):
        return (p[0] - self.ox) * self.k, (self.H - (p[1] - self.oy)) * self.k

def svg_part(part, P, relief=True, pilots=True, fill=None):
    f, s = COL.get(part.kind, ("#ddd", "#555"))
    d = loop_path(part.outer, P) + " " + " ".join(loop_path(h, P) for h in part.holes)
    out = [f'<path d="{d}" fill="{fill or f}" fill-rule="evenodd" stroke="{s}" stroke-width="0.9"/>']
    if relief:
        for q in part.relief_points():
            x, y = P.xy(q); out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.8" fill="#d23"/>')
    if pilots and getattr(part, "pilot_d", None):    # bolt holes at true size
        for q, dd in zip(part.pilots, part.pilot_d):
            x, y = P.xy(q); out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{max(dd / 2 * P.k, 1.2):.2f}" fill="none" stroke="#1f5fbf" stroke-width="0.9"/>')
    elif pilots:
        for q in part.pilots:
            x, y = P.xy(q); out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.5" fill="#1f5fbf"/>')
    return out

def text(x, y, s, size=11, anchor="start", fill="#222", weight="normal"):
    s = s.replace("&", "&amp;").replace("<", "&lt;")
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}" font-family="Helvetica, Arial, sans-serif">{s}</text>'

def render_png(svg_path, width):
    png = svg_path[:-4] + ".png"
    os.system(f'rsvg-convert -w {width} "{svg_path}" -o "{png}"')
    return png
