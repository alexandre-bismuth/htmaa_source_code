"""Paint UVs (planar projection islands), panel-line / decal layout, livery texture generation and the custom
normal transfer for the body paint.

UV0 layout of sti_paint (one 4096^2 atlas, uniform texel density, ~0.75 mm/px):
  left side  (+Y faces)  projected on (-x, z): front of the car on the image left, text reads normally
  right side (-Y faces)  projected on (x, z)
  top        (+Z faces)  projected on (-x, y)
  front      (+X faces)  projected on (y, z)  (as seen standing in front of the car)
  rear       (-X faces)  projected on (-y, z) (as seen standing behind the car)
  hidden     flanges / returns: a small plain-paint patch
Each face goes to the island of its dominant normal axis; a few regions are forced so decals never straddle an
island seam. The livery itself is drawn by tools/blender/sti_livery.py (PIL, run through uv in tools/mapgen).
"""
import json
import math
import subprocess
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from sti_common import G, evaluated_mesh, new_object, remove, tab

import tempfile
TEX = 4096
LAYOUT = Path(tempfile.gettempdir()) / "sti_livery_layout.json"   # intermediate, read by sti_livery.py
MARGIN = 20
ISLANDS = {   # name: ((axis, sign) for u, (axis, sign) for v)
    "left": ((0, -1), (2, 1)),
    "right": ((0, 1), (2, 1)),
    "top": ((0, -1), (1, 1)),
    "front": ((1, 1), (2, 1)),
    "rear": ((1, -1), (2, 1)),
}
# faces whose centroid falls in a box are forced to an island (so a decal stays on one projection)
FORCE = [
    ("front", (1.93, 2.30), (-0.42, 0.42), (0.68 + G, 0.86 + G)),   # "SUBARU" on the hood nose
]


def island_of(c, n):
    for name, (x0, x1), (y0, y1), (z0, z1) in FORCE:
        if x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1 and n.x > 0.05:
            return name
    ax, ay, az = abs(n.x), abs(n.y), abs(n.z) * 1.12
    if az >= ax and az >= ay:
        if n.z > 0:
            return "top"
        if max(ax, ay) < 0.2:
            return "bottom"
    if ay >= ax:
        return "left" if n.y > 0 else "right"
    return "front" if n.x > 0 else "rear"


def project(name, p):
    (a, sa), (b, sb) = ISLANDS[name]
    return sa * p[a], sb * p[b]


def layout(ext):
    """ext: island -> (umin, umax, vmin, vmax) in metres. Returns island -> dict(x0, y0, s, umin, vmax)."""
    w = {k: e[1] - e[0] for k, e in ext.items()}
    h = {k: e[3] - e[2] for k, e in ext.items()}
    rows = [["left"], ["right"], ["top"], ["front", "rear"]]
    width = max(sum(w[k] for k in r) for r in rows)
    height = sum(max(h[k] for k in r) for r in rows)
    s = min((TEX - 3 * MARGIN) / width, (TEX - (len(rows) + 1) * MARGIN - 40) / height)
    out, y = {}, MARGIN
    for r in rows:
        x = MARGIN
        for k in r:
            out[k] = dict(x0=x, y0=y, s=s, umin=ext[k][0], vmax=ext[k][3], w=w[k] * s, h=h[k] * s)
            x += w[k] * s + MARGIN
        y += max(h[k] for k in r) * s + MARGIN
    out["hidden"] = dict(x0=TEX - 40, y0=TEX - 40, s=0, umin=0, vmax=0, w=24, h=24)
    return out


def uv_of(isl, u, v):
    px = isl["x0"] + (u - isl["umin"]) * isl["s"]
    py = isl["y0"] + (isl["vmax"] - v) * isl["s"]
    return px / TEX, 1.0 - py / TEX


# --- panel lines, defined in a projection and lifted onto the (uncut) surface ------------------------------
def lift(bvh, pts2d, view, side=1):
    """pts2d in the view plane -> [(p, n)] on the surface. view: 'side' (x,h), 'top' (x,y), 'front' (y,h),
    'rear' (y,h). Heights h are above ground."""
    out = []
    for a, b in pts2d:
        if view == "side":
            o, d = Vector((a, side * 3.0, b + G)), Vector((0, -side, 0))
        elif view == "top":
            o, d = Vector((a, side * b, 3.0)), Vector((0, 0, -1))
        elif view == "front":
            o, d = Vector((4.0, side * a, b + G)), Vector((-1, 0, 0))
        else:
            o, d = Vector((-4.0, side * a, b + G)), Vector((1, 0, 0))
        loc, n, i, dist = bvh.ray_cast(o, d)
        if loc is not None:
            out.append((tuple(loc), tuple(n)))
    return out


