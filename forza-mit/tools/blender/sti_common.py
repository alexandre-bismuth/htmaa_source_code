"""Shared constants and small helpers for the Blender STi build (tools/blender/build_sti.py).

Frame: Blender metres, X = car forward, Y = car LEFT, Z = up (Blender's default glTF export writes
glTF (x, z, -y), identical to the old tools/mapgen/gltf.py enu_to_gltf). Origin = the vehicle mesh root;
the ground plane is at z = G at rest.
"""
import math

import bmesh
import bpy
import numpy as np

G = -0.086                        # ground z
XA_F, XA_R = 1.2915, -1.2335      # axles
TRACK_F, TRACK_R = 1.485, 1.490
WHEEL_Z = 0.231                   # wheel centre height at rest
R_TIRE = 0.317                    # 225/45R17
W_TIRE = 0.225
R_RIM = 17 * 0.0254 / 2           # 0.2159 bead seat radius


def pchip(x, xs, ys):
    """Monotone cubic (Fritsch-Carlson) interpolation; xs ascending or descending; clamps outside."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    if xs[0] > xs[-1]:
        xs, ys = xs[::-1], ys[::-1]
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
    """pchip over a list of (x, value) pairs."""
    xs, ys = zip(*pts)
    return pchip(x, xs, ys)


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def link(obj, coll=None):
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def new_object(name, bm_or_mesh, coll=None):
    if isinstance(bm_or_mesh, bmesh.types.BMesh):
        me = bpy.data.meshes.new(name)
        bm_or_mesh.to_mesh(me)
        bm_or_mesh.free()
    else:
        me = bm_or_mesh
    ob = bpy.data.objects.new(name, me)
    return link(ob, coll)


def evaluated_mesh(ob, name=None):
    """Mesh with all modifiers applied (copy)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    me.name = name or ob.name + "_eval"
    return me


def apply_all(ob):
    me = evaluated_mesh(ob)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    bpy.data.meshes.remove(old)
    return ob


def shade_smooth(me):
    for p in me.polygons:
        p.use_smooth = True


def remove(ob):
    me = ob.data
    bpy.data.objects.remove(ob)
    if me and me.users == 0 and isinstance(me, bpy.types.Mesh):
        bpy.data.meshes.remove(me)


def tri_count(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def auto_smooth(bm, angle_deg=35.0):
    """Smooth-shade every face, mark edges sharper than angle_deg (and boundaries) as sharp."""
    a = math.radians(angle_deg)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if len(e.link_faces) == 2:
            e.smooth = e.calc_face_angle(0.0) < a
        else:
            e.smooth = True


def bm_to_mesh(bm, name="tmp"):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    return me


class Parts:
    """Collects geometry per material part (bmesh per part, merged on add)."""

    def __init__(self):
        self.bm = {}

    def add(self, part, src, matrix=None, smooth=None, free=True):
        """src: bmesh or Mesh. smooth: None keeps the shading flags, a number = auto-smooth angle.
        A bmesh src is freed unless free=False."""
        is_bm = isinstance(src, bmesh.types.BMesh)
        if is_bm:
            b = src.copy() if (matrix is not None or not free) else src
        else:
            b = bmesh.new()
            b.from_mesh(src)
        if matrix is not None:
            bmesh.ops.transform(b, matrix=matrix, verts=b.verts)
        if smooth is not None:
            auto_smooth(b, smooth)
        me = bm_to_mesh(b)
        if part not in self.bm:
            self.bm[part] = bmesh.new()
        self.bm[part].from_mesh(me)
        bpy.data.meshes.remove(me)
        if b is not src:
            b.free()
        if is_bm and free and b is not src:
            src.free()
        elif is_bm and free:
            src.free()

    def mesh(self, part):
        return bm_to_mesh(self.bm[part], "sti_" + part)


# --- small modelling helpers ------------------------------------------------------------------------
def subsurf_bm(bm, levels=2, crease_edges=None, crease=1.0):
    """Catmull-Clark subdivide a bmesh cage (returns a new bmesh; the input is freed)."""
    if crease_edges:
        cl = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")
        for e in crease_edges:
            e[cl] = crease
    me = bm_to_mesh(bm)
    bm.free()
    ob = bpy.data.objects.new("ss_tmp", me)
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("ss", "SUBSURF")
    m.levels = m.render_levels = levels
    out = evaluated_mesh(ob)
    remove(ob)
    b = bmesh.new()
    b.from_mesh(out)
    bpy.data.meshes.remove(out)
    return b


def lathe(profile, segments=64, closed_profile=False, a0=0.0, a1=2 * math.pi):
    """Surface of revolution about the Y axis. profile: [(r, y)] ordered; returns bmesh.
    Face winding: outward for a profile running from +y toward -y along the outside."""
    bm = bmesh.new()
    full = abs(a1 - a0 - 2 * math.pi) < 1e-6
    n = segments if full else segments + 1
    rings = []
    for k in range(n):
        a = a0 + (a1 - a0) * k / segments
        ca, sa = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((r * ca, y, r * sa)) for r, y in profile])
    m = len(profile)
    for k in range(segments):
        r0, r1 = rings[k], rings[(k + 1) % n]
        for j in range(m - 1 if not closed_profile else m):
            jn = (j + 1) % m
            if r0[j].co == r0[jn].co and r1[j].co == r1[jn].co:
                continue
            try:
                bm.faces.new((r0[j], r1[j], r1[jn], r0[jn]))
            except ValueError:
                pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    return bm


