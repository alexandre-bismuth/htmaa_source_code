"""Geometry for the parked cars (tools/blender/parked_cars.py): a body loft, a cabin loft, surface patches (lamps,
grille, handles...), wheels and small parts, collected as quads/triangles with a zone per face.

Frame: metres, X = car forward, Y = car LEFT, Z = up, ground at z = 0, origin on the ground at the middle of the
overall length and width (so a prop at z = 0 stands on the asphalt). Same axes as the STi (tools/blender/sti_*), so
Blender's glTF export (+Y up) lands +X forward in Unreal.

Body: a loft of closed cross-sections (top crown -> shoulder -> side -> sill -> underbody) at stations along x; the
plan half-width falls to 0 at both ends along a superellipse, so the nose and tail close without caps. Wheel arches are
the sill line rising round each wheel (the underbody follows: the tunnel is hidden by a black chassis block + liners).
Cabin: a second loft (roof crown -> roof edge -> side glass -> base) whose height goes to 0 at the cowl and the deck,
sunk a few cm into the body (the beltline is the visible intersection). Zones are assigned per face on station /
section-row boundaries, so window, pillar and seam edges are exact grid lines (no stair steps).
"""
import math

import numpy as np

# ------------------------------------------------------------------------------------------------ helpers
def pchip(x, xs, ys):
    """Monotone cubic interpolation (Fritsch-Carlson); xs ascending; clamps outside."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    h = np.diff(xs)
    d = np.diff(ys) / h
    n = len(xs)
    m = np.zeros(n)
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, n - 1):
        if d[k - 1] * d[k] <= 0:
            m[k] = 0.0
        else:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    k = int(np.searchsorted(xs, x) - 1)
    t = (x - xs[k]) / h[k]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return float(h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1])


def tab(x, pts):
    pts = sorted(pts)
    return pchip(x, [p[0] for p in pts], [p[1] for p in pts])


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def uniq_sorted(vals, tol=4e-4, keep=(), guarded=(), guard=0.0036):
    """Sorted descending (front first), merging values closer than tol (values in `keep` win); other values within
    `guard` of a `guarded` one are dropped (so a 6 mm seam strip between two guarded stations is exactly one face)."""
    ka = np.array(sorted(guarded)) if len(guarded) else np.zeros(0)
    keep = sorted(set(round(k, 6) for k in list(keep) + list(guarded)))
    vals = [v for v in vals if not len(ka) or np.min(np.abs(ka - v)) >= guard]
    out = []
    for v in sorted(set(round(v, 6) for v in vals) | set(keep), reverse=True):
        if out and abs(out[-1] - v) < tol:
            if v in keep and out[-1] not in keep:
                out[-1] = v
            continue
        out.append(v)
    return out


def signed_volume(V, F):
    V = np.asarray(V, float)
    vol = 0.0
    for f in F:
        for k in range(1, len(f) - 1):
            vol += np.dot(V[f[0]], np.cross(V[f[k]], V[f[k + 1]]))
    return vol / 6.0


def outward(V, F):
    """Reverse all faces of a closed shell whose normals point inward."""
    return F if signed_volume(V, F) >= 0 else [tuple(reversed(f)) for f in F]


class Mesh:
    """Accumulates polygons (3 or 4 vertex indices) with a zone name per face."""

    def __init__(self):
        self.v = []
        self.f = []
        self.z = []

    def add(self, verts, faces, zones):
        o = len(self.v)
        self.v.extend([tuple(map(float, p)) for p in verts])
        if isinstance(zones, str):
            zones = [zones] * len(faces)
        for fc, zn in zip(faces, zones):
            self.f.append(tuple(int(i) + o for i in fc))
            self.z.append(zn)

    def extend(self, other):
        self.add(other.v, [tuple(i for i in fc) for fc in other.f], other.z)


def grid_faces(ni, nj, closed_j=False):
    """Quads of an ni x nj vertex grid (index i * nj + j)."""
    out = []
    for i in range(ni - 1):
        for j in range(nj if closed_j else nj - 1):
            jn = (j + 1) % nj
            out.append((i * nj + j, (i + 1) * nj + j, (i + 1) * nj + jn, i * nj + jn))
    return out


# ------------------------------------------------------------------------------------------------ body
class Body:
    """Lower body (the painted shell below the beltline)."""

    def __init__(self, s):
        self.s = s
        L = s["L"]
        self.xf, self.xr = L / 2, -L / 2
        self.B = s["W"] / 2
        self.axles = [self.xf - s["fo"], self.xf - s["fo"] - s["wb"]]
        self.Ra = s["R"] + s.get("arch_gap", 0.055)
        self.zw = s["R"] - 0.012                     # wheel centre height (tyre squashed 12 mm)
        self.top_pts = [(self.xf - d, z) for d, z in s["top"]]
        self.end_f, self.end_r = s.get("end_f", 0.30), s.get("end_r", 0.26)
        self.n_end = s.get("plan_n", 3.4)

    # plan / profile functions -------------------------------------------------------------------
    def plan(self, x):
        """Half width at x (0 at the very ends)."""
        b = self.B
        x0f, x0r = self.xf - self.end_f, self.xr + self.end_r
        if x > x0f:
            xi = min((x - x0f) / self.end_f, 1.0)
            b *= (1 - xi ** self.n_end) ** (1 / self.n_end)
        elif x < x0r:
            xi = min((x0r - x) / self.end_r, 1.0)
            b *= (1 - xi ** self.n_end) ** (1 / self.n_end)
        for xa in self.axles:                       # fender flares
            d = abs(x - xa) / (self.Ra + 0.25)
            if d < 1:
                b += self.s.get("flare", 0.012) * math.cos(0.5 * math.pi * d) ** 2
        return max(b, 0.0)

    def ztop(self, x):
        z = tab(x, self.top_pts)
        # roll the top over at both ends (circle-ish, radius rt)
        for xe, sgn, rt in ((self.xf, 1, self.s.get("roll_f", 0.075)), (self.xr, -1, self.s.get("roll_r", 0.08))):
            d = (x - (xe - sgn * rt)) * sgn
            if d > 0:
                z -= rt * (1 - math.sqrt(max(0.0, 1 - (min(d / rt, 1.0)) ** 2)))
        return z

    def zbot_base(self, x):
        s = self.s
        ra = self.axles
        pts = [(self.xf, s["bump_f"] + 0.05), (self.xf - 0.12, s["bump_f"]), (ra[0] + self.Ra + 0.02, s["sill"] + 0.02),
               (ra[0], s["sill"]), (ra[1], s["sill"]), (ra[1] - self.Ra - 0.02, s["sill"] + 0.02),
               (self.xr + 0.12, s["bump_r"]), (self.xr, s["bump_r"] + 0.06)]
        z = tab(x, [(p[0], p[1]) for p in pts])
        # chin / tail lift at the very ends
        for xe, sgn, rb in ((self.xf, 1, 0.06), (self.xr, -1, 0.06)):
            dd = (x - (xe - sgn * rb)) * sgn
            if dd > 0:
                z += rb * (1 - math.sqrt(max(0.0, 1 - (min(dd / rb, 1.0)) ** 2)))
        return z

    def arch(self, x):
        """Height of the arch edge at x (None outside the arches)."""
        for xa in self.axles:
            d = x - xa
            if abs(d) < self.Ra:
                return self.zw + math.sqrt(self.Ra * self.Ra - d * d)
        return None

    def zbot(self, x):
        z = self.zbot_base(x)
        a = self.arch(x)
        return max(z, a) if a is not None else z

    # stations -------------------------------------------------------------------------------------
    def stations(self, extra=(), guarded=()):
        s = self.s
        st = list(np.arange(self.xr + self.end_r, self.xf - self.end_f, 0.025))
        n = 22
        for k in range(n + 1):        # superellipse ends: uniform in the angle parameter
            th = 0.5 * math.pi * k / n
            xi = math.sin(th) ** (2 / self.n_end)
            st.append(self.xf - self.end_f + self.end_f * xi)
            st.append(self.xr + self.end_r - self.end_r * xi)
        for xa in self.axles:          # arches: 4 degree steps round the circle
            for k in range(46):
                st.append(xa + self.Ra * math.cos(math.pi * k / 45))
            st += [xa + self.Ra + 0.004, xa - self.Ra - 0.004]
        keep = [self.xf, self.xr] + list(extra)
        return uniq_sorted([x for x in st if self.xr <= x <= self.xf], keep=keep, guarded=guarded)

    # sections -------------------------------------------------------------------------------------
    ROWS = None

    def half_section(self, x):
        """[(y, z, kind)] from the top centre to the bottom centre (fixed count for every station)."""
        s = self.s
        b = self.plan(x)
        f = b / self.B if self.B > 0 else 0.0
        zt, zb = self.ztop(x), self.zbot(x)
        h = max(zt - zb, 0.02)
        crown = s.get("crown", 0.035) * f
        rs = min(s.get("shoulder_r", 0.05), 0.35 * h) * max(f, 0.15)
        tum = s.get("tumble", 0.045) * f
        tuck = min(s.get("tuck", 0.035), 0.025) * f
        in_arch = self.arch(x) is not None and self.arch(x) > self.zbot_base(x) + 1e-4
        rb = (0.012 if in_arch else s.get("sill_r", 0.035)) * max(f, 0.2)
        rb = min(rb, 0.3 * h)
        y_te = max(b - tum - rs, 0.0)
        pts = []
        # top (crown); thin seam row at s = 0.70 (hood / boot lid edge)
        seam = 0.70
        dl = min(0.003 / max(y_te, 0.05), 0.015)
        for u in (0.0, 0.12, 0.24, 0.36, 0.48, 0.58, seam - dl, seam + dl, 0.80, 0.88, 0.94, 0.98):
            pts.append((u * y_te, zt - crown * u * u, "top"))
        z_te = zt - crown
        # shoulder roll: quarter superellipse from (y_te, z_te) to (b - tum, z_te - rs)
        for k in range(0, 8):
            a = 0.5 * math.pi * k / 7
            ca, sa = math.cos(a), math.sin(a)
            e = 2.0 / 2.6
            pts.append((y_te + rs * (abs(sa) ** e), z_te - rs * (1 - abs(ca) ** e), "shoulder"))
        z_sh = z_te - rs
        # side: shoulder -> sill (tumble above, tuck below)
        nside = 14
        for k in range(1, nside + 1):
            t = k / nside
            z = z_sh + (zb + rb - z_sh) * t
            zn = (z - (zb + rb)) / max(z_sh - (zb + rb), 1e-4)
            zc = s.get("crease", 0.66)
            y = (b - tum * ((zn - zc) / (1 - zc)) ** 1.05 if zn > zc else b - 0.004 * ((zc - zn) / zc) * f) \
                - tuck * max(0.0, (0.25 - zn) / 0.25) ** 2
            pts.append((y, z, "side"))
        y_sb = pts[-1][0]
        for k in range(1, 5):          # sill rounding
            a = 0.5 * math.pi * k / 4
            pts.append((y_sb - rb * (1 - math.cos(a)), zb + rb * (1 - math.sin(a)), "sill"))
        y0 = pts[-1][0]
        for u in (0.8, 0.55, 0.3, 0.0):
            pts.append((y0 * u, zb, "under"))
        return pts

    def wedge(self, x, z):
        """x shift of a body point: the top of the nose / tail leans in, the chin and bumper bottom tuck under."""
        s = self.s
        zt, zb = self.ztop(x), self.zbot_base(x)
        zn = (z - zb) / max(zt - zb, 0.05)
        out = 0.0
        for xe, sgn, ln, at, ab in ((self.xf, 1, self.end_f + 0.25, s.get("wedge_top_f", 0.07), s.get("wedge_bot_f", 0.06)),
                                    (self.xr, -1, self.end_r + 0.25, s.get("wedge_top_r", 0.05), s.get("wedge_bot_r", 0.06))):
            w = smoothstep(xe - sgn * ln, xe, x) if sgn > 0 else smoothstep(xe + ln, xe, x)
            if w > 0:
                out -= sgn * w * (at * max(0.0, zn - 0.55) / 0.45 + ab * max(0.0, 0.3 - zn) / 0.3)
        return out

    def ring(self, x):
        half = self.half_section(x)
        left = [(x + self.wedge(x, z), y, z) for y, z, _ in half]
        right = [(x + self.wedge(x, z), -y, z) for y, z, _ in reversed(half[1:-1])]
        kinds = [k for _, _, k in half] + [k for _, _, k in reversed(half[1:-1])]
        return left + right, kinds

    def build(self, zone_fn, extra_stations=(), guarded=()):
        """zone_fn(x_mid, kind, j, side, z_mid) -> zone. Returns (Mesh, stations)."""
        st = self.stations(extra_stations, guarded)
        rings, kinds = [], None
        for x in st:
            r, kinds = self.ring(x)
            rings.append(r)
        nj = len(rings[0])
        V = [p for r in rings for p in r]
        F = grid_faces(len(st), nj, closed_j=True)
        Z = []
        nh = len(self.half_section(st[0]))
        for i in range(len(st) - 1):
            for j in range(nj):
                xm = 0.5 * (st[i] + st[i + 1])
                side = 1 if j < nh - 1 else -1
                jm = j if side > 0 else nj - 1 - j         # the matching left-half face
                zm = 0.25 * (rings[i][j][2] + rings[i + 1][j][2] + rings[i][(j + 1) % nj][2] + rings[i + 1][(j + 1) % nj][2])
                Z.append(zone_fn(xm, kinds[jm], jm, side, zm))
        m = Mesh()
        m.add(V, outward(V, F), Z)
        return m, st


class Cabin:
    """Greenhouse: roof + glass + pillars, from the cowl to the deck / tail."""

    def __init__(self, s, body):
        self.s, self.body = s, body
        c = s["cabin"]
        xf = body.xf
        self.xc, self.xh, self.xre, self.xrg = xf - c["d_c"], xf - c["d_h"], xf - c["d_re"], xf - c["d_rg"]
        self.roof = [(xf - d, z) for d, z in c["roof"]]
        self.ledge = c.get("ledge", 0.06)
        self.tumble = math.tan(math.radians(c.get("tumble_deg", 24)))
        self.re = c.get("edge_r", 0.07)
        self.crown = c.get("crown", 0.04)
        self.sink = 0.035
        self.ext_f, self.ext_r = 0.09, 0.09
        self.sweep_f, self.sweep_r = c.get("sweep_f", 0.22), c.get("sweep_r", 0.16)

    def zbase(self, x):
        b = self.body
        return b.ztop(x) - self.s.get("crown", 0.035) - self.sink

    def zroof(self, x):
        """Section top (centre) height: the cabin's side profile, extended below the body at both ends."""
        if x > self.xc:
            t = min((x - self.xc) / self.ext_f, 1.0)
            return self.body.ztop(self.xc) + (self.zbase(x) - 0.002 - self.body.ztop(self.xc)) * t
        if x < self.xrg:
            t = min((self.xrg - x) / self.ext_r, 1.0)
            return self.body.ztop(self.xrg) + (self.zbase(x) - 0.002 - self.body.ztop(self.xrg)) * t
        pts = [(self.xc, self.body.ztop(self.xc))] + self.roof + [(self.xrg, self.body.ztop(self.xrg))]
        return tab(x, pts)

    def width_base(self, x):
        return max(self.body.plan(x) - self.ledge - self.body.s.get("tumble", 0.045), 0.05)

    def stations(self, extra=()):
        x0, x1 = self.xrg - self.ext_r, self.xc + self.ext_f
        st = list(np.arange(x0, x1, 0.025)) + [x0, x1]
        for k in range(1, 12):
            st.append(self.xc + self.ext_f * k / 12)
            st.append(self.xrg - self.ext_r * k / 12)
        keep = [self.xc, self.xh, self.xre, self.xrg, x0, x1] + list(extra)
        return uniq_sorted([x for x in st if x0 <= x <= x1], keep=keep)

    def half_section(self, x):
        zr, zb = self.zroof(x), self.zbase(x)
        h = max(zr - zb, 0.0)
        bb = self.width_base(x)
        hf = min(h / 0.25, 1.0)
        re = min(self.re, 0.45 * h)
        crown = self.crown * hf
        bt = max(bb - h * self.tumble - re, 0.02)       # roof half width (to the edge rounding)
        pts = []
        for u in (0.0, 0.15, 0.3, 0.45, 0.58, 0.7, 0.8, 0.88, 0.94, 0.98):
            pts.append((u * bt, zr - crown * u * u, "top"))
        z_e = zr - crown
        for k in range(1, 7):
            a = 0.5 * math.pi * k / 6
            pts.append((bt + re * math.sin(a), z_e - re * (1 - math.cos(a)), "edge"))
        y1, z1 = pts[-1][0], pts[-1][1]
        # side glass: frame row (just below the edge), glass, seal row at the belt
        zbelt_vis = self.body.ztop(x) - self.s.get("crown", 0.035)     # where the side meets the body top
        tz = lambda z: (y1 + (bb - y1) * (z1 - z) / max(z1 - zb, 1e-4), z)
        side_z = [z1 - min(0.012, 0.2 * (z1 - zb))]
        for k in range(1, 10):
            side_z.append(z1 + (zbelt_vis + 0.02 - z1) * k / 10)
        side_z += [zbelt_vis + 0.012, zbelt_vis - 0.002, zb]
        kinds = ["frame"] + ["glass"] * 9 + ["seal", "seal", "hidden"]
        for z, k in zip(side_z, kinds):
            z = min(z, z1) if z1 >= zb else zb
            yy, zz = tz(max(min(z, z1), zb))
            pts.append((yy, zz, "side_" + k))
        pts.append((bb * 0.5, zb, "bottom"))
        pts.append((0.0, zb, "bottom"))
        return pts

    def ring(self, x):
        half = self.half_section(x)
        left = [(x, y, z) for y, z, _ in half]
        right = [(x, -y, z) for y, z, _ in reversed(half[1:-1])]
        kinds = [k for _, _, k in half] + [k for _, _, k in reversed(half[1:-1])]
        return left + right, kinds

    def sweep(self, p):
        """Plan sweep: the windshield / backlight curve back at the sides (applied after zoning)."""
        x, y, z = p
        bb = max(self.width_base(x), 0.1)
        wf = smoothstep(self.xh - 0.25, self.xh + 0.05, x)
        wr = smoothstep(self.xre + 0.25, self.xre - 0.05, x)
        q = (y / (self.body.B)) ** 2
        return (x - self.sweep_f * q * wf + self.sweep_r * q * wr, y, z)

    def build(self, zone_fn, extra=()):
        st = self.stations(extra)
        rings, kinds = [], None
        for x in st:
            r, kinds = self.ring(x)
            rings.append(r)
        nj = len(rings[0])
        nh = len(self.half_section(st[0]))
        V = [self.sweep(p) for r in rings for p in r]
        F = grid_faces(len(st), nj, closed_j=True)
        Z = []
        for i in range(len(st) - 1):
            xm = 0.5 * (st[i] + st[i + 1])
            for j in range(nj):
                jm = j if j < nh - 1 else nj - 1 - j
                zm = 0.5 * (rings[i][j][2] + rings[i][(j + 1) % nj][2])
                Z.append(zone_fn(xm, kinds[jm], zm))
        m = Mesh()
        m.add(V, outward(V, F), Z)
        return m, st


# ------------------------------------------------------------------------------------------------ patches
def patch(bvh, centre, axes, outline, offset, rings=(0.0, 0.3, 0.55, 0.75, 0.88, 0.96, 1.0), zone_fn=None,
          wall=True, mirror_y=False):
    """A shell on the body surface: polar grid of `outline` (2D points in the (U, V) plane, ccw) around `centre`,
    ray-cast along D onto the body, lifted `offset` along the surface normal. axes = (U, V, D) unit vectors.
    zone_fn(ring_index, r, k) -> zone. Returns a Mesh (empty if the rays miss)."""
    for scale in (1.0, 0.88, 0.76, 0.64):
        m = _patch(bvh, centre, axes, [(u * scale, v * scale) for u, v in outline], offset, rings, zone_fn, wall, mirror_y)
        if m.f:
            return m
    return Mesh()


def densify(outline, step=0.02):
    out = []
    n = len(outline)
    for k in range(n):
        a, b = np.array(outline[k]), np.array(outline[(k + 1) % n])
        m = max(1, int(np.linalg.norm(b - a) / step))
        out += [tuple(a + (b - a) * t / m) for t in range(m)]
    return out


def _patch(bvh, centre, axes, outline, offset, rings, zone_fn, wall, mirror_y):
    from mathutils import Vector
    U, V, D = (Vector(a) for a in axes)
    C = Vector(centre) + Vector((0.0, 1.7e-4, 0.0))     # never exactly on the y = 0 seam (rays slip through)
    outline = densify(outline)
    n = len(outline)
    pts, ok = [], True
    for ri, r in enumerate(rings):
        row = []
        for k in range(n if r > 0 else 1):
            u, v = (outline[k][0] * r, outline[k][1] * r) if r > 0 else (0.0, 0.0)
            o = C + U * u + V * v - D * 6.0
            hit = bvh.ray_cast(o, D, 12.0)
            if hit[0] is None:
                ok = False
                break
            p = hit[0] + hit[1] * offset
            row.append((p.x, p.y, p.z, hit[0], hit[1]))
        if not ok:
            return Mesh()
        pts.append(row)
    verts, faces, zones = [], [], []
    verts.append(pts[0][0][:3])
    idx = [[0]]
    for ri in range(1, len(rings)):
        base = len(verts)
        idx.append(list(range(base, base + n)))
        verts += [p[:3] for p in pts[ri]]
    for k in range(n):
        kn = (k + 1) % n
        faces.append((0, idx[1][k], idx[1][kn]))
        zones.append(zone_fn(0, rings[1], k) if zone_fn else "black")
    for ri in range(1, len(rings) - 1):
        for k in range(n):
            kn = (k + 1) % n
            faces.append((idx[ri][k], idx[ri + 1][k], idx[ri + 1][kn], idx[ri][kn]))
            zones.append(zone_fn(ri, rings[ri + 1], k) if zone_fn else "black")
    if wall:   # skirt from the outer ring down into the body
        base = len(verts)
        last = pts[-1]
        for p in last:
            q = p[3] - p[4] * 0.004
            verts.append((q.x, q.y, q.z))
        for k in range(n):
            kn = (k + 1) % n
            faces.append((idx[-1][k], base + k, base + kn, idx[-1][kn]))
            zones.append(zone_fn(len(rings) - 1, 1.0, k) if zone_fn else "black")
    # winding: outward = along -D roughly; flip if the first face's normal points along D
    m = Mesh()
    a, b_, c = (np.array(verts[i]) for i in faces[len(faces) // 2][:3])
    nrm = np.cross(b_ - a, c - a)
    if np.dot(nrm, np.array(D)) > 0:
        faces = [tuple(reversed(f)) for f in faces]
    m.add(verts, faces, zones)
    if mirror_y:
        mv = [(x, -y, z) for x, y, z in verts]
        m.add(mv, [tuple(reversed(f)) for f in faces], zones)
    return m


def rrect(w, h, r, n=5, skew=0.0, taper=0.0):
    """Rounded rectangle outline (ccw), centred; skew shifts the top edge in u, taper narrows the top."""
    out = []
    corners = [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)]
    for cx, cy, a0 in corners:
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            u, v = cx + r * math.cos(a), cy + r * math.sin(a)
            t = (v + h / 2) / h
            u = u * (1 - taper * t) + skew * t
            out.append((u, v))
    return out


def ellipse(rx, ry, n=24):
    return [(rx * math.cos(2 * math.pi * k / n), ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


# ------------------------------------------------------------------------------------------------ solids
def box(c, size, zone, rot_z=0.0):
    cx, cy, cz = c
    sx, sy, sz = (s / 2 for s in size)
    P = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz), (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    ca, sa = math.cos(rot_z), math.sin(rot_z)
    P = [(cx + x * ca - y * sa, cy + x * sa + y * ca, cz + z) for x, y, z in P]
    F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    m = Mesh()
    m.add(P, F, zone)
    return m


def rounded_box(c, size, r, zone, n=4):
    """Superellipsoid-ish box (lat-long grid), for mirrors / small housings."""
    cx, cy, cz = c
    sx, sy, sz = (s / 2 for s in size)
    e = 0.35
    nu, nv = 16, 10
    V = []
    for i in range(nv + 1):
        th = -math.pi / 2 + math.pi * i / nv
        for j in range(nu):
            ph = 2 * math.pi * j / nu
            ct, st_ = math.cos(th), math.sin(th)
            cp, sp = math.cos(ph), math.sin(ph)
            sg = lambda v: math.copysign(abs(v) ** e, v)
            V.append((cx + sx * sg(ct) * sg(cp), cy + sy * sg(ct) * sg(sp), cz + sz * sg(st_)))
    F = []
    for i in range(nv):
        for j in range(nu):
            jn = (j + 1) % nu
            F.append((i * nu + j, i * nu + jn, (i + 1) * nu + jn, (i + 1) * nu + j))
    m = Mesh()
    m.add(V, F, zone)
    return m


def lathe(profile, seg, zone_fn, centre=(0, 0, 0), axis_y_sign=1.0):
    """Surface of revolution about the Y axis through `centre`: profile [(r, y)] (y along the axle, + = outboard).
    zone_fn(profile_index, seg_index) -> zone."""
    cx, cy, cz = centre
    V = []
    for k in range(seg):
        a = 2 * math.pi * k / seg
        ca, sa = math.cos(a), math.sin(a)
        for r, y in profile:
            V.append((cx + r * ca, cy + axis_y_sign * y, cz + r * sa))
    n = len(profile)
    F, Z = [], []
    for k in range(seg):
        kn = (k + 1) % seg
        for j in range(n - 1):
            f = (k * n + j, kn * n + j, kn * n + j + 1, k * n + j + 1)
            F.append(tuple(reversed(f)) if axis_y_sign > 0 else f)
            Z.append(zone_fn(j, k))
    m = Mesh()
    m.add(V, F, Z)
    return m


def wheel(s, centre, side):
    """Tyre + rim + brake disc at `centre`, outer face toward side * Y."""
    R, w, rr = s["R"], s["tw"], s["rim_r"]
    sq = 0.012
    # tyre cross-section (r, y) from the inner bead round the tread to the outer bead (y + = outboard)
    prof = []
    hw = w / 2
    sh = 0.035                         # shoulder radius
    side_pts = 7
    for k in range(side_pts):          # inner sidewall (bead -> shoulder)
        t = k / (side_pts - 1)
        r = rr + (R - sh - rr) * t
        prof.append((r, -hw + 0.012 * math.sin(math.pi * t) * -1 - 0.004))
    for k in range(1, 7):              # inner shoulder
        a = 0.5 * math.pi * k / 6
        prof.append((R - sh + sh * math.sin(a), -hw + sh * (1 - math.cos(a))))
    for k in range(1, 6):              # tread
        prof.append((R, -hw + sh + (w - 2 * sh) * k / 5))
    for k in range(1, 7):              # outer shoulder
        a = 0.5 * math.pi * k / 6
        prof.append((R - sh * (1 - math.cos(a)), hw - sh + sh * math.sin(a)))
    for k in range(1, side_pts):       # outer sidewall
        t = k / (side_pts - 1)
        r = R - sh - (R - sh - rr) * t
        prof.append((r, hw + 0.012 * math.sin(math.pi * t) + 0.004 * t))
    seg = 64
    tyre = lathe(prof, seg, lambda j, k: "tyre", centre, side)
    # squash the contact patch
    for i, (x, y, z) in enumerate(tyre.v):
        if z < centre[2] - R + sq:
            tyre.v[i] = (x, y, centre[2] - R + sq)
    m = Mesh()
    m.extend(tyre)
    # rim: barrel + outer lip + spoke face (polar grid, windows removed) + hub
    style = s.get("rim", "silver5")
    nsp = {"silver5": 5, "silver10": 10, "dark6": 6, "silver6": 6, "steel": 8, "silver7": 7}.get(style, 5)
    rim_zone = "rim_dark" if style.startswith("dark") else ("steel" if style == "steel" else "rim")
    yo = hw + 0.004 - 0.012            # outer rim plane (slightly inside the sidewall)
    lip = [(rr + 0.012, yo + 0.004), (rr, yo + 0.006), (rr - 0.012, yo), (rr - 0.016, yo - 0.02), (rr - 0.016, -hw + 0.02),
           (rr + 0.01, -hw + 0.01)]
    m.extend(lathe(lip, seg, lambda j, k: rim_zone, centre, side))
    # spoke face: rings from hub to rim inner radius, angular seg
    face_y = yo - 0.025
    radii = [0.0, 0.045, 0.06, 0.09, rr * 0.55, rr * 0.72, rr * 0.86, rr - 0.016]
    dish = [0.012, 0.012, 0.004, 0.0, -0.006, -0.008, -0.002, 0.018]   # concave face
    V, F, Z = [], [], []
    nseg = 60
    cx, cy, cz = centre
    for i, (r, dz) in enumerate(zip(radii, dish)):
        for k in range(nseg):
            a = 2 * math.pi * k / nseg
            V.append((cx + r * math.cos(a), cy + side * (face_y + dz), cz + r * math.sin(a)))
    for i in range(len(radii) - 1):
        for k in range(nseg):
            kn = (k + 1) % nseg
            am = 2 * math.pi * (k + 0.5) / nseg
            ph = (am * nsp / (2 * math.pi)) % 1.0
            spoke_w = 0.30 if nsp <= 6 else 0.45
            is_window = (radii[i] >= 0.09 and radii[i + 1] <= rr * 0.86 + 1e-6 and not (ph < spoke_w * 0.5 or ph > 1 - spoke_w * 0.5))
            if style == "steel":
                is_window = (abs(radii[i] - rr * 0.72) < 1e-6) and (k % (nseg // nsp) < 2)
            f = (i * nseg + k, i * nseg + kn, (i + 1) * nseg + kn, (i + 1) * nseg + k)
            if side < 0:
                f = tuple(reversed(f))
            if is_window:
                continue
            F.append(f)
            Z.append("chrome" if (i == 0 and style != "steel") else rim_zone)
    mm = Mesh()
    mm.add(V, F, Z)
    m.extend(mm)
    # brake disc + hat behind the spokes (dark), closes the view through the windows
    disc = [(rr - 0.02, face_y - 0.075), (rr * 0.80, face_y - 0.075), (rr * 0.80, face_y - 0.06), (0.0, face_y - 0.06)]
    m.extend(lathe(disc, 48, lambda j, k: "disc", centre, side))
    return m


def liner(xa, zw, Ra, y_out, y_in, side):
    """Wheel-well liner: half cylinder over the wheel (black), facing the wheel."""
    V, F = [], []
    na = 28
    ys = [y_out, y_in]
    for k in range(na + 1):
        a = math.radians(-8 + (180 + 16) * k / na)
        for y in ys:
            V.append((xa + (Ra - 0.008) * math.cos(a), side * y, zw + (Ra - 0.008) * math.sin(a)))
    for k in range(na):
        f = (k * 2, k * 2 + 1, (k + 1) * 2 + 1, (k + 1) * 2)
        F.append(f if side > 0 else tuple(reversed(f)))
    m = Mesh()
    m.add(V, F, "under")
    return m