def densify(pts, step=0.01):
    out = []
    for (a0, b0), (a1, b1) in zip(pts[:-1], pts[1:]):
        k = max(1, int(math.hypot(a1 - a0, b1 - b0) / step))
        out += [(a0 + (a1 - a0) * t / k, b0 + (b1 - b0) * t / k) for t in range(k)]
    return out + [pts[-1]]


def smooth_curve(pts, n=80):
    """Catmull-Rom through the points -> n samples."""
    P = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for k in range(n + 1):
        t = k / n * (len(pts) - 1)
        i = min(int(t), len(pts) - 2)
        u = t - i
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * u + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * u * u
                                + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * u ** 3) for j in range(2)))
    return out


def rounded_box_2d(cx, cy, w, h, r, n=6):
    pts = []
    for (qx, qy), a0 in (((1, 1), 0), ((-1, 1), 90), ((-1, -1), 180), ((1, -1), 270)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + qx * (w / 2 - r) + r * math.cos(a), cy + qy * (h / 2 - r) + r * math.sin(a)))
    return pts + [pts[0]]


def panel_lines(bvh):
    """List of dict(pts=[(p, n)], w=gap width m, depth=0..1)."""
    L = []

    def add(pts, view, side=1, w=0.0045, curve=True):
        p2 = smooth_curve(pts, max(20, int(40 * len(pts)))) if curve and len(pts) > 2 else densify(pts)
        lp = lift(bvh, densify(p2, 0.006), view, side)
        if len(lp) > 1:
            L.append(dict(pts=lp, w=w))

    for side in (1, -1):
        # doors (side view, heights above ground)
        add([(0.845, 0.975), (0.815, 0.86), (0.800, 0.68), (0.800, 0.45), (0.808, 0.302)], "side", side)
        add([(0.808, 0.302), (0.30, 0.300), (-0.40, 0.300), (-0.86, 0.302)], "side", side)
        add([(-0.128, 0.995), (-0.140, 0.80), (-0.155, 0.50), (-0.165, 0.300)], "side", side)
        add([(-1.045, 1.012), (-1.020, 0.90), (-0.965, 0.775), (-0.895, 0.66), (-0.862, 0.52), (-0.858, 0.40),
             (-0.862, 0.302)], "side", side)
        # front bumper / fender seam, rear bumper / quarter seam and rear bumper top
        add([(1.905, 0.700), (1.835, 0.600), (1.760, 0.520), (1.700, 0.470)], "side", side)
        add([(-1.965, 0.740), (-1.880, 0.670), (-1.790, 0.600), (-1.690, 0.520), (-1.640, 0.490)], "side", side)
        add([(-1.965, 0.740), (-2.060, 0.725), (-2.130, 0.712)], "side", side)
        add([(0.82, 0.712), (0.55, 0.712), (0.25, 0.712)], "rear", side)
        # hood edges (top view: x, y) and the hood nose
        add([(2.040, 0.430), (1.975, 0.515), (1.80, 0.552), (1.50, 0.572), (1.20, 0.588), (0.99, 0.600)], "top", side)
        add([(2.064, 0.0), (2.060, 0.18), (2.052, 0.31), (2.040, 0.430)], "top", side)
        # trunk lid (top view) and its rear edge (rear view)
        add([(-1.640, 0.0), (-1.640, 0.45), (-1.648, 0.565), (-1.700, 0.598), (-2.000, 0.600), (-2.075, 0.585)],
            "top", side)
        add([(0.0, 0.955), (0.30, 0.955), (0.46, 0.950)], "rear", side, curve=False)
    # fuel filler door, right rear quarter
    add(rounded_box_2d(-1.56, 0.875, 0.175, 0.115, 0.025), "side", -1, curve=False)
    return L