def grid_surface(P, closed_u=False, closed_v=False):
    """P: nested list [i][j] of Vector-like points -> quad bmesh."""
    bm = bmesh.new()
    ni, nj = len(P), len(P[0])
    V = [[bm.verts.new(P[i][j]) for j in range(nj)] for i in range(ni)]
    for i in range(ni if closed_u else ni - 1):
        for j in range(nj if closed_v else nj - 1):
            a, b = V[i][j], V[(i + 1) % ni][j]
            c, d = V[(i + 1) % ni][(j + 1) % nj], V[i][(j + 1) % nj]
            try:
                bm.faces.new((a, b, c, d))
            except ValueError:
                pass
    return bm


def box_bm(size, center=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=center, verts=bm.verts)
    return bm


def rounded_box(size, center=(0, 0, 0), levels=2, edge=0.12):
    """Box with support loops at `edge` (fraction of each side) so Catmull-Clark rounds only the edges."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=True)
    for v in bm.verts:
        co = v.co.copy()
        for k in range(3):
            if 1e-6 < abs(co[k]) < 0.49:
                co[k] = math.copysign(0.5 - edge, co[k])
        v.co = co
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    b = subsurf_bm(bm, levels)
    bmesh.ops.translate(b, vec=center, verts=b.verts)
    return b


def transformed(bm, M):
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
    return bm


def merge(dst, src, free=True):
    me = bm_to_mesh(src)
    dst.from_mesh(me)
    bpy.data.meshes.remove(me)
    if free:
        src.free()
    return dst


def mirror_y(bm):
    out = bm.copy()
    bmesh.ops.scale(out, vec=(1, -1, 1), verts=out.verts)
    bmesh.ops.reverse_faces(out, faces=out.faces)
    return out


def text_bm(text, height, depth, font="/System/Library/Fonts/Supplemental/Arial Black.ttf", shear=0.0, spacing=1.0):
    """Extruded text as a bmesh: centred at the origin, reading along +x, cap height `height` along +y,
    extruded from z=0 to z=depth (+z faces the viewer)."""
    cu = bpy.data.curves.new("txt", "FONT")
    cu.body = text
    try:
        cu.font = bpy.data.fonts.load(font, check_existing=True)
    except Exception:
        pass
    cu.size = 1.0
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.shear = shear
    cu.space_character = spacing
    cu.extrude = 0.5
    cu.resolution_u = 4
    ob = bpy.data.objects.new("txt", cu)
    bpy.context.scene.collection.objects.link(ob)
    me = evaluated_mesh(ob)
    remove(ob)
    bpy.data.curves.remove(cu)
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    ys = [v.co.y for v in bm.verts]
    k = height / max(1e-6, (max(ys) - min(ys)))
    for v in bm.verts:
        v.co = (v.co.x * k, v.co.y * k, (v.co.z + 0.5) * depth)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm
