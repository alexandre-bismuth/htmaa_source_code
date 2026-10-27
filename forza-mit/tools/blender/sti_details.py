"""Body details: lamps, grille + intake honeycomb, fog lamps, lip, hood scoop, cowl, wipers, mirrors, door handles,
side markers, wing, exhaust, underbody mechanicals. Left-side pieces are mirrored to the right.
(The floor pan, bumper undersides and wheel wells are part of the body shell: sti_body zones 4 and 5.)

Everything is placed on the body by ray casts against the uncut skin (bvh), so it follows the body shape.
"""
import math

import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import sti_body
from sti_common import (G, XA_F, XA_R, box_bm, grid_surface, lathe, merge, mirror_y, rounded_box,
                        subsurf_bm, text_bm, transformed)

BVH = None


def hit(o, d):
    loc, n, i, dist = BVH.ray_cast(Vector(o), Vector(d).normalized())
    return (loc, n) if loc is not None else (None, None)


def side_pt(x, h, side=1):
    return hit((x, side * 3, h + G), (0, -side, 0))


def top_pt(x, y):
    return hit((x, y, 3), (0, 0, -1))


def front_pt(y, h):
    return hit((4, y, h + G), (-1, 0, 0))


def rear_pt(y, h):
    return hit((-4, y, h + G), (1, 0, 0))


def frame(z_axis, up=Vector((0, 0, 1))):
    """Rotation matrix whose local +Y is z_axis (lathe axis) - used to orient lathed parts."""
    y = Vector(z_axis).normalized()
    x = up.cross(y)
    if x.length < 1e-6:
        x = Vector((1, 0, 0))
    x.normalize()
    z = x.cross(y)
    return Matrix((x, y, z)).transposed().to_4x4()


def both(parts, part, bm, smooth=40):
    parts.add(part, mirror_y(bm), smooth=smooth)
    parts.add(part, bm, smooth=smooth)


def dome(bm, amount):
    """Bulge a lamp-lens patch: displacement along the normal, 0 at the cut boundary, max in the middle."""
    from mathutils.kdtree import KDTree
    bm.normal_update()
    edge = [v for v in bm.verts if v.is_boundary]
    kd = KDTree(len(edge))
    for k, v in enumerate(edge):
        kd.insert(v.co, k)
    kd.balance()
    dist = {v: kd.find(v.co)[2] for v in bm.verts}
    dmax = max(dist.values()) or 1.0
    nrm = {v: v.normal.copy() for v in bm.verts}
    for v in bm.verts:
        t = min(1.0, dist[v] / dmax)
        v.co += nrm[v] * amount * math.sin(0.5 * math.pi * t) ** 0.8
    return bm


def offset(bm, d):
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * d
    return bm


# --- lamps ---------------------------------------------------------------------------------------------
def reflector(r_out, depth, f_inner=0.25, seg=24, rings=6):
    """Faceted parabolic multi-reflector bowl, opening toward +Y, rim at y=0 (add with smooth=4 for facets)."""
    prof = []
    for k in range(rings + 1):
        r = r_out * (f_inner + (1 - f_inner) * k / rings)
        prof.append((r, -depth * (r / r_out) ** 2))
    prof = prof[::-1]
    prof.append((r_out + 0.004, 0.0))
    return lathe(prof[::-1], seg)


def projector(r, seg=40):
    """Projector lens dome (opening toward +Y) with a short barrel."""
    prof = [(0.0001, r * 0.55)] + [(r * math.sin(a), r * 0.55 * math.cos(a)) for a in
                                   [math.radians(t) for t in range(10, 91, 10)]] + [(r, -r * 0.6)]
    return lathe(prof, seg)


def ring(r_in, r_out, y=0.0, depth=0.004, seg=48):
    return lathe([(r_out, y - depth), (r_out, y), (r_in, y), (r_in, y - depth)], seg)


def lamp_anchor(patch_bvh, toward, axis):
    """Point on the lens patch hit by a ray from outside along -axis toward the target point."""
    o = Vector(toward) + Vector(axis) * 0.3
    loc, n, i, d = patch_bvh.ray_cast(o, -Vector(axis))
    return loc if loc is not None else Vector(toward)


def facet(bm, amp, seed=0.0):
    """Optic-facet look for reflectors: every vertex moves along its normal by a pseudo-random +-amp, so with
    flat shading (add with smooth=4) neighbouring faces tilt a few degrees and sparkle like lamp optics."""
    bm.normal_update()
    nrm = {v: v.normal.copy() for v in bm.verts}
    for v in bm.verts:
        h = math.sin(v.co.x * 1371.3 + v.co.y * 2113.7 + v.co.z * 1733.1 + seed) * 43758.5453
        v.co += nrm[v] * amp * (2.0 * (h - math.floor(h)) - 1.0)
    return bm


def shroud(r0, r1, depth, seg=48):
    """Projector shroud: a short chrome cone around the projector lens, flaring toward the viewer (+Y)."""
    return lathe([(r1 + 0.002, depth - 0.002), (r1, depth), (r0, 0.0), (r0, -0.004)], seg)


def headlamps(parts, patches):
    """Bugeye headlamp: clear domed cover; inside, a chrome housing, the big multi-reflector bowl with the HID
    projector (dark lens in a chrome shroud) and, in the teardrop tail, the small high-beam / indicator
    reflector with an amber bulb."""
    s1, s2 = [Vector(c) for c, r in sti_body.HEADLAMP_SPHERES]
    d0 = Vector((-0.75, -0.65, 0.0)).normalized()
    for side, patch in zip((1, -1), patches):
        d_in = Vector((d0.x, side * d0.y, 0.0))
        pb = patch.copy()
        pb.normal_update()
        bvh = BVHTree.FromBMesh(pb)
        # clear cover (slightly proud of the body) and the chrome housing back wall (faceted)
        parts.add("lens", dome(offset(patch.copy(), 0.0015), 0.020), smooth=70)
        back = patch.copy()
        bmesh.ops.translate(back, vec=d_in * 0.050, verts=back.verts)
        parts.add("chrome", facet(back, 0.0007, 1.0), smooth=4)
        # main lamp: big chrome multi-reflector with a projector, small lamp in the teardrop tail
        axis = Vector((0.93, 0.33 * side, 0.12)).normalized()
        c1 = Vector((s1.x, side * s1.y, s1.z))
        c2 = Vector((s2.x, side * s2.y, s2.z))
        a1 = lamp_anchor(bvh, c1 + Vector((0, 0, 0.004)), axis) - axis * 0.012
        M1 = Matrix.Translation(a1) @ frame(axis)
        parts.add("chrome", transformed(reflector(0.074, 0.032), M1), smooth=4)
        parts.add("chrome", transformed(ring(0.074, 0.082, 0.002), M1), smooth=30)
        parts.add("chrome", transformed(shroud(0.0335, 0.050, 0.020), M1), smooth=30)
        parts.add("black", transformed(ring(0.0305, 0.0345, 0.003, 0.008), M1), smooth=30)
        parts.add("glass", transformed(projector(0.031), Matrix.Translation(a1 - axis * 0.004) @ frame(axis)), smooth=60)
        parts.add("chrome", transformed(ring(0.006, 0.030, -0.018, 0.002), M1), smooth=30)
        tail = c1.lerp(c2, 0.58)
        a2 = lamp_anchor(bvh, tail - Vector((0, 0, 0.012)), axis) - axis * 0.010
        M2 = Matrix.Translation(a2) @ frame(axis)
        parts.add("chrome", transformed(reflector(0.032, 0.018, 0.2, 16, 4), M2), smooth=4)
        parts.add("chrome", transformed(ring(0.032, 0.037, 0.002), M2), smooth=30)
        parts.add("amber", transformed(projector(0.0065, 16), M2 @ Matrix.Translation((0, -0.007, 0))), smooth=60)
        parts.add("lens", transformed(projector(0.010, 24), M2), smooth=60)
        pb.free()
        patch.free()


def fin(pts, d_in, depth, half=0.0007):
    """Thin double-sided divider wall from a polyline on the lamp face, `depth` deep along d_in."""
    bm = bmesh.new()
    for s in (1, -1):
        rows = [[p + Vector((0, s * half, 0)) - d_in * 0.001, p + Vector((0, s * half, 0)) + d_in * depth]
                for p in pts]
        b = grid_surface(rows)
        b.normal_update()
        if sum(f.normal.y for f in b.faces) * s < 0:
            bmesh.ops.reverse_faces(b, faces=b.faces)
        merge(bm, b)
    return bm


TL_SPLIT = 0.585          # |y| of the divider between the red tail / stop section and the clear reverse section
TL_ROUND = 0.040          # radius of the round tail / stop element


def taillamps(parts, patches):
    """Tail lamp with real depth, built like the real thing: a red-tinted translucent domed cover ('red') over
    chrome faceted optics 26 mm in, so the lamp reads red from the tint itself in any light (not from emissive);
    the round tail / stop element (chrome bezel, faceted bowl, chrome ring + bulb); the reverse section under a
    clear cover with its own reflector and bulb; a black divider; the chrome housing 3 cm in."""
    d0 = Vector((0.8, -0.6, 0.0)).normalized()
    for side, patch in zip((1, -1), patches):
        d_in = Vector((d0.x, side * d0.y, 0.0))
        patch.normal_update()
        bvh = BVHTree.FromBMesh(patch)
        # the round element sits in the middle of the red section, facing out of it
        red_f = [f for f in patch.faces if abs(f.calc_center_median().y) > TL_SPLIT + 0.03]
        area = sum(f.calc_area() for f in red_f)
        c = sum((f.calc_center_median() * f.calc_area() for f in red_f), Vector()) / area
        axis = sum((f.normal * f.calc_area() for f in red_f), Vector()).normalized()
        a = lamp_anchor(bvh, c, axis)
        # chrome housing back wall
        back = patch.copy()
        bmesh.ops.translate(back, vec=d_in * 0.03, verts=back.verts)
        parts.add("chrome", facet(back, 0.0008, 2.0), smooth=4)
        # inner optics, split at the divider
        inner = patch.copy()
        bmesh.ops.bisect_plane(inner, geom=inner.verts[:] + inner.edges[:] + inner.faces[:],
                               plane_co=(0, side * TL_SPLIT, 0), plane_no=(0, 1, 0))
        cut = sorted((v.co.copy() for v in inner.verts if abs(abs(v.co.y) - TL_SPLIT) < 1e-5), key=lambda p: p.z)
        red = inner.copy()
        rev_faces = [f for f in inner.faces if abs(f.calc_center_median().y) < TL_SPLIT]
        rev_c = sum((f.calc_center_median() for f in rev_faces), Vector()) / max(1, len(rev_faces))
        rev_n = sum((f.normal * f.calc_area() for f in rev_faces), Vector()).normalized()
        inner.free()

        # the red optic sits deep (26 mm, just in front of the housing wall) so the round element's bowl stands
        # fully in front of it - no hole to cut
        bmesh.ops.delete(red, geom=[f for f in red.faces if abs(f.calc_center_median().y) < TL_SPLIT], context="FACES")
        bmesh.ops.translate(red, vec=d_in * 0.026, verts=red.verts)
        parts.add("chrome", facet(red, 0.0009, 3.0), smooth=4)         # optic: chrome seen through red
        if len(cut) > 1:
            parts.add("black", fin(cut, d_in, 0.029), smooth=40)
        # domed cover: red-tinted translucent over the tail / stop section, clear over the reverse lamp
        cover = dome(offset(patch, 0.0015), 0.007)
        bmesh.ops.bisect_plane(cover, geom=cover.verts[:] + cover.edges[:] + cover.faces[:],
                               plane_co=(0, side * TL_SPLIT, 0), plane_no=(0, 1, 0))
        clear = cover.copy()
        bmesh.ops.delete(cover, geom=[f for f in cover.faces if abs(f.calc_center_median().y) < TL_SPLIT],
                         context="FACES")
        bmesh.ops.delete(clear, geom=[f for f in clear.faces if abs(f.calc_center_median().y) >= TL_SPLIT],
                         context="FACES")
        parts.add("red", cover, smooth=70)
        parts.add("lens", clear, smooth=70)
        # round tail / stop element
        R = TL_ROUND
        M = Matrix.Translation(a - axis * 0.004) @ frame(axis)
        # chrome bezel whose skirt reaches back to the red optic (hides the hole cut in it)
        parts.add("chrome", transformed(ring(R - 0.001, R + 0.011, 0.0, 0.013), M), smooth=30)
        Mb = Matrix.Translation(a - axis * 0.006) @ frame(axis)
        parts.add("chrome", transformed(reflector(R, 0.020, 0.2, 24, 6), Mb), smooth=4)
        parts.add("chrome", transformed(ring(0.011, 0.016, -0.012, 0.003), Mb), smooth=30)
        parts.add("lens", transformed(projector(0.008, 16), Mb @ Matrix.Translation((0, -0.014, 0))), smooth=60)
        # reverse lamp: small chrome reflector + bulb in the clear section
        if rev_faces:
            Mr = Matrix.Translation(rev_c + rev_n * 0.0 + d_in * 0.010) @ frame(rev_n)
            parts.add("chrome", transformed(reflector(0.024, 0.012, 0.2, 20, 4), Mr), smooth=4)
            parts.add("lens", transformed(projector(0.007, 16), Mr @ Matrix.Translation((0, -0.006, 0))), smooth=60)
            # JDM: amber rear indicator bulb in the clear section, below the reverse bulb
            Ma = Matrix.Translation(rev_c + d_in * 0.012 + Vector((0, 0, -0.022))) @ frame(rev_n)
            parts.add("amber", transformed(projector(0.0065, 16), Ma), smooth=60)
        patch.free()


# --- honeycomb mesh -------------------------------------------------------------------------------------
def honeycomb(outline, cell=0.024, wall=0.0032, depth=0.014, recess=0.03, grow=0.02):
    """Hex mesh in the (y, h) plane following the body surface (front), recessed behind the opening."""
    ys = [p[0] for p in outline]
    hs = [p[1] for p in outline]
    y0, y1, h0, h1 = min(ys) - grow, max(ys) + grow, min(hs) - grow, max(hs) + grow
    R = cell / math.sqrt(3)            # hex circumradius (flat-to-flat = cell)
    dy, dh = cell, 1.5 * R
    bm = bmesh.new()
    row = 0
    h = h0
    while h <= h1:
        y = y0 + (cell / 2 if row % 2 else 0.0)
        while y <= y1:
            loc, n = front_pt(y, h)
            if loc is not None:
                base = loc - Vector((recess, 0, 0))
                outer = [base + Vector((0, R * math.cos(math.radians(30 + 60 * k)),
                                        R * math.sin(math.radians(30 + 60 * k)))) for k in range(6)]
                ri = R - wall
                inner = [base + Vector((0, ri * math.cos(math.radians(30 + 60 * k)),
                                        ri * math.sin(math.radians(30 + 60 * k)))) for k in range(6)]
                ib = [p - Vector((depth, 0, 0)) for p in inner]
                vo = [bm.verts.new(p) for p in outer]
                vi = [bm.verts.new(p) for p in inner]
                vb = [bm.verts.new(p) for p in ib]
                for k in range(6):
                    kn = (k + 1) % 6
                    bm.faces.new((vo[k], vi[k], vi[kn], vo[kn]))
                    bm.faces.new((vi[k], vb[k], vb[kn], vi[kn]))
            y += dy
        h += dh
        row += 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # face the viewer (+x)
    for f in bm.faces:
        if f.normal.x < -0.5:
            f.normal_flip()
    return bm


def subaru_badge(parts):
    """Oval chrome badge with the six stars on a dark field, centred in the grille."""
    loc, n = front_pt(0.0, 0.648)
    c = loc + Vector((0.012, 0, 0))
    M = Matrix.Translation(c) @ frame(Vector((1, 0, 0))) @ Matrix.Diagonal((1.0, 1.0, 0.62, 1.0))
    parts.add("chrome", transformed(ring(0.046, 0.056, 0.004, 0.010), M), smooth=30)
    disc = lathe([(0.0001, 0.0), (0.047, 0.0), (0.047, -0.008)], 48)
    parts.add("mesh", transformed(disc, M), smooth=30)
    stars = bmesh.new()
    for (sy, sz, r) in ((-0.022, 0.006, 0.013), (0.004, 0.016, 0.006), (0.016, 0.009, 0.006), (0.006, -0.002, 0.006),
                        (0.024, -0.004, 0.006), (0.012, -0.014, 0.006)):
        pts = []
        for k in range(8):
            rr = r if k % 2 == 0 else r * 0.3
            a = math.pi / 4 * k
            pts.append(Vector((0.0015, sy + rr * math.cos(a), sz / 0.62 * 0.62 + rr * math.sin(a))))
        vs = [stars.verts.new(p) for p in pts]
        stars.faces.new(vs)
    bmesh.ops.transform(stars, matrix=Matrix.Translation(c), verts=stars.verts)
    parts.add("chrome", stars)


def backing(outline, recess, grow=0.03):
    """Dark plate behind an opening (follows the surface), so the mesh never shows daylight."""
    ys = [p[0] for p in outline]
    hs = [p[1] for p in outline]
    y0, y1, h0, h1 = min(ys) - grow, max(ys) + grow, min(hs) - grow, max(hs) + grow
    rows = []
    for i in range(13):
        y = y0 + (y1 - y0) * i / 12
        row = []
        for j in range(5):
            h = h0 + (h1 - h0) * j / 4
            loc, n = front_pt(y, h)
            x = (loc.x if loc is not None else 2.1) - recess
            row.append(Vector((x, y, h + G)))
        rows.append(row)
    bm = grid_surface(rows)
    bm.normal_update()
    if sum(f.normal.x for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return bm


def front_end(parts):
    parts.add("mesh", honeycomb(sti_body.GRILLE, recess=0.028), smooth=20)
    parts.add("mesh", honeycomb(sti_body.INTAKE, cell=0.03, recess=0.04), smooth=20)
    parts.add("black", backing(sti_body.GRILLE, 0.065), smooth=60)
    parts.add("black", backing(sti_body.INTAKE, 0.080), smooth=60)
    subaru_badge(parts)
    # fog lamps in their pockets
    fy, fh, fr = sti_body.FOG
    for side in (1, -1):
        loc, n = front_pt(side * fy, fh)
        axis = Vector((1, 0.12 * side, -0.02)).normalized()
        M = Matrix.Translation(loc - Vector((0.024, 0, 0))) @ frame(axis)
        parts.add("chrome", transformed(reflector(fr - 0.008, 0.03, 0.25, 20, 5), M), smooth=4)
        parts.add("black", transformed(ring(fr - 0.008, fr + 0.004, 0.003, 0.02), M), smooth=30)
        lens = lathe([(0.0001, 0.006), (0.02, 0.0055), (0.045, 0.003), (fr - 0.008, 0.0)], 48)
        parts.add("lens", transformed(lens, M), smooth=60)
        parts.add("chrome", transformed(projector(0.012, 24), M @ Matrix.Translation((0, -0.012, 0))), smooth=60)
    # front lip spoiler: a black blade around the bottom of the bumper
    pts = []
    for k in range(41):
        a = math.radians(-64 + 128 * k / 40)
        o = Vector((1.70, 0, 0.262 + G))
        d = Vector((math.cos(a), math.sin(a), 0))
        loc, n = hit(o + d * 1.5, -d)
        if loc is not None:
            pts.append((loc, d))
    sec = []
    for loc, d in pts:
        base = Vector((loc.x, loc.y, 0.236 + G))
        out = d * 0.032
        sec.append([base - d * 0.03 + Vector((0, 0, 0.014)), base + out * 0.7 + Vector((0, 0, 0.010)),
                    base + out + Vector((0, 0, 0.004)), base + out + Vector((0, 0, -0.006)),
                    base + out * 0.6 + Vector((0, 0, -0.010)), base - d * 0.03 + Vector((0, 0, -0.010))])
    parts.add("black", grid_surface(sec), smooth=40)


# --- hood scoop -------------------------------------------------------------------------------------------
def face_toward(bm, c):
    """Orient every face of bm so its normal points toward the point c (inside of a cavity)."""
    bm.normal_update()
    flip = [f for f in bm.faces if f.normal.dot(Vector(c) - f.calc_center_median()) < 0]
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)
    return bm


def hood_scoop(parts):
    xs = [1.10 + (1.565 - 1.10) * (k / 30) ** 0.8 for k in range(31)]
    nj = 33
    secs = []
    for x in xs:
        t = (x - 1.10) / (1.565 - 1.10)
        H = 0.074 * (1 - (1 - t) ** 2.2) ** 0.9
        w = 0.285 + 0.050 * t
        row = []
        for j in range(nj):
            s = -1 + 2 * j / (nj - 1)
            y = s * (w + 0.06)
            loc, n = top_pt(x, y)
            prof = H * max(0.0, 1 - abs(y / w) ** 5) ** 0.45 if abs(y) < w else 0.0
            # built into the hood: the shell rises out of the hood skin (its outer band dives below it), so
            # there is no step / gap line at the base, just the fillet where the two surfaces meet
            bury = 0.0012 + 0.006 * max(0.0, min(1.0, (abs(y) - w) / 0.05)) + 0.004 * max(0.0, 1 - t / 0.05)
            row.append(loc + Vector((0, 0, prof - bury)))
        secs.append(row)
    shell = grid_surface(secs)
    shell = subsurf_bm(shell, 1)
    pl = shell.faces.layers.int.new("proj")
    for f in shell.faces:
        f[pl] = 2                  # own UV island (sti_uv 'scoop'): livery + baked AO like the hood
    parts.add("paint", shell, smooth=60)
    # mouth: rolled lip, black throat and back wall
    x = xs[-1]
    t, H, w = 1.0, 0.074, 0.335
    lip, throat = [], []
    for j in range(nj):
        s = -1 + 2 * j / (nj - 1)
        y = s * w
        loc, n = top_pt(x, y)
        prof = H * max(0.0, 1 - abs(s) ** 5) ** 0.45
        lip.append(loc + Vector((0, 0, prof)))
    inner = [p.lerp(Vector((x, 0, (lip[0].z + lip[-1].z) / 2 + 0.002)), 0.10) for p in lip]
    body = [p + Vector((-0.010, 0, -0.004 if p.z > lip[0].z + 0.01 else 0.003)) for p in inner]
    deep = [p + Vector((-0.12, 0, -0.012)) for p in body]
    parts.add("paint", grid_surface([lip, [p + Vector((-0.004, 0, 0)) for p in inner]]), smooth=60)
    # the mouth is a closed dark cavity (one-sided faces all facing into it): throat roof, a floor over the
    # hood, and the intercooler face at the back - otherwise the hood under the shell shows through the mouth
    cz = (lip[0].z + lip[-1].z) / 2
    cav = Vector((x - 0.06, 0.0, cz + 0.015))
    roof = grid_surface([[p + Vector((-0.004, 0, 0)) for p in inner], body, deep])
    face_toward(roof, cav)
    parts.add("black", roof, smooth=60)
    rows = []
    for k in range(25):
        y = -0.315 + 0.63 * k / 24
        rows.append([top_pt(x - 0.002, y)[0] + Vector((0, 0, 0.0012)), top_pt(x - 0.136, y)[0] + Vector((0, 0, 0.0012))])
    floor = grid_surface(rows)
    face_toward(floor, cav)
    parts.add("black", floor, smooth=40)
    bm = bmesh.new()
    bm.faces.new([bm.verts.new(p) for p in deep])
    face_toward(bm, cav)
    parts.add("mesh", bm)


def cowl_and_wipers(parts):
    # black cowl panel between the hood's rear edge and the windshield base
    rows = []
    for k in range(25):
        y = -0.66 + 1.32 * k / 24
        xb = 0.952 - 0.072 * (y / 0.672) ** 2
        row = []
        for t in (0.0, 0.03, 0.065):
            loc, n = top_pt(xb + 0.006 + t, y)
            row.append(loc + n * 0.003)
        rows.append(row)
    parts.add("black", grid_surface(rows), smooth=40)
    # wipers: arm + blade resting on the glass (right-hand-drive car: both park pointing to the left)
    for (x0, y0, x1, y1) in ((0.93, -0.50, 0.90, 0.12), (0.935, 0.04, 0.905, 0.58)):
        for k, (w, lift) in enumerate(((0.010, 0.010), (0.016, 0.020))):
            pts = []
            for i in range(12):
                t = i / 11
                x, y = x0 + (x1 - x0) * t - 0.012 * k, y0 + (y1 - y0) * t
                loc, n = top_pt(x, y)
                pts.append((loc + n * lift, n))
            sec = []
            for i, (p, n) in enumerate(pts):
                tdir = (pts[min(i + 1, 11)][0] - pts[max(i - 1, 0)][0]).normalized()
                b = tdir.cross(n).normalized()
                sec.append([p - b * w / 2 - n * 0.003, p - b * w / 2 + n * 0.004, p + b * w / 2 + n * 0.004,
                            p + b * w / 2 - n * 0.003])
            parts.add("black", grid_surface(sec, closed_v=True), smooth=40)


# --- mirrors, handles, markers ---------------------------------------------------------------------------
def mirror_pod(n=28, k=10):
    """Mirror housing lofted along its span (local +y = outboard): superellipse sections (crisp but rounded),
    a flat back for the glass at x = -0.026, a fuller front, slightly taller at the outer end, ends rounded off."""
    rows = []
    vs = [math.sin(0.5 * math.pi * i / k) for i in range(-k, k + 1)]
    for v in vs:
        sc = (1.0 - min(abs(v), 0.9995) ** 4) ** 0.25
        y = 0.0875 * v
        a = (0.054 - 0.010 * v) * sc
        b = (0.044 + 0.005 * v) * sc
        row = []
        for j in range(n):
            th = 2 * math.pi * j / n
            c, s_ = math.cos(th), math.sin(th)
            x = a * math.copysign(abs(c) ** (2 / 2.6), c)
            z = b * math.copysign(abs(s_) ** (2 / 2.6), s_)
            row.append(Vector((max(x, -0.026 * sc), y, z + 0.002 * v)))
        rows.append(row)
    bm = grid_surface(rows, closed_v=True)
    for r in (rows[0], rows[-1]):
        bm.faces.new([bm.verts.new(p) for p in r])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def mirrors(parts):
    pod = mirror_pod()
    M = Matrix.Translation((0.668, 0.955, 1.052 + G)) @ Matrix.Rotation(math.radians(-7), 4, "Z")
    both(parts, "paint", transformed(pod, M), smooth=60)
    glass = rounded_box((0.004, 0.150, 0.080), (-0.0285, 0.002, 0.001), 2, 0.3)
    both(parts, "chrome", transformed(glass, M), smooth=60)
    rim = rounded_box((0.006, 0.160, 0.090), (-0.026, 0.002, 0.001), 2, 0.3)
    both(parts, "black", transformed(rim, M), smooth=60)
    # sail (triangle base on the door) + arm
    sail = rounded_box((0.13, 0.026, 0.062), (0.0, 0.0, 0.0), 2, 0.3)
    for v in sail.verts:
        if v.co.x < 0:
            v.co.z *= 0.45 + 0.55 * (1 + v.co.x / 0.065)
    both(parts, "black", transformed(sail, Matrix.Translation((0.765, 0.790, 1.005 + G))
                                     @ Matrix.Rotation(math.radians(-5), 4, "Z")), smooth=50)
    arm = rounded_box((0.055, 0.115, 0.030), (0, 0, 0), 2, 0.35)
    both(parts, "black", transformed(arm, Matrix.Translation((0.70, 0.858, 1.032 + G))
                                     @ Matrix.Rotation(math.radians(-10), 4, "Z")), smooth=50)


def handles(parts):
    """Pull handles sitting in the (boolean-cut) recess dishes."""
    for hx, hh in ((-0.005, 0.885), (-0.900, 0.900)):
        loc, n = side_pt(hx, hh)
        h = rounded_box((0.118, 0.016, 0.022), (0, 0, 0), 2, 0.45)
        z = Vector((0, 0, 1))
        y = n.normalized()
        x = y.cross(z).normalized() * -1
        R = Matrix((x, y, x.cross(y) * -1)).transposed().to_4x4()
        both(parts, "paint", transformed(h, Matrix.Translation(loc + n * 0.001) @ R), smooth=60)


def markers(parts):
    loc, n = side_pt(1.985, 0.662)
    if loc is not None:
        m = rounded_box((0.065, 0.010, 0.022), (0, 0, 0), 2, 0.35)
        R = frame(n) @ Matrix.Rotation(math.radians(90), 4, "Y")
        both(parts, "amber", transformed(m, Matrix.Translation(loc) @ frame(n) @ Matrix.Rotation(math.pi / 2, 4, "Y")),
             smooth=60)


# --- rear --------------------------------------------------------------------------------------------------
def airfoil(chord, thick=0.12, camber=0.04, n=24):
    """NACA-4-like section in (x, z), leading edge at 0, chord along -x (car rear). Closed loop."""
    up, lo = [], []
    for k in range(n + 1):
        b = (1 - math.cos(math.pi * k / n)) / 2
        yt = 5 * thick * (0.2969 * math.sqrt(b) - 0.126 * b - 0.3516 * b ** 2 + 0.2843 * b ** 3 - 0.1036 * b ** 4)
        p, m = 0.4, camber
        yc = m / p ** 2 * (2 * p * b - b * b) if b < p else m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * b - b * b)
        up.append((-b * chord, (yc + yt) * chord))
        lo.append((-b * chord, (yc - yt) * chord))
    return up + lo[::-1][1:-1]


def wing(parts):
    """GDB STi rear wing: thick cambered main plane carried by two blade uprights at its tips; the blades
    rise a little above the plane as end plates; small gurney flap on the trailing edge."""
    chord, span, yb = 0.240, 0.612, 0.604
    H_LE = 1.212
    aoa = math.radians(-10.0)     # trailing edge up (downforce)
    secs = []
    ys = [-span + 2 * span * k / 48 for k in range(49)]
    for y in ys:
        t = abs(y) / span
        c = chord * (1 - 0.06 * t ** 4)
        sec = airfoil(c, 0.12, 0.06, 28)
        xle = -1.795 - 0.018 * t ** 2
        zle = H_LE + 0.008 * t ** 2 + G
        row = []
        for a, b in sec:
            x = a * math.cos(aoa) - b * math.sin(aoa)
            z = a * math.sin(aoa) + b * math.cos(aoa)
            row.append(Vector((xle + x, y, zle - z)))
        secs.append(row)
    plane = grid_surface(secs, closed_v=True)
    for row in (secs[0], secs[-1]):
        plane.faces.new([plane.verts.new(p) for p in row])
    bmesh.ops.remove_doubles(plane, verts=plane.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(plane, faces=plane.faces)
    parts.add("paint", plane, smooth=50)
    # gurney flap along the trailing edge
    te_x = -1.795 - chord * math.cos(aoa)
    te_z = H_LE + G - chord * math.sin(aoa)
    gur = rounded_box((0.006, 2 * span - 0.03, 0.020), (te_x + 0.004, 0.0, te_z + 0.008), 2, 0.3)
    parts.add("paint", gur, smooth=50)
    # blade uprights (also the end plates)
    for side in (1, -1):
        yy = side * yb
        rows = []
        for k in range(15):
            t = k / 14
            loc, n = top_pt(-1.94, yy)
            z0 = (loc.z if loc is not None else 1.05 + G) - 0.006
            z_top = H_LE + 0.040 + G
            z = z0 + (z_top - z0) * t
            xle = -1.850 + 0.058 * t ** 0.7 - 0.085 * t ** 7
            xte = -2.085 + 0.022 * t + 0.035 * t ** 7
            c = xle - xte
            sec = airfoil(c, 0.022 / c, 0.0, 14)
            rows.append([Vector((xle + a, yy + b, z)) for a, b in sec])
        # close the top with a rounded cap row
        top = rows[-1]
        cx = sum(p.x for p in top) / len(top)
        rows.append([Vector((cx + (p.x - cx) * 0.96, yy + (p.y - yy) * 0.3, p.z + 0.004)) for p in top])
        fin = grid_surface(rows, closed_v=True)
        cap = rows[-1]
        fin.faces.new([fin.verts.new(p) for p in cap])
        bmesh.ops.remove_doubles(fin, verts=fin.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(fin, faces=fin.faces)
        parts.add("paint", fin, smooth=50)
        loc, n = top_pt(-1.96, yy)
        if loc is not None:
            foot = rounded_box((0.255, 0.040, 0.010), (0, 0, 0), 2, 0.35)
            parts.add("black", transformed(foot, Matrix.Translation(loc + Vector((0.0, 0, 0.002)))), smooth=50)
            # stand base: two chrome bolt heads on the gasket
            for bx in (-1.885, -2.035):
                b = lathe([(0.0001, 0.0035), (0.0050, 0.0030), (0.0058, 0.0)], 6)
                parts.add("chrome", transformed(b, Matrix.Translation(Vector((bx, yy, loc.z + 0.007)))
                                                @ frame(Vector((0, 0, 1)))), smooth=20)
        # end-plate bolts: the main plane is bolted through each upright (two hex heads on the outer face)
        tz = 0.85
        xle = -1.850 + 0.058 * tz ** 0.7 - 0.085 * tz ** 7
        xte = -2.085 + 0.022 * tz + 0.035 * tz ** 7
        for bx, bz in ((-1.898, 0.010), (-1.965, 0.022)):
            b_ = (xle - bx) / (xle - xte)
            half = 5 * 0.022 * (0.2969 * math.sqrt(b_) - 0.126 * b_ - 0.3516 * b_ ** 2 + 0.2843 * b_ ** 3
                                - 0.1036 * b_ ** 4)
            head = lathe([(0.0001, 0.0030), (0.0048, 0.0026), (0.0056, 0.0)], 6)
            parts.add("chrome", transformed(head, Matrix.Translation(Vector((bx, yy + side * (half - 0.0004),
                                                                             H_LE + G + bz)))
                                            @ frame(Vector((0, side, 0)))), smooth=20)


EXH_Y = -0.36       # single tip under the right-hand side of the rear bumper (y < 0 = car right)


def exhaust(parts):
    loc, n = rear_pt(EXH_Y, 0.30)
    x_end = (loc.x if loc is not None else -2.18) - 0.035
    axis = Vector((-1, 0.0, -0.05)).normalized()
    M = Matrix.Translation((x_end, EXH_Y, 0.268 + G)) @ frame(axis)
    r = 0.050
    tip = lathe([(r - 0.006, -0.20), (r - 0.006, -0.004), (r - 0.003, 0.0), (r, -0.004), (r, -0.16),
                 (r - 0.012, -0.22)], 64)
    parts.add("chrome", transformed(tip, M), smooth=40)
    inner = lathe([(0.0001, -0.20), (r - 0.0065, -0.20), (r - 0.0065, -0.004)], 48)
    parts.add("black", transformed(inner, M), smooth=40)
    # double-wall look: an inner chrome sleeve set 12 mm back, dark core further in
    sleeve = lathe([(r - 0.010, -0.012), (r - 0.013, -0.016), (r - 0.013, -0.06)], 48)
    parts.add("chrome", transformed(sleeve, M), smooth=40)


def rear_reflectors(parts):
    for side in (1, -1):
        loc, n = rear_pt(side * 0.70, 0.43)
        if loc is None:
            continue
        axis = Vector((n.x, n.y, 0)).normalized()
        R = Matrix.Rotation(math.atan2(axis.y, axis.x) - math.pi, 4, "Z")
        M = Matrix.Translation(loc - axis * 0.002) @ R
        parts.add("red", transformed(rounded_box((0.012, 0.11, 0.028), (0, 0, 0), 2, 0.4), M), smooth=50)
        parts.add("chrome", transformed(facet(rounded_box((0.007, 0.100, 0.020), (0.001, 0, 0), 1, 0.3), 0.0006),
                                        M), smooth=4)
        parts.add("black", transformed(rounded_box((0.008, 0.124, 0.040), (0.004, 0, 0), 2, 0.4), M), smooth=50)


def rear_valance(parts):
    """Lower rear bumper section: a black grained valance wrapping the bumper's lower third (it breaks the
    painted slab), standing 6-9 mm proud with a crisp top lip, tucking under the bumper; diffuser fins below."""
    hs = (0.385, 0.375, 0.350, 0.320, 0.292, 0.268)     # profile heights (top lip .. under the bumper)
    sec = []
    for k in range(49):
        a = math.radians(180 - 58 + 116 * k / 48)
        d = Vector((math.cos(a), math.sin(a), 0))
        row = []
        for j, h in enumerate(hs):
            o = Vector((-1.72, 0, h + G))
            loc, n = hit(o + d * 1.5, -d)
            if loc is None:
                break
            out = (0.0005, 0.009, 0.008, 0.007, 0.006, 0.004)[j]
            row.append(loc + d * out)
        if len(row) == len(hs):
            base = row[-1]
            row.append(base - d * 0.045 + Vector((0, 0, -0.012)))    # return under the bumper
            sec.append(row)
    bm = grid_surface(sec)
    bm.normal_update()
    if sum(f.normal.dot(f.calc_center_median() - Vector((-1.6, 0, 0.3 + G))) for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    parts.add("black", bm, smooth=35)


def antenna(parts):
    loc, n = top_pt(-0.86, 0.0)
    if loc is None:
        return
    base = rounded_box((0.07, 0.035, 0.022), (0, 0, 0), 2, 0.45)
    parts.add("black", transformed(base, Matrix.Translation(loc + Vector((0, 0, 0.006)))), smooth=50)
    mast = lathe([(0.0001, 0.20), (0.0018, 0.198), (0.0024, 0.0), (0.0035, -0.01)], 10)
    M = Matrix.Translation(loc + Vector((0.01, 0, 0.012))) @ frame(Vector((-0.55, 0, 0.83)))
    parts.add("black", transformed(mast, M), smooth=40)


PLATE_W, PLATE_H = 0.3048, 0.1524          # US plate, 12 x 6 in


def rrect(w, h, r, n=6):
    """CCW rounded rectangle outline centred at 0: list of (u, v)."""
    pts = []
    for (cx, cy), a0 in (((w / 2 - r, h / 2 - r), 0), ((-w / 2 + r, h / 2 - r), 90), ((-w / 2 + r, -h / 2 + r), 180),
                         ((w / 2 - r, -h / 2 + r), 270)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def plate_assembly(parts, centre, out, lamp=False):
    """Plate (textured, embossed by its normal map), black frame, four chrome bolts; optional plate lamps.
    centre: plate face centre (mesh coords); out: unit vector the plate faces."""
    out = Vector(out).normalized()
    up = Vector((0, 0, 1))
    right = up.cross(out).normalized()          # plate +u axis (text reads along it)
    up = out.cross(right).normalized()
    M = Matrix((right, up, out)).transposed().to_4x4()
    M = Matrix.Translation(centre) @ M
    # plate: front face (UV 0..1), thin edge, back
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UV0")
    ol = rrect(PLATE_W, PLATE_H, 0.010)
    fv = [bm.verts.new((u, v, 0.0)) for u, v in ol]
    bv = [bm.verts.new((u, v, -0.0015)) for u, v in ol]
    f = bm.faces.new(fv)
    for l in f.loops:
        l[uvl].uv = (l.vert.co.x / PLATE_W + 0.5, l.vert.co.y / PLATE_H + 0.5)
    bm.faces.new(bv[::-1])
    n = len(ol)
    for k in range(n):
        bm.faces.new((fv[k], bv[k], bv[(k + 1) % n], fv[(k + 1) % n]))
    bmesh.ops.triangulate(bm, faces=[f])
    parts.add("plate", transformed(bm, M), smooth=30)
    # frame: a black bezel ring proud of the plate face
    o1, o2, i1 = rrect(PLATE_W + 0.022, PLATE_H + 0.022, 0.016), rrect(PLATE_W + 0.014, PLATE_H + 0.014, 0.013), \
        rrect(PLATE_W - 0.010, PLATE_H - 0.010, 0.008)
    rings = [[Vector((u, v, -0.004)) for u, v in o1], [Vector((u, v, 0.0045)) for u, v in o1],
             [Vector((u, v, 0.006)) for u, v in o2], [Vector((u, v, 0.0042)) for u, v in i1],
             [Vector((u, v, 0.0004)) for u, v in i1]]
    fr = grid_surface([list(r) for r in zip(*rings)], closed_u=True)
    fr.normal_update()
    if sum(f.normal.z for f in fr.faces) < 0:
        bmesh.ops.reverse_faces(fr, faces=fr.faces)
    parts.add("black", transformed(fr, M), smooth=40)
    # bolts on the plate holes (texture positions 150/874 x 60/452 of 1024x512)
    for bu in (-0.1074, 0.1074):
        for bvv in (0.0583, -0.0583):
            bolt = lathe([(0.0001, 0.0042), (0.0045, 0.0036), (0.0062, 0.0012), (0.0064, 0.0)], 12)
            parts.add("chrome", transformed(bolt, M @ Matrix.Translation((bu, bvv, 0.0)) @
                                            Matrix.Rotation(math.pi / 2, 4, "X")), smooth=40)
    if lamp:
        for bu in (-0.075, 0.075):
            house = rounded_box((0.07, 0.016, 0.022), (bu, PLATE_H / 2 + 0.027, 0.004), 2, 0.35)
            parts.add("black", transformed(house, M), smooth=40)
            lens = rounded_box((0.055, 0.004, 0.012), (bu, PLATE_H / 2 + 0.0185, 0.006), 2, 0.4)
            parts.add("lens", transformed(lens, M), smooth=40)


def plates(parts):
    # rear: inside the bumper recess
    loc, n = rear_pt(0.0, 0.515)
    if loc is not None:
        x_back = loc.x + 0.021
        plate_assembly(parts, Vector((x_back - 0.007, 0.0, 0.515 + G)), (-1, 0, 0), lamp=False)
        # plate lamps: two housings tucked into the roof of the recess, lenses facing down onto the plate
        for yl in (-0.095, 0.095):
            parts.add("black", rounded_box((0.016, 0.060, 0.010), (loc.x + 0.009, yl, 0.600 + G), 2, 0.35), smooth=40)
            parts.add("lens", rounded_box((0.010, 0.046, 0.003), (loc.x + 0.009, yl, 0.5945 + G), 2, 0.4), smooth=40)
    # front: on the bar across the lower intake
    loc, n = front_pt(0.0, 0.405)
    if loc is not None:
        plate_assembly(parts, Vector((loc.x - 0.004, 0.0, 0.405 + G)), (1, 0, 0.06))


def plate_recess_back(parts):
    loc, n = rear_pt(0.0, 0.515)
    if loc is None:
        return
    x = loc.x + 0.021
    pts = sti_body.rounded_rect(-0.29, 0.415, 0.29, 0.615, 0.035)
    bm = bmesh.new()
    f = bm.faces.new([bm.verts.new((x, y, h + G)) for y, h in pts])
    f.normal_update()             # (a new face's normal is not computed yet)
    if f.normal.x > 0:            # face the viewer behind the car
        f.normal_flip()
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    parts.add("paint", bm)        # a painted recess (body colour, like the bumper)


def rear_emblem(parts):
    """Subaru oval (chrome ring, dark field, six chrome stars) on the boot lid, and the boot-lid key barrel."""
    loc, n = rear_pt(0.0, 0.865)
    if loc is None:
        return
    out = Vector((-1, 0, 0))
    c = loc + out * 0.004
    M = Matrix.Translation(c) @ frame(out) @ Matrix.Diagonal((1.0, 1.0, 0.62, 1.0))
    parts.add("chrome", transformed(ring(0.044, 0.053, 0.004, 0.010), M), smooth=30)
    parts.add("mesh", transformed(lathe([(0.0001, 0.0), (0.045, 0.0), (0.045, -0.008)], 48), M), smooth=30)
    stars = bmesh.new()
    for (sy, sz, r) in ((-0.021, 0.006, 0.012), (0.004, 0.015, 0.0055), (0.015, 0.008, 0.0055),
                        (0.006, -0.002, 0.0055), (0.023, -0.004, 0.0055), (0.011, -0.013, 0.0055)):
        pts = []
        for k in range(8):
            rr = r if k % 2 == 0 else r * 0.3
            a = math.pi / 4 * k
            # seen from behind the car the viewer's left is +y: the big star sits there
            pts.append(c + out * 0.0015 + Vector((0.0, -sy + rr * math.cos(a), sz + rr * math.sin(a))))
        f = stars.faces.new([stars.verts.new(p) for p in pts])
        f.normal_update()
        if f.normal.dot(out) < 0:
            f.normal_flip()
    parts.add("chrome", stars)
    # key barrel just above the bumper line
    loc, n = rear_pt(0.0, 0.760)
    if loc is not None:
        M = Matrix.Translation(loc + out * 0.001) @ frame(out)
        parts.add("chrome", transformed(lathe([(0.0001, 0.003), (0.006, 0.0026), (0.008, 0.001), (0.0085, -0.003)], 24),
                                        M), smooth=40)
        parts.add("black", transformed(rounded_box((0.0016, 0.0016, 0.010), (0, 0.0038, 0), 1, 0.3), M), smooth=40)


def underbody(parts):
    """Shapes visible from low angles: sump/crossmember, transmission tunnel bits, driveshaft, fuel tank,
    rear differential, suspension arms, exhaust pipe and silencer ('under': dull metal)."""
    U = "under"
    parts.add(U, rounded_box((0.55, 0.62, 0.13), (1.32, 0.0, 0.265 + G), 2, 0.25), smooth=40)       # sump / x-member
    parts.add(U, rounded_box((0.45, 0.32, 0.12), (0.72, 0.0, 0.275 + G), 2, 0.30), smooth=40)       # gearbox
    from sti_driver import tube
    parts.add(U, tube([(0.50, 0.0, 0.245 + G), (-1.05, 0.0, 0.262 + G)], [0.034, 0.034], 12), smooth=40)
    parts.add(U, rounded_box((0.26, 0.30, 0.17), (-1.235, 0.0, 0.285 + G), 2, 0.35), smooth=40)     # rear diff
    parts.add(U, rounded_box((0.56, 0.84, 0.11), (-0.78, 0.0, 0.255 + G), 2, 0.25), smooth=40)      # fuel tank
    for side in (1, -1):
        # lower arms and drive shafts toward the hubs (stop short of the wheel planes)
        for xa, h in ((1.2915, 0.215), (-1.2335, 0.235)):
            parts.add(U, tube([(xa - 0.06, side * 0.22, h + G), (xa, side * 0.60, h + 0.01 + G)], [0.020, 0.018], 10),
                      smooth=40)
            parts.add(U, tube([(xa, side * 0.12, 0.25 + G), (xa, side * 0.60, 0.231 + G)], [0.022, 0.022], 10),
                      smooth=40)
    # exhaust: front pipe -> centre pipe -> silencer -> tail pipe to the tip
    pipe = [(1.45, -0.10, 0.215), (0.90, -0.13, 0.205), (-0.40, -0.16, 0.205), (-1.00, -0.24, 0.212),
            (-1.55, -0.30, 0.220), (-1.66, -0.33, 0.225)]
    parts.add(U, tube([(x, y, h + G) for x, y, h in pipe], [0.026] * len(pipe), 12), smooth=40)
    parts.add(U, rounded_box((0.40, 0.34, 0.13), (-1.88, -0.28, 0.258 + G), 2, 0.4), smooth=40)     # silencer


def intake_and_skirts(parts):
    """Black horizontal bar across the lower intake, side-skirt lower lips, diffuser strakes."""
    # bar across the intake (plate mount)
    rows = []
    for k in range(17):
        y = -0.36 + 0.72 * k / 16
        loc, n = front_pt(y, 0.405)
        x = (loc.x if loc is not None else 2.15) - 0.012
        rows.append([Vector((x - 0.05, y, 0.384 + G)), Vector((x, y, 0.386 + G)), Vector((x + 0.004, y, 0.405 + G)),
                     Vector((x, y, 0.424 + G)), Vector((x - 0.05, y, 0.426 + G))])
    parts.add("black", grid_surface(rows), smooth=40)
    # side-skirt lower lip: a black strip under the rocker between the arches
    for side in (1, -1):
        rows = []
        for k in range(31):
            x = 0.86 - (0.86 - (-0.83)) * k / 30
            loc, n = side_pt(x, 0.215, side)
            if loc is None:
                continue
            y = loc.y
            rows.append([Vector((x, y - side * 0.05, 0.200 + G)), Vector((x, y + side * 0.004, 0.200 + G)),
                         Vector((x, y + side * 0.010, 0.214 + G)), Vector((x, y - side * 0.004, 0.232 + G))])
        bm = grid_surface(rows)
        bm.normal_update()
        if sum(f.normal.y * side for f in bm.faces) < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
        parts.add("black", bm, smooth=40)
    # diffuser: fins under the rear bumper (clear of the exhaust tip on the right)
    for y in (-0.54, -0.09, 0.05, 0.19, 0.33, 0.47):
        loc, n = rear_pt(y, 0.30)
        x = (loc.x if loc is not None else -2.18) + 0.025
        fin = rounded_box((0.26, 0.008, 0.075), (x + 0.12, y, 0.255 + G), 2, 0.3)
        parts.add("black", fin, smooth=40)


def scoop_slats(parts):
    """Three horizontal slats in the hood-scoop mouth (closed blades, seen from both sides)."""
    for k, dz in enumerate((0.018, 0.034, 0.050)):
        loc, n = top_pt(1.50, 0.0)
        z = (loc.z if loc is not None else 0.95 + G) + dz
        parts.add("black", rounded_box((0.022, 0.54, 0.006), (1.543, 0.0, z), 2, 0.3), smooth=40)


def wiper_caps(parts):
    for (x, y) in ((0.93, -0.50), (0.935, 0.04)):
        loc, n = top_pt(x, y)
        if loc is not None:
            cap = rounded_box((0.06, 0.05, 0.03), (0, 0, 0), 2, 0.45)
            parts.add("black", transformed(cap, Matrix.Translation(loc + n * 0.012)), smooth=50)


def badges(parts):
    """3D badges: chrome 'WRX' (boot, left) and pink 'STi' (boot, right; grille, right)."""
    for text, part, y, h, height in (("WRX", "chrome", 0.36, 0.905, 0.030), ("STi", "badge", -0.36, 0.905, 0.034)):
        loc, n = rear_pt(y, h)
        if loc is None:
            continue
        bm = text_bm(text, height, 0.004, shear=0.18 if text == "STi" else 0.0,
                     font="/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf" if text == "WRX" else
                     "/System/Library/Fonts/Supplemental/Arial Black.ttf")
        nn = Vector((n.x, n.y, 0.0)).normalized()
        # text reads left->right for a viewer behind the car: +x(text) -> -y(car)
        R = Matrix((Vector((0, -1, 0)), Vector((0, 0, 1)), nn)).transposed().to_4x4()
        parts.add(part, transformed(bm, Matrix.Translation(loc - nn * 0.001) @ R), smooth=30)
    loc, n = front_pt(-0.25, 0.66)
    if loc is not None:
        bm = text_bm("STi", 0.026, 0.004, shear=0.18)
        R = Matrix((Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0)))).transposed().to_4x4()
        parts.add("badge", transformed(bm, Matrix.Translation(Vector((loc.x - 0.022, loc.y, loc.z))) @ R), smooth=30)


def wing_brake_light(parts):
    """High-mount stop lamp strip on the wing's trailing edge (centre)."""
    chord, H_LE, aoa = 0.240, 1.212, math.radians(-10.0)
    te_x = -1.795 - chord * math.cos(aoa)
    te_z = H_LE + G - chord * math.sin(aoa)
    bm = rounded_box((0.005, 0.24, 0.013), (te_x + 0.0005, 0.0, te_z + 0.008), 2, 0.4)
    parts.add("red", bm, smooth=40)
    parts.add("chrome", facet(rounded_box((0.003, 0.226, 0.009), (te_x + 0.0012, 0.0, te_z + 0.008), 1, 0.3),
                              0.0004), smooth=4)


def build(parts, bvh, patches):
    global BVH
    BVH = bvh
    headlamps(parts, patches.get("headlamp", []))
    taillamps(parts, patches.get("taillamp", []))
    front_end(parts)
    hood_scoop(parts)
    cowl_and_wipers(parts)
    mirrors(parts)
    handles(parts)
    markers(parts)
    wing(parts)
    exhaust(parts)
    plate_recess_back(parts)
    plates(parts)
    rear_emblem(parts)
    antenna(parts)
    rear_reflectors(parts)
    rear_valance(parts)
    underbody(parts)
    intake_and_skirts(parts)
    scoop_slats(parts)
    wiper_caps(parts)
    badges(parts)
    wing_brake_light(parts)
