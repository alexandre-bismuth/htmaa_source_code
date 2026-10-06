"""STi body shell: a quad control cage (left half, y >= 0) + Mirror + Subdivision Surface with creases.

The cage is a loft: STATIONS along x, and 14 ROWS around each half section (top centre -> floor).
Row meaning in the cabin zone (cowl..deck):
  0 centre top (roof / windshield / backlight centre line)     7 upper door (below the belt)
  1 top mid                                                     8 shoulder crease (character line)
  2 windshield / roof / backlight edge                         9 max width (door bulge)
  3 A-pillar crown / drip rail / C-pillar                      10 lower door
  4 side glass top                                             11 side-skirt crease
  5 side glass mid                                             12 rocker bottom
  6 belt (side glass bottom)                                   13 floor edge
In the hood and deck zones rows 3..6 roll over the fender / quarter top. At both ends every row wraps
around the plan-view corner to the centre plane (superellipse), which closes the nose and the tail
across the mirror plane without poles.
Face attribute "zone": 0 paint, 1 glass, 2 black trim (B-pillar).
"""
import math

import bmesh
import bpy
import numpy as np

from sti_common import G, pchip, tab, new_object

NROW = 14
X_COWL, X_HEADER, X_BF, X_BR, X_ROOF_END, X_GLASS_END, X_DECK = 0.95, 0.26, -0.12, -0.22, -0.92, -1.05, -1.60
X_START_F, X_START_R = 1.93, -1.95
MAIN = [1.93, 1.78, 1.62, 1.46, 1.30, 1.14, 1.02, X_COWL, 0.84, 0.70, 0.55, 0.40, X_HEADER, 0.10, X_BF, X_BR,
        -0.40, -0.60, -0.78, X_ROOF_END, X_GLASS_END, -1.20, -1.36, -1.50, X_DECK, -1.74, -1.86, -1.95]
WRAP_U = [0.30, 0.55, 0.74, 0.88, 1.0]

# --- centre line (row 0) height above ground --------------------------------------------------------
H0 = [(1.93, 0.855), (1.78, 0.893), (1.62, 0.922), (1.46, 0.944), (1.30, 0.960), (1.14, 0.972), (1.02, 0.982),
      (0.95, 0.996), (0.84, 1.062), (0.70, 1.148), (0.55, 1.238), (0.40, 1.322), (0.26, 1.394), (0.10, 1.421),
      (-0.12, 1.428), (-0.40, 1.429), (-0.78, 1.421), (-0.92, 1.408), (-1.05, 1.368), (-1.20, 1.296),
      (-1.36, 1.215), (-1.50, 1.140), (-1.60, 1.090), (-1.74, 1.080), (-1.86, 1.074), (-1.95, 1.066)]
# row 2 (hood edge / windshield edge / roof edge / backlight edge / deck edge) half width
Y2 = [(1.93, 0.50), (1.78, 0.53), (1.62, 0.55), (1.46, 0.565), (1.30, 0.58), (1.14, 0.595), (1.02, 0.61),
      (0.95, 0.672), (0.84, 0.655), (0.70, 0.628), (0.55, 0.598), (0.40, 0.565), (0.26, 0.525), (0.10, 0.478),
      (-0.12, 0.470), (-0.40, 0.470), (-0.78, 0.466), (-0.92, 0.462), (-1.05, 0.478), (-1.20, 0.505),
      (-1.36, 0.537), (-1.50, 0.567), (-1.60, 0.592), (-1.74, 0.650), (-1.86, 0.668), (-1.95, 0.665)]
# side glass top (row 4) height in the cabin zone
H4 = [(0.95, 0.985), (0.84, 1.045), (0.70, 1.125), (0.55, 1.208), (0.40, 1.288), (0.26, 1.345), (0.10, 1.362),
      (-0.40, 1.364), (-0.60, 1.350), (-0.78, 1.300), (-0.92, 1.205), (-1.05, 1.100), (-1.20, 1.086),
      (-1.36, 1.078), (-1.50, 1.072), (-1.60, 1.068)]
# C-pillar crown (row 3) behind the roof
Y3BL = [(-0.92, 0.550), (-1.05, 0.574), (-1.20, 0.608), (-1.36, 0.644), (-1.50, 0.676), (-1.60, 0.696)]
H3BL = [(-0.92, 1.370), (-1.05, 1.318), (-1.20, 1.250), (-1.36, 1.178), (-1.50, 1.118), (-1.60, 1.082)]
# belt (row 6) in the cabin zone
Y6 = [(0.95, 0.768), (0.5, 0.776), (-0.5, 0.778), (-1.05, 0.778), (-1.36, 0.775), (-1.6, 0.768)]
H6 = [(0.95, 0.968), (0.6, 0.982), (0.0, 0.993), (-0.6, 1.000), (-1.05, 1.010), (-1.36, 1.024), (-1.6, 1.040)]
# rows 7..13 (the whole length)
Y7 = [(1.93, 0.770), (1.62, 0.800), (1.30, 0.812), (0.95, 0.808), (0.0, 0.808), (-1.0, 0.812), (-1.3, 0.818),
      (-1.6, 0.815), (-1.95, 0.805)]
H7 = [(1.93, 0.770), (1.62, 0.828), (1.30, 0.860), (1.02, 0.885), (0.95, 0.918), (0.6, 0.930), (0.0, 0.940),
      (-0.9, 0.952), (-1.3, 0.968), (-1.6, 0.982), (-1.95, 0.980)]
Y8 = [(1.93, 0.798), (1.62, 0.832), (1.30, 0.836), (0.95, 0.836), (0.0, 0.836), (-1.0, 0.838), (-1.3, 0.840),
      (-1.6, 0.836), (-1.95, 0.812)]
H8 = [(1.93, 0.720), (1.62, 0.768), (1.30, 0.785), (0.95, 0.800), (0.0, 0.815), (-1.0, 0.830), (-1.6, 0.850),
      (-1.95, 0.840)]
Y9 = [(1.93, 0.815), (1.62, 0.848), (1.30, 0.852), (0.95, 0.852), (0.0, 0.850), (-1.0, 0.852), (-1.25, 0.854),
      (-1.6, 0.852), (-1.95, 0.835)]
Y11 = [(1.93, 0.800), (1.62, 0.838), (1.30, 0.846), (0.95, 0.848), (0.0, 0.848), (-1.0, 0.848), (-1.25, 0.850),
       (-1.6, 0.842), (-1.95, 0.820)]
H11 = [(1.93, 0.290), (1.62, 0.272), (1.0, 0.270), (0.0, 0.268), (-1.0, 0.270), (-1.6, 0.292), (-1.95, 0.305)]
H12 = [(1.93, 0.250), (1.62, 0.215), (1.0, 0.196), (-1.0, 0.196), (-1.6, 0.240), (-1.95, 0.272)]

# nose / tail tips (x, h) per row: the centre-plane profile of the front and rear faces
TIP_F = [(2.066, 0.802), (2.088, 0.778), (2.108, 0.752), (2.124, 0.726), (2.138, 0.700), (2.152, 0.672),
         (2.165, 0.640), (2.176, 0.604), (2.188, 0.556), (2.196, 0.486), (2.197, 0.404), (2.182, 0.312),
         (2.142, 0.252), (2.070, 0.226)]
TIP_R = [(-2.096, 1.034), (-2.112, 1.012), (-2.124, 0.988), (-2.132, 0.962), (-2.138, 0.932), (-2.142, 0.898),
         (-2.146, 0.860), (-2.150, 0.800), (-2.196, 0.722), (-2.212, 0.600), (-2.212, 0.440), (-2.196, 0.326),
         (-2.140, 0.278), (-2.010, 0.246)]
P_F = [2.0, 2.0, 2.0, 2.05, 2.1, 2.15, 2.2, 2.25, 2.3, 2.3, 2.3, 2.25, 2.2, 2.1]
P_R = [2.0, 2.0, 2.1, 2.2, 2.25, 2.3, 2.35, 2.4, 2.5, 2.6, 2.6, 2.5, 2.4, 2.2]


def flare(x):
    """Fender flare bulge (0..1) around both axles."""
    out = 0.0
    for xa in (1.2915, -1.2335):
        d = abs(x - xa) / 0.55
        if d < 1:
            out = max(out, math.cos(0.5 * math.pi * d) ** 2)
    return out


def zone(x):
    if x > X_COWL + 1e-6:
        return "hood"
    if x >= X_HEADER - 1e-6:
        return "ws"
    if x >= X_ROOF_END - 1e-6:
        return "roof"
    if x >= X_DECK - 1e-6:
        return "bl"
    return "deck"


def section(x):
    """14 (x, y, h) points of the half section at station x (h = height above ground)."""
    z = zone(x)
    pts = [None] * NROW
    h0 = tab(x, H0)
    crown = {"hood": 0.010, "ws": 0.022, "roof": 0.012, "bl": 0.028, "deck": 0.008}[z]
    y1 = {"hood": 0.27, "ws": 0.33, "roof": 0.26, "bl": 0.29, "deck": 0.30}[z]
    pts[0] = (x, 0.0, h0)
    y2 = tab(x, Y2)
    drop2 = {"hood": 0.030, "ws": 0.040, "roof": 0.024, "bl": 0.060, "deck": 0.016}[z]
    h2 = h0 - drop2
    # windshield / backlight edges curve in plan (corners further back at the base, forward at the header)
    dx1 = dx2 = 0.0
    if z == "ws":
        t = (X_COWL - x) / (X_COWL - X_HEADER)
        dx2 = -0.075 * (1 - t) + 0.055 * t
        dx1 = 0.35 * dx2
    elif z == "bl":
        t = (X_ROOF_END - x) / (X_ROOF_END - X_DECK)
        dx2 = -0.035 * (1 - t) + 0.085 * t
        dx1 = 0.35 * dx2
    pts[1] = (x + dx1, y1, h0 - crown)
    pts[2] = (x + dx2, y2, h2)
    fl = flare(x)
    y7, h7 = tab(x, Y7) + 0.008 * fl, tab(x, H7)
    if z in ("hood", "deck"):
        # rows 3..6 roll over the fender / quarter top from the hood edge to the upper side
        for j, t in zip((3, 4, 5, 6), (0.22, 0.42, 0.62, 0.80)):
            th = t * 0.5 * math.pi
            pts[j] = (x, y2 + (y7 - y2) * math.sin(th), h7 + (h2 - h7) * math.cos(th) + 0.012 * math.sin(2 * th))
    else:
        y6, h6 = tab(x, Y6), tab(x, H6)
        h4 = tab(x, H4)
        if z == "ws":
            # A-pillar: row 3 is the pillar crown, row 4 the side-glass top outboard / below the windshield edge
            y3, h3 = y2 + 0.034, h2 + 0.022
            y4, h4 = y2 + 0.060, max(h2 - 0.008, h6 + 0.004)
            h3 = max(h3, h4 + 0.012)
            pts[3] = (x + dx2 * 0.8, y3, h3)
            pts[4] = (x + dx2 * 0.6, y4, h4)
        elif z == "roof":
            pts[3] = (x, 0.548, h2 - 0.022)
            y4 = 0.560 + 0.08 * max(0.0, (h2 - 0.024 - h4) / 0.45)
            pts[4] = (x, y4, h4)
        else:   # backlight stations: C-pillar / sail between the backlight edge and the belt
            t = (X_ROOF_END - x) / (X_ROOF_END - X_DECK)
            y3, h3 = tab(x, Y3BL), tab(x, H3BL)
            pts[3] = (x + dx2 * 0.3, y3, h3)
            pts[4] = (x, y3 + 0.55 * (y6 - y3), h4)
        y4, h4 = pts[4][1], pts[4][2]
        pts[5] = (x, y4 + 0.56 * (y6 - y4) + 0.010, h4 + 0.50 * (h6 - h4))
        pts[6] = (x, y6, h6)
    pts[7] = (x, y7, h7)
    pts[8] = (x, tab(x, Y8) + 0.018 * fl, tab(x, H8))
    y9 = tab(x, Y9) + 0.030 * fl
    pts[9] = (x, y9, tab(x, [(1.93, 0.60), (0.0, 0.62), (-1.95, 0.64)]))
    pts[10] = (x, y9 - 0.016, 0.42)
    y11 = tab(x, Y11) + 0.024 * fl - 0.006
    pts[11] = (x, y11, tab(x, H11))
    pts[12] = (x, y11 - 0.040, tab(x, H12))
    pts[13] = (x, 0.55, tab(x, H12) - 0.010)
    return pts


def wrap(sec, tips, pw, u):
    """Move a section toward the centre-plane tip: x linear in u, half width along a superellipse."""
    out = []
    for (x, y, h), (xt, ht), p in zip(sec, tips, pw):
        k = (1 - u ** p) ** (1 / p) if u < 1 else 0.0
        w = 0.5 * u ** 1.3 + 0.5 * (1 - k)
        out.append((x + (xt - x) * u, y * k, h + (ht - h) * w))
    return out


def cage_points():
    """(n_station, NROW, 3) array (z = mesh z) and the station zone names."""
    secs, zones = [], []
    front = section(X_START_F)
    for u in reversed(WRAP_U):
        secs.append(wrap(front, TIP_F, P_F, u))
        zones.append("nose")
    for x in MAIN:
        secs.append(section(x))
        zones.append(zone(x))
    rear = section(X_START_R)
    for u in WRAP_U:
        secs.append(wrap(rear, TIP_R, P_R, u))
        zones.append("tail")
    P = np.array(secs, float)
    P[:, :, 2] += G
    return P, zones


def face_zone(xa, xb, j):
    """zone of the cage face between stations xa > xb and rows j, j+1."""
    xm = 0.5 * (xa + xb)
    if j <= 1 and X_HEADER < xm < X_COWL:
        return 1                     # windshield
    if j <= 1 and X_DECK < xm < X_ROOF_END:
        return 1                     # backlight
    if j in (4, 5) and X_GLASS_END < xm < X_COWL:
        if X_BR < xm < X_BF:
            return 2                 # B-pillar
        return 1                     # side glass
    return 0


CREASES = {8: 0.5, 11: 0.70, 12: 0.45}


def build_cage(name="sti_body_cage", levels=3):
    P, zones = cage_points()
    ns = P.shape[0]
    xs = [MAIN[i - len(WRAP_U)] if zones[i] not in ("nose", "tail") else None for i in range(ns)]
    bm = bmesh.new()
    V = [[bm.verts.new(P[i, j]) for j in range(NROW)] for i in range(ns)]
    zl = bm.faces.layers.int.new("zone")
    cl = bm.edges.layers.float.new("crease_edge")
    faces = {}
    for i in range(ns - 1):
        for j in range(NROW - 1):
            # winding: outward normal (stations go front -> rear, rows top -> bottom)
            f = bm.faces.new((V[i][j], V[i][j + 1], V[i + 1][j + 1], V[i + 1][j]))
            zval = 0
            if xs[i] is not None and xs[i + 1] is not None:
                zval = face_zone(xs[i], xs[i + 1], j)
            f[zl] = zval
            f.smooth = True
            faces[i, j] = f
    bm.normal_update()
    # creases: character lines along rows, and every glass / trim boundary
    for i in range(ns - 1):
        for j, c in CREASES.items():
            e = bm.edges.get((V[i][j], V[i + 1][j]))
            e[cl] = max(e[cl], c)
        if zones[i] == "tail" and abs(P[i, 0, 0] - (-1.95 + (TIP_R[0][0] + 1.95) * 0.74)) < 1e-6:
            # boot lid: crisp edge where the deck turns down into the rear face
            for j in range(0, 7):
                e = bm.edges.get((V[i][j], V[i][j + 1]))
                if e is not None:
                    e[cl] = max(e[cl], 0.6)
        if zones[i] == "tail" or zones[i + 1] == "tail" or xs[i] is not None and xs[i] <= -1.86:
            # rear bumper: a crisp top shelf that steps out from the boot face
            e = bm.edges.get((V[i][8], V[i + 1][8]))
            e[cl] = max(e[cl], 0.95)
    for e in bm.edges:
        zs = {f[zl] for f in e.link_faces}
        if len(zs) > 1:
            e[cl] = 1.0
    ob = new_object(name, bm)
    m = ob.modifiers.new("mirror", "MIRROR")
    m.use_axis = (False, True, False)
    m.use_clip = True
    m.use_mirror_merge = True
    m.merge_threshold = 1e-4
    s = ob.modifiers.new("subsurf", "SUBSURF")
    s.levels = s.render_levels = levels
    s.uv_smooth = "PRESERVE_BOUNDARIES"
    s.boundary_smooth = "ALL"
    return ob


# ------------------------------------------------------------------------------------------------
# Openings: every opening is a closed convex cutter. The body is closed at the floor, all cutters are
# subtracted with one exact boolean, the cutter walls are dropped again, and every new hole gets a
# flange (return) so the shell never shows a paper-thin edge. "swap" cutters also return the patch of
# skin they removed (used as the flush lamp lenses).
import mathutils
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

ARCH_R = {1.2915: 0.348, -1.2335: 0.346}
ARCH_ZC = 0.231 + 0.012          # arch centre slightly above the axle (arches are taller than wide)


class Cut:
    def __init__(self, name, bm, flange, swap=False):
        self.name, self.bm, self.flange, self.swap = name, bm, flange, swap
        self.bvh = BVHTree.FromBMesh(bm)


def hull_of_spheres(spheres, seg=24):
    """Convex hull of spheres [(centre, r)] -> bmesh (a smooth rounded blob)."""
    bm = bmesh.new()
    pts = []
    for c, r in spheres:
        for i in range(seg // 2 + 1):
            th = math.pi * i / (seg // 2)
            for k in range(seg):
                ph = 2 * math.pi * k / seg
                pts.append(Vector(c) + r * Vector((math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th))))
    vs = [bm.verts.new(p) for p in pts]
    res = bmesh.ops.convex_hull(bm, input=vs)
    bmesh.ops.delete(bm, geom=list(set(res["geom_interior"]) | set(res["geom_unused"])), context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def prism(outline, axis, a0, a1):
    """Closed prism: 2D outline (CCW, coords of the two other axes in order) extruded along axis a0..a1."""
    bm = bmesh.new()
    def P(u, v, a):
        if axis == "x":
            return (a, u, v)
        if axis == "y":
            return (u, a, v)
        return (u, v, a)
    lo = [bm.verts.new(P(u, v, a0)) for u, v in outline]
    hi = [bm.verts.new(P(u, v, a1)) for u, v in outline]
    n = len(outline)
    for k in range(n):
        bm.faces.new((lo[k], lo[(k + 1) % n], hi[(k + 1) % n], hi[k]))
    bm.faces.new(lo[::-1])
    bm.faces.new(hi)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def rounded_rect(u0, v0, u1, v1, r, n=8, taper=0.0):
    """CCW rounded rectangle outline; taper narrows the bottom edge (u) by that amount on each side."""
    pts = []
    corners = [(u1 - r, v0 + r, -90, 0, taper), (u1 - r, v1 - r, 0, 90, 0), (u0 + r, v1 - r, 90, 180, 0),
               (u0 + r, v0 + r, 180, 270, -taper)]
    for cu, cv, a0, a1, t in corners:
        for k in range(n + 1):
            a = math.radians(a0 + (a1 - a0) * k / n)
            pts.append((cu - t + r * math.cos(a), cv + r * math.sin(a)))
    return pts


def circle(u, v, r, n=48):
    return [(u + r * math.cos(2 * math.pi * k / n), v + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def mirror_bm(bm):
    """Copy of bm mirrored to y < 0 (normals fixed)."""
    out = bm.copy()
    bmesh.ops.scale(out, vec=(1, -1, 1), verts=out.verts)
    bmesh.ops.reverse_faces(out, faces=out.faces)
    return out


def arch_bm(xa, r, sgn):
    bm = bmesh.new()
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=160, radius1=r, radius2=r, depth=0.9)
    M = Matrix.Translation((xa, sgn * 0.88, ARCH_ZC)) @ Matrix.Rotation(math.pi / 2, 4, "X")
    bmesh.ops.transform(bm, matrix=M, verts=res["verts"])
    return bm


def cutter_object(name, bms, zones=None):
    """Join cutter bmeshes into one object. Faces carry zone 99 (walls dropped after the boolean) unless a
    zone is given per bmesh: 2 = kept as a dark groove wall (panel gaps), 3 = kept as painted recess."""
    bm = bmesh.new()
    zl = bm.faces.layers.int.new("zone")
    me_tmp = bpy.data.meshes.new("tmp")
    for k, b in enumerate(bms):
        n0 = len(bm.faces)
        b.to_mesh(me_tmp)
        bm.from_mesh(me_tmp)
        bm.faces.ensure_lookup_table()
        z = 99 if zones is None else zones[k]
        for f in bm.faces[n0:]:
            f[zl] = z
    bpy.data.meshes.remove(me_tmp)
    ob = new_object(name, bm)
    ob.hide_render = True
    return ob


def drop_zones(ob, zones=(98, 99)):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    zl = bm.faces.layers.int.get("zone")
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[zl] in zones], context="FACES")
    bm.to_mesh(ob.data)
    bm.free()


def close_bottom(ob):
    """Cap the open floor loop (zone 98) so the shell is a closed solid for exact booleans."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    zl = bm.faces.layers.int.get("zone")
    edges = [e for e in bm.edges if e.is_boundary]
    if edges:
        res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=edges)
        for f in res["geom"]:
            if isinstance(f, bmesh.types.BMFace):
                f[zl] = 98
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()


def boolean(ob, cutter, op="DIFFERENCE"):
    from sti_common import evaluated_mesh
    m = ob.modifiers.new("bool", "BOOLEAN")
    m.operation = op
    m.solver = "EXACT"
    m.object = cutter
    m.use_hole_tolerant = False
    m.use_self = True
    me = evaluated_mesh(ob)
    ob.modifiers.clear()
    old = ob.data
    ob.data = me
    bpy.data.meshes.remove(old)
    drop_zones(ob)
    return ob


ROLL = [(0.0006, 0.0018), (0.0022, 0.0034), (0.0045, 0.0043)]


def flanges(ob, cuts):
    """Return-flange strips (a separate bmesh, zone per cut) along every hole made by `cuts`.
    flange spec: dict(dir=Vector or "arch", depth=(d1, d2), out=(o1, o2), zone=int, xa=axle x)."""
    src = bmesh.new()
    src.from_mesh(ob.data)
    out = bmesh.new()
    zl = out.faces.layers.int.new("zone")
    vmap = {}
    for e in src.edges:
        if not e.is_boundary:
            continue
        mid = (e.verts[0].co + e.verts[1].co) / 2
        best = None
        for c in cuts:
            loc, nrm, idx, dist = c.bvh.find_nearest(mid)
            if loc is not None and dist < 0.003 and (best is None or dist < best[1]):
                best = (c, dist)
        if best is None:
            continue
        cut = best[0]
        fs = cut.flange
        f0 = e.link_faces[0]
        a, b = e.verts
        loop = next(l for l in f0.loops if l.edge == e)
        if loop.vert != a:
            a, b = b, a
        ring = []
        for v in (a, b):
            key = v.index
            if key not in vmap:
                co = v.co.copy()
                if fs["dir"] == "arch":
                    sgn = 1 if co.y > 0 else -1
                    d = Vector((0, -sgn, 0))
                    o = Vector((co.x - fs["xa"], 0, co.z - ARCH_ZC)).normalized()
                    o_r = o.copy()
                    o *= max(0.0, o.z) ** 1.5          # roll the lip only over the top of the arch
                elif fs["dir"] == "normal":
                    loc, nrm, idx, dist = cut.bvh.find_nearest(co)
                    d = -Vector(fs["n"]) if co.y > 0 else -Vector(fs["n"]) * Vector((1, -1, 1))
                    o = Vector((0, 0, 0))
                else:
                    d = Vector(fs["dir"]).normalized()
                    if co.y < 0:
                        d.y = -d.y
                    loc, nrm, idx, dist = cut.bvh.find_nearest(co)
                    o = (nrm - d * nrm.dot(d)).normalized() if nrm is not None else Vector()
                    o_r = o.copy()
                vs = [out.verts.new(co)]
                # rounded (rolled) edge, radius ~4.5 mm, curling into the opening, then the straight return
                for dd, oo in ROLL:
                    vs.append(out.verts.new(co + d * dd - o_r * oo))
                for dd, oo in zip(fs["depth"], fs["out"]):
                    vs.append(out.verts.new(co + d * (dd + ROLL[-1][0]) + o * oo - o_r * ROLL[-1][1]))
                vmap[key] = vs
            ring.append(vmap[key])
        ra, rb = ring
        for k in range(len(ra) - 1):
            try:
                f = out.faces.new((rb[k], ra[k], ra[k + 1], rb[k + 1]))
                zs = fs.get("zone", (0, 0))
                f[zl] = 0 if k < len(ROLL) else zs[k - len(ROLL)]
            except ValueError:
                pass
    src.free()
    return out


def body_skin(levels=3):
    """Evaluated (mirrored, subdivided) body skin object with the 'zone' face attribute."""
    from sti_common import evaluated_mesh, remove
    cage = build_cage(levels=levels)
    me = evaluated_mesh(cage, "sti_body_skin")
    remove(cage)
    return new_object("sti_body_skin", me)


def make_cuts():
    cuts = []
    for xa, r in ARCH_R.items():
        for sgn in (1, -1):
            cuts.append(Cut("arch", arch_bm(xa, r, sgn),
                            dict(dir="arch", xa=xa, depth=(0.012, 0.070), out=(0.004, 0.045), zone=(0, 0))))
    # bugeye headlamp: a teardrop that wraps the nose corner (round lamp low-inboard, tail up the fender)
    hl = hull_of_spheres(HEADLAMP_SPHERES)
    for b in (hl, mirror_bm(hl)):
        cuts.append(Cut("headlamp", b, dict(dir=(-0.75, -0.65, 0.0), depth=(0.006, 0.045), out=(0, 0), zone=(2, 2)),
                        swap=True))
    tl = hull_of_spheres(TAILLAMP_SPHERES)
    for b in (tl, mirror_bm(tl)):
        cuts.append(Cut("taillamp", b, dict(dir=(0.8, -0.6, 0.0), depth=(0.006, 0.035), out=(0, 0), zone=(2, 2)),
                        swap=True))
    # front: grille, lower intake, fog-lamp pockets; rear: licence-plate recess
    cuts.append(Cut("grille", prism([(y, h + G) for y, h in GRILLE], "x", 1.90, 2.40),
                    dict(dir=(-1, 0, 0), depth=(0.006, 0.075), out=(0.0, -0.004), zone=(0, 2))))
    cuts.append(Cut("intake", prism([(y, h + G) for y, h in INTAKE], "x", 1.90, 2.40),
                    dict(dir=(-1, 0, 0), depth=(0.006, 0.090), out=(0.0, -0.006), zone=(0, 2))))
    for sgn in (1, -1):
        cuts.append(Cut("fog", prism([(sgn * FOG[0] + u, FOG[1] + G + v) for u, v in circle(0, 0, FOG[2])], "x", 1.90, 2.40),
                        dict(dir=(-1, 0, 0), depth=(0.005, 0.060), out=(0.0, -0.008), zone=(0, 2))))
    cuts.append(Cut("plate", prism([(-y, h + G) for y, h in PLATE], "x", -2.45, -2.05),
                    dict(dir=(1, 0, 0), depth=(0.004, 0.020), out=(0.0, -0.003), zone=(0, 0))))
    return cuts


G_ = G
HEADLAMP_SPHERES = [((2.075, 0.598, 0.718 + G_), 0.112), ((1.955, 0.745, 0.802 + G_), 0.052)]
TAILLAMP_SPHERES = [((-2.088, 0.505, 0.912 + G_), 0.040), ((-2.040, 0.738, 0.915 + G_), 0.046),
                    ((-2.012, 0.752, 0.772 + G_), 0.058), ((-2.082, 0.628, 0.742 + G_), 0.038)]
GRILLE = rounded_rect(-0.36, 0.588, 0.36, 0.708, 0.035, taper=0.035)
INTAKE = rounded_rect(-0.40, 0.290, 0.40, 0.500, 0.05, taper=-0.03)
FOG = (0.625, 0.430, 0.078)
PLATE = rounded_rect(-0.188, 0.425, 0.188, 0.605, 0.022)


def cut_body(skin, grooves=(), recesses=()):
    """Subtract every opening, plus the panel-gap groove tubes (kept as dark walls, zone 2) and painted
    recesses such as door-handle dishes (kept, zone 3).
    Returns (skin with holes, flange bmesh, {swap name: [patch bmesh]})."""
    from sti_common import remove
    cuts = make_cuts()
    close_bottom(skin)
    patches = {}
    for c in cuts:
        if not c.swap:
            continue
        tmp = new_object("swap_tmp", skin.data.copy())
        cutter = cutter_object("swap_cutter", [c.bm])
        boolean(tmp, cutter, "INTERSECT")
        b = bmesh.new()
        b.from_mesh(tmp.data)
        patches.setdefault(c.name, []).append(b)
        remove(tmp)
        remove(cutter)
    bms = [c.bm for c in cuts] + list(grooves) + list(recesses)
    zones = [99] * len(cuts) + [2] * len(grooves) + [3] * len(recesses)
    cutter = cutter_object("cutters", bms, zones)
    boolean(skin, cutter)
    remove(cutter)
    fl = flanges(skin, cuts)
    return skin, fl, patches


def boundary_loops(bm, pred):
    """Closed vertex loops along edges for which pred(edge) is true."""
    adj = {}
    for e in bm.edges:
        if pred(e):
            a, b = e.verts
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in adj:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [v for v in adj[cur] if v is not prev and v not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            loop.append(cur)
            seen.add(cur)
        if len(loop) > 3:
            loops.append(loop)
    return loops


def sweep(loop_pts, loop_nrm, profile, closed=True):
    """Sweep a 2D profile [(across, up)] along a polyline with per-point surface normals -> bmesh."""
    bm = bmesh.new()
    n = len(loop_pts)
    rings = []
    for i in range(n):
        p = loop_pts[i]
        t = (loop_pts[(i + 1) % n] - loop_pts[i - 1]) if closed else (loop_pts[min(i + 1, n - 1)] - loop_pts[max(i - 1, 0)])
        t.normalize()
        nn = loop_nrm[i] - t * loop_nrm[i].dot(t)
        nn.normalize()
        b = t.cross(nn)
        rings.append([bm.verts.new(p + b * a + nn * u) for a, u in profile])
    m = len(profile)
    for i in range(n if closed else n - 1):
        r0, r1 = rings[i], rings[(i + 1) % n]
        for k in range(m - 1):
            bm.faces.new((r0[k], r0[k + 1], r1[k + 1], r1[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


GLASS_INSET = 0.009      # glass sits 9 mm behind the body skin; the rubber seal bridges the step


def grid_surface_closed(rows):
    bm = bmesh.new()
    V = [[bm.verts.new(p) for p in r] for r in rows]
    n, m = len(V), len(V[0])
    for i in range(n):
        for j in range(m - 1):
            try:
                bm.faces.new((V[i][j], V[(i + 1) % n][j], V[(i + 1) % n][j + 1], V[i][j + 1]))
            except ValueError:
                pass
    bm.normal_update()
    for f in bm.faces:
        if f.normal.dot(f.calc_center_median() - Vector((0.0, 0.0, 0.5 + G))) < 0:
            f.normal_flip()
    return bm


RUBBER = [(-0.0128, -0.0105), (-0.0122, -0.0045), (-0.0112, 0.0026), (-0.008, 0.0056), (0.0, 0.0064), (0.008, 0.0056),
          (0.0112, 0.0026), (0.0122, -0.0045), (0.0128, -0.0105)]


def split_skin(skin, src_bvh):
    """-> dict: 'paint' (bmesh, skin faces zone 0), 'glass' (inset zone 1), 'black' (zone 2 + rubber)."""
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    bm.normal_update()
    zl = bm.faces.layers.int.get("zone")
    out = {}
    # rubber seals along every glass boundary (normals from the uncut source surface)
    is_glass_edge = lambda e: len({f[zl] == 1 for f in e.link_faces}) == 2 or (e.is_boundary and e.link_faces and e.link_faces[0][zl] == 1)
    rub = bmesh.new()
    for loop in boundary_loops(bm, is_glass_edge):
        pts = [v.co.copy() for v in loop]
        nrm = []
        for v in loop:
            nrm.append(v.normal.copy())
        sw = sweep(pts, nrm, RUBBER)
        me = bpy.data.meshes.new("t")
        sw.to_mesh(me)
        rub.from_mesh(me)
        bpy.data.meshes.remove(me)
        sw.free()
    frit = bmesh.new()
    for loop in boundary_loops(bm, is_glass_edge):
        c = sum((v.co for v in loop), Vector()) / len(loop)
        if abs(c.y) > 0.3 or not (c.x > 0.2 or c.x < -0.85):
            continue                                   # windshield and backlight only
        n = len(loop)
        rows = []
        for i, v in enumerate(loop):
            t = (loop[(i + 1) % n].co - loop[i - 1].co).normalized()
            nn = v.normal.normalized()
            b = t.cross(nn).normalized()
            if b.dot(c - v.co) < 0:
                b = -b
            base = v.co - nn * (GLASS_INSET - 0.0012)
            rows.append([base + b * 0.004, base + b * 0.030, base + b * 0.050])
        rib = grid_surface_closed(rows)
        me = bpy.data.meshes.new("t")
        rib.to_mesh(me)
        frit.from_mesh(me)
        bpy.data.meshes.remove(me)
        rib.free()
    for name, zvs in (("paint", (0, 3)), ("glass", (1,)), ("black", (2,))):
        b = bm.copy()
        zl2 = b.faces.layers.int.get("zone")
        bmesh.ops.delete(b, geom=[f for f in b.faces if f[zl2] not in zvs], context="FACES")
        if zvs == (1,):
            b.normal_update()
            for v in b.verts:
                v.co -= v.normal * GLASS_INSET
        out[name] = b
    out["frit"] = frit
    out["rubber"] = rub
    bm.free()
    return out