def handles():
    """Door handle recess centres (x, h) - the handle geometry is in sti_details."""
    return [(-0.005, 0.885), (-0.900, 0.900)]


def write_layout(me, isl_of_face, ext, OUT, bvh):
    lay = layout(ext)
    data = dict(tex=TEX, islands=lay, axes={k: v for k, v in ISLANDS.items()}, ground=G,
                lines=panel_lines(bvh), handles=handles())
    # side decals are defined in side view; give the livery script the surface height span of the doors
    LAYOUT.write_text(json.dumps(data))
    return lay


def finish_paint(me, src_me, OUT, ARGS):
    """UV-unwrap the joined paint mesh, (re)draw the livery, transfer smooth normals from the uncut skin."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    sl = bm.verts.layers.int.get("skin")
    src_bm = bmesh.new()
    src_bm.from_mesh(src_me)
    bvh = BVHTree.FromBMesh(src_bm)
    isl = {}
    ext = {k: [1e9, -1e9, 1e9, -1e9] for k in ISLANDS}
    zl = bm.faces.layers.int.get("zone")
    pl = bm.faces.layers.int.get("proj")
    for f in bm.faces:
        recess = zl is not None and f[zl] == 3
        if pl is None or not f[pl]:
            isl[f.index] = "hidden"
            continue
        c = f.calc_center_median()
        loc, n, i, d = bvh.find_nearest(c)
        name = island_of(c, n if (n is not None and not recess) else f.normal)
        if name == "bottom":
            name = "hidden"
        isl[f.index] = name
        if name in ext:
            e = ext[name]
            for v in f.verts:
                u, w = project(name, v.co)
                e[0], e[1], e[2], e[3] = min(e[0], u), max(e[1], u), min(e[2], w), max(e[3], w)
    lay = write_layout(me, isl, ext, OUT, bvh)
    uvl = bm.loops.layers.uv.new("UV0")
    hid = lay["hidden"]
    for f in bm.faces:
        name = isl[f.index]
        for k, l in enumerate(f.loops):
            if name == "hidden":
                l[uvl].uv = ((hid["x0"] + 4 + 16 * (k % 2)) / TEX, 1 - (hid["y0"] + 4 + 16 * (k // 2 % 2)) / TEX)
            else:
                l[uvl].uv = uv_of(lay[name], *project(name, l.vert.co))
    bm.to_mesh(me)
    bm.free()
    src_bm.free()

    if "--no-livery" not in ARGS or not (OUT / "sti_livery.png").exists():
        root = Path(__file__).resolve().parents[2]
        subprocess.run(["uv", "run", "--project", str(root / "tools/mapgen"), "python",
                        str(Path(__file__).resolve().parent / "sti_livery.py"), str(OUT), str(LAYOUT)], check=True)

    # smooth normals of the uncut surface on every skin vertex (booleans leave slivers along the cuts)
    ob = new_object("paint_tmp", me)
    src = new_object("paint_src", src_me)
    vg = ob.vertex_groups.new(name="skin")
    attr = me.attributes["skin"].data
    vg.add([i for i in range(len(me.vertices)) if attr[i].value], 1.0, "REPLACE")
    m = ob.modifiers.new("dt", "DATA_TRANSFER")
    m.object = src
    m.use_loop_data = True
    m.data_types_loops = {"CUSTOM_NORMAL"}
    m.loop_mapping = "POLYINTERP_NEAREST"
    m.vertex_group = "skin"
    out = evaluated_mesh(ob, "sti_paint")
    for a in ("skin",):
        if a in out.attributes:
            out.attributes.remove(out.attributes[a])
    remove(ob)
    bpy.data.objects.remove(src)
    return out


def box_uv(me):
    """Simple box-projected UV0 for the non-textured parts (keeps every glb with TEXCOORD_0)."""
    if not me.polygons:
        return
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    uvl = me.uv_layers.new(name="UV0")
    for p in me.polygons:
        n = p.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        a, b = [k for k in range(3) if k != ax]
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = (co[a] * 2.0, co[b] * 2.0)


def keep_uv0(me):
    """Keep the authored UV layer as the only one, named UV0."""
    while len(me.uv_layers) > 1:
        me.uv_layers.remove(me.uv_layers[-1])
    if me.uv_layers:
        me.uv_layers[0].name = "UV0"
    else:
        box_uv(me)
