"""Wheel parts, modelled at the origin with the axle along Y and the outer face toward +Y.

tire    225/45R17 (R 0.317 m): sidewall bulge, rim protector, 4 circumferential grooves, shoulder blocks
rim     gold 17x8" ET53, 5 twin-spoke (10 spokes), ~4 cm concave dish (caliper shaped to clear it), lip, barrel,
        hub, centre cap
brake   294 mm ventilated disc (two friction plates + 36 radial vanes), drilled + slotted, with a bell (spins with
        the wheel); lug nuts
caliper gold four-pot Brembo-style caliper at the trailing side (wheel-local, must not spin)
"""
import math

import bmesh
from mathutils import Matrix, Vector

from sti_common import grid_surface, lathe, merge, rounded_box, subsurf_bm, transformed, remove, new_object

R, W = 0.317, 0.225
RB = 0.2159            # bead seat radius (17")
Y_MOUNT = 0.053        # hub mounting face (ET53)


# --- tyre -----------------------------------------------------------------------------------------------
def tyre_profile():
    """(r, y, groove_zone) from the outer bead over the tread to the inner bead. groove_zone: 0 none,
    1 shoulder block (lateral grooves cut here), 2 circumferential groove bottom."""
    hw = W / 2
    P = []
    # outer sidewall: bead -> bulge -> shoulder
    # rim-protector ridge at t=0.08, a raised (0.6 mm) lettering band between t=0.40 and 0.52
    for t, extra in ((0.0, 0.0), (0.08, 0.004), (0.17, 0.0), (0.30, 0.0), (0.395, 0.0), (0.40, 0.0006),
                     (0.52, 0.0006), (0.525, 0.0), (0.66, 0.0), (0.82, 0.0), (1.0, 0.0)):
        r = RB + 0.006 + (R - 0.022 - RB - 0.006) * t
        bulge = 0.012 * math.sin(math.pi * min(1.0, t * 1.15)) ** 1.2
        y = hw - 0.010 + bulge - 0.004 * t + extra
        P.append((r, y, 0))
    n_side = len(P)
    # shoulder round
    for a in (15, 35, 55, 75):
        aa = math.radians(a)
        P.append((R - 0.022 + 0.022 * math.sin(aa), hw - 0.012 - 0.012 * (1 - math.cos(aa)) - 0.004, 0))
    # tread with grooves at +-0.025 and +-0.066 (width 0.011, depth 0.007)
    grooves = [0.066, 0.025, -0.025, -0.066]
    ys = [0.097]
    for g in grooves:
        ys += [g + 0.0075, g + 0.0055, g - 0.0055, g - 0.0075]
    ys += [-0.097]
    for i, y in enumerate(ys):
        crown = 0.003 * (y / 0.1) ** 2
        r = R - crown
        zone = 1 if abs(y) > 0.071 else 0
        in_groove = any(abs(y - g) < 0.0056 for g in grooves)
        if in_groove:
            r -= 0.007
            zone = 2
        P.append((r, y, zone))
    # inner shoulder + sidewall (mirror)
    tail = [(r, -y, z) for r, y, z in P[:n_side + 4]][::-1]
    return P + tail


def tyre(pitches=56):
    prof = tyre_profile()
    # angular samples: per pitch a block then a lateral groove (shoulders only)
    angles, groove = [], []
    for k in range(pitches):
        a0 = 2 * math.pi * k / pitches
        p = 2 * math.pi / pitches
        for f, g in ((0.0, False), (0.70, False), (0.74, True), (0.92, True), (0.96, False)):
            angles.append(a0 + f * p)
            groove.append(g)
    bm = bmesh.new()
    rings = []
    for a, g in zip(angles, groove):
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for r, y, z in prof:
            rr = r - (0.006 if (g and z == 1) else 0.0)
            ring.append(bm.verts.new((rr * ca, y, rr * sa)))
        rings.append(ring)
    n, m = len(rings), len(prof)
    for i in range(n):
        r0, r1 = rings[i], rings[(i + 1) % n]
        for j in range(m - 1):
            bm.faces.new((r0[j], r1[j], r1[j + 1], r0[j + 1]))
    bm.normal_update()
    # outward normals: area-weighted vote over all faces (normal . centre > 0 for tread and sidewalls)
    vote = sum(f.normal.dot(f.calc_center_median()) * f.calc_area() for f in bm.faces)
    if vote < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return bm


# --- rim -------------------------------------------------------------------------------------------------
def y_face(r):
    """Concave spoke face: hub recessed, rim edge outboard - a ~4 cm dish (y 0.063 at the hub -> 0.103 at the lip).
    The caliper is shaped to this (CAL_FACE: its outer half follows the spoke backs), see clearance()."""
    t = max(0.0, (r - 0.07) / (0.205 - 0.07))
    return Y_MOUNT + 0.010 + 0.040 * t ** 1.6


SPOKE_R0, SPOKE_R1, SPOKE_D0, SPOKE_D1 = 0.068, 0.210, 0.030, 0.022


def spoke_back(r):
    """y of the spoke's back (inboard) face at radius r."""
    t = (r - SPOKE_R0) / (SPOKE_R1 - SPOKE_R0)
    return y_face(r) - (SPOKE_D0 + (SPOKE_D1 - SPOKE_D0) * t)


def rounded_trapezoid(wf, wb, d, rc, n=4, ridge=0.0):
    """Closed CCW outline: front face (width wf at +d/2, crowned by `ridge` in the middle), narrower back
    (wb at -d/2), rounded corners."""
    corners = [(wf / 2 - rc, d / 2 - rc), (-wf / 2 + rc, d / 2 - rc), (-wb / 2 + rc, -d / 2 + rc), (wb / 2 - rc, -d / 2 + rc)]
    pts = []
    m = len(corners)
    for i in range(m):
        p0, p1, p2 = corners[i - 1], corners[i], corners[(i + 1) % m]
        e_in = (p1[0] - p0[0], p1[1] - p0[1])
        e_out = (p2[0] - p1[0], p2[1] - p1[1])
        a0 = math.atan2(-e_in[0], e_in[1])        # outward normal of the incoming edge (CCW polygon)
        a1 = math.atan2(-e_out[0], e_out[1])
        while a1 < a0:
            a1 += 2 * math.pi
        for k in range(n + 1):
            a = a0 + (a1 - a0) * k / n
            pts.append((p1[0] + rc * math.cos(a), p1[1] + rc * math.sin(a)))
        if i == 0:
            pts.append((0.0, d / 2 + ridge))         # front crown (catches a highlight along the spoke)
    return pts


def spoke(angle, r0=SPOKE_R0, r1=SPOKE_R1, w0=0.041, w1=0.035, d0=SPOKE_D0, d1=SPOKE_D1, nr=16, ns=16):
    """Lofted spoke from the hub to the rim along direction `angle` (in the xz plane), rounded section."""
    secs = []
    for i in range(nr + 1):
        t = i / nr
        r = r0 + (r1 - r0) * t
        w = w0 + (w1 - w0) * t + 0.016 * math.exp(-((t - 1.0) / 0.10) ** 2)   # flare into the rim
        d = d0 + (d1 - d0) * t
        yc = y_face(r) - d / 2
        sec = [(r, cx, yc + cy) for cx, cy in rounded_trapezoid(w, 0.50 * w, d, 0.0045, ridge=0.0035)]
        secs.append(sec)
    ca, sa = math.cos(angle), math.sin(angle)
    P = []
    for sec in secs:
        P.append([Vector((r * ca - cx * sa, y, r * sa + cx * ca)) for r, cx, y in sec])
    bm = grid_surface(P, closed_v=True)
    bm.normal_update()
    c = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    out = sum((f.normal.dot(f.calc_center_median() - Vector((c.x, c.y, c.z))) for f in bm.faces))
    if out < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return bm


def rim():
    bm = bmesh.new()
    hw = 0.1015
    # outer lip + barrel + inner flange as one closed lathe profile (outside then inside)
    prof = [
        (0.2140, hw + 0.004), (0.2225, hw + 0.002), (0.2262, hw - 0.004), (0.2250, hw - 0.010), (0.2165, hw - 0.012),
        (0.2135, hw - 0.020), (0.2128, 0.040), (0.2060, 0.000), (0.2060, -hw + 0.020), (0.2130, -hw + 0.012),
        (0.2225, -hw + 0.006), (0.2225, -hw - 0.002), (0.2050, -hw - 0.002), (0.1995, -hw + 0.012),
        (0.1995, 0.000), (0.2050, 0.045), (0.2055, hw - 0.022), (0.2080, hw - 0.004), (0.2140, hw + 0.004)]
    merge(bm, lathe(prof, 96))
    # hub: mounting disc with a raised centre
    hub = lathe([(0.0001, Y_MOUNT + 0.030), (0.030, Y_MOUNT + 0.030), (0.034, Y_MOUNT + 0.026),
                 (0.034, Y_MOUNT + 0.020), (0.068, Y_MOUNT + 0.016), (0.078, Y_MOUNT + 0.008),
                 (0.078, Y_MOUNT - 0.002), (0.0001, Y_MOUNT - 0.002)], 64)
    merge(bm, hub)
    # 5 twin spokes
    for k in range(5):
        base = 2 * math.pi * k / 5 + math.pi / 2
        for s in (-1, 1):
            merge(bm, spoke(base + s * math.radians(6.0)))
    bm.normal_update()
    return bm


def centre_cap_and_nuts():
    cap = lathe([(0.0001, Y_MOUNT + 0.036), (0.022, Y_MOUNT + 0.035), (0.028, Y_MOUNT + 0.031), (0.030, Y_MOUNT + 0.026)], 48)
    nuts = bmesh.new()
    for k in range(5):
        a = 2 * math.pi * k / 5 + math.pi / 2 + math.pi / 5
        nut = lathe([(0.0001, 0.016), (0.006, 0.0155), (0.0095, 0.012), (0.0105, 0.004), (0.0105, -0.004)], 6)
        merge(nuts, transformed(nut, Matrix.Translation((0.050 * math.cos(a), Y_MOUNT + 0.018, 0.050 * math.sin(a)))))
    return cap, nuts


# --- brakes ----------------------------------------------------------------------------------------------
VENT = (0.0135, 0.0225)      # the ventilation gap between the two friction plates (disc y 0.004..0.032)
# caliper outer face y by radius: follows the dish (spoke backs) with >= 6 mm clearance, so the outer half is a
# wedge - slim at the inner radius, full depth at the bridge - instead of making the spokes shallow
CAL_FACE = [(0.122, 0.034), (0.128, 0.040), (0.150, 0.048), (0.166, 0.054), (0.176, 0.056), (0.181, 0.050)]
CAL_A = (150.0, 212.0)       # caliper arc (deg, xz plane): trailing side


def clearance():
    """Smallest gap (m) between the caliper's outer face and the spoke backs over the caliper's radius."""
    gaps = []
    for (r0, y0), (r1, y1) in zip(CAL_FACE[:-1], CAL_FACE[1:]):
        for k in range(11):
            r = r0 + (r1 - r0) * k / 10
            gaps.append(spoke_back(r) - (y0 + (y1 - y0) * k / 10))
    return min(gaps)


def disc():
    """294 mm ventilated disc: outer and inner friction plates (the vanes are added after the drilling)."""
    ro, ri, y0, y1 = 0.147, 0.088, 0.004, 0.032
    g0, g1 = VENT
    bm = bmesh.new()
    for a, b in ((g1, y1), (y0, g0)):
        merge(bm, lathe([(ri, b), (ro - 0.002, b), (ro, b - 0.002), (ro, a + 0.002), (ro - 0.002, a), (ri, a),
                         (ri, b)], 96))
    merge(bm, lathe([(ri, g0), (ri + 0.006, g0), (ri + 0.006, g1), (ri, g1), (ri, g0)], 96))   # inner web
    # bell / hat
    hat = lathe([(0.088, y1 - 0.004), (0.084, Y_MOUNT - 0.004), (0.080, Y_MOUNT), (0.034, Y_MOUNT),
                 (0.034, Y_MOUNT - 0.006), (0.078, Y_MOUNT - 0.008), (0.082, y1)], 64)
    merge(bm, hat)
    bm.normal_update()
    return bm


def disc_holes_and_slots():
    """Cutter solids: cross-drilled holes and curved slots in the friction faces."""
    cut = bmesh.new()
    for k in range(24):
        a = 2 * math.pi * k / 24
        for rr in ((0.112, 0.130) if k % 2 == 0 else (0.121, 0.139)):
            c = lathe([(0.0001, 0.06), (0.0035, 0.06), (0.0035, -0.03), (0.0001, -0.03)], 10)
            merge(cut, transformed(c, Matrix.Translation((rr * math.cos(a), 0, rr * math.sin(a)))))
    for k in range(6):
        a0 = 2 * math.pi * k / 6 + 0.25
        for face_y in (0.032, 0.004):
            pts = []
            for i in range(9):
                t = i / 8
                a = a0 + 0.35 * t
                r = 0.100 + 0.040 * t
                pts.append((r * math.cos(a), r * math.sin(a)))
            for (x0, z0), (x1, z1) in zip(pts[:-1], pts[1:]):
                L = math.hypot(x1 - x0, z1 - z0)
                b = bmesh.new()
                bmesh.ops.create_cube(b, size=1.0)
                bmesh.ops.scale(b, vec=(L * 1.15, 0.003, 0.0025), verts=b.verts)
                ang = math.atan2(z1 - z0, x1 - x0)
                M = Matrix.Translation(((x0 + x1) / 2, face_y, (z0 + z1) / 2)) @ Matrix.Rotation(-ang, 4, "Y")
                merge(cut, transformed(b, M))
    return cut


def vanes(n=36):
    """Radial cooling vanes in the gap between the friction plates (seen as dark slots at the disc edge)."""
    bm = bmesh.new()
    g0, g1 = VENT
    for k in range(n):
        a = 2 * math.pi * (k + 0.5) / n
        b = bmesh.new()
        bmesh.ops.create_cube(b, size=1.0)
        bmesh.ops.scale(b, vec=(0.050, g1 - g0 + 0.001, 0.0045), verts=b.verts)
        M = Matrix.Rotation(-a, 4, "Y") @ Matrix.Translation((0.1205, (g0 + g1) / 2, 0.0))
        merge(bm, transformed(b, M))
    return bm


def caliper():
    """Four-pot caliper straddling the disc at the trailing side (angles in the xz plane): inner half, a wedge
    outer half under the spoke backs (CAL_FACE), the bridge at the outer radius; plus bridge bolts and a raised
    logo pad ('caliper_logo')."""
    a0, a1 = (math.radians(a) for a in CAL_A)
    yi = -0.026
    prof = [(0.122, yi + 0.008)] + CAL_FACE + [(0.181, yi + 0.010), (0.170, yi), (0.128, yi), (0.122, yi + 0.008)]
    body = lathe(prof, 18, a0=a0, a1=a1)
    for a in (a0, a1):
        ca, sa = math.cos(a), math.sin(a)
        vs = [body.verts.new((r * ca, y, r * sa)) for r, y in prof[:-1]]
        body.faces.new(vs)
    bmesh.ops.remove_doubles(body, verts=body.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(body, faces=body.faces)
    return subsurf_bm(body, 1)


def caliper_details():
    """(bridge bolts, logo pad): two hex bolt heads on the outer face near the arc ends, and a raised pad in the
    middle of the outer face (the caliper's logo field)."""
    bolts = bmesh.new()
    for adeg in (CAL_A[0] + 7, CAL_A[1] - 7):
        a = math.radians(adeg)
        r = 0.170
        y = 0.0545
        head = lathe([(0.0001, 0.0035), (0.0050, 0.0030), (0.0058, 0.0)], 6)
        merge(bolts, transformed(head, Matrix.Translation((r * math.cos(a), y - 0.0008, r * math.sin(a)))))
    a0, a1 = math.radians(167), math.radians(195)
    lp = [(0.140, 0.0003), (0.1405, 0.0018), (0.1615, 0.0018), (0.162, 0.0003)]
    def face_y(r):
        for (r0, y0), (r1, y1) in zip(CAL_FACE[:-1], CAL_FACE[1:]):
            if r0 <= r <= r1:
                return y0 + (y1 - y0) * (r - r0) / (r1 - r0)
        return CAL_FACE[-1][1]
    logo = lathe([(r, face_y(r) - 0.0012 + dy) for r, dy in lp], 12, a0=a0, a1=a1)
    return bolts, logo


def sidewall_text(text, r_mid, a_mid, height=0.0135, raise_=0.0007):
    """Raised lettering wrapped on the outer sidewall (generic size marking, no brands)."""
    import bpy
    from sti_common import evaluated_mesh, remove
    cu = bpy.data.curves.new("tyre_txt", "FONT")
    cu.body = text
    try:
        cu.font = bpy.data.fonts.load("/System/Library/Fonts/Supplemental/Arial Black.ttf", check_existing=True)
    except Exception:
        pass
    cu.size = 1.0
    cu.align_x = "CENTER"
    cu.extrude = 0.0
    ob = bpy.data.objects.new("tyre_txt", cu)
    bpy.context.scene.collection.objects.link(ob)
    me = evaluated_mesh(ob)
    remove(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    zs = [v.co.y for v in bm.verts]
    z0, z1 = min(zs), max(zs)
    k = height / (z1 - z0)
    # extrude the letters 0.7 mm off the sidewall
    res = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    top = {v for v in res["geom"] if isinstance(v, bmesh.types.BMVert)}
    prof = [(r, y) for r, y, z in tyre_profile()[:11]]
    def y_side(r):
        for (r0, y0), (r1, y1) in zip(prof[:-1], prof[1:]):
            if r0 <= r <= r1:
                return y0 + (y1 - y0) * (r - r0) / (r1 - r0)
        return prof[-1][1]
    for v in bm.verts:
        u, w = v.co.x * k, (v.co.y - (z0 + z1) / 2) * k
        r = r_mid + w
        a = a_mid + u / r_mid
        y = y_side(r) + (raise_ if v in top else -0.0004)
        v.co = Vector((r * math.cos(a), y, r * math.sin(a)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def build(parts):
    gap = clearance()
    print(f"[sti_wheels] caliper outer face to spoke backs: min clearance {gap * 1000:.1f} mm "
          f"({'OK' if gap >= 0.004 else 'TOO TIGHT'}); dish depth {(y_face(0.205) - y_face(0.07)) * 1000:.0f} mm",
          flush=True)
    parts.add("tire", tyre(), smooth=40)
    # (no sidewall lettering: the game mirrors the wheel for the right side, text would read backwards)
    parts.add("rim", rim(), smooth=40)
    cap, nuts = centre_cap_and_nuts()
    parts.add("rim", cap, smooth=40)
    parts.add("brake", nuts, smooth=25)
    # disc with drilled holes + slots (exact boolean)
    import bpy
    from sti_common import evaluated_mesh, bm_to_mesh
    d = new_object("disc_tmp", bm_to_mesh(disc()))
    c = new_object("disc_cut", bm_to_mesh(disc_holes_and_slots()))
    m = d.modifiers.new("b", "BOOLEAN")
    m.operation, m.solver, m.object = "DIFFERENCE", "EXACT", c
    me = evaluated_mesh(d)
    remove(d)
    remove(c)
    parts.add("brake", me, smooth=40)
    bpy.data.meshes.remove(me)
    parts.add("brake", vanes(), smooth=40)
    parts.add("caliper", caliper(), smooth=50)
    bolts, logo = caliper_details()
    parts.add("caliper", bolts, smooth=20)
    parts.add("caliper", logo, smooth=30)


TIRE_UV = (0.222, 0.296)     # radius band of the outer sidewall mapped to V 0.25..1.0 of sti_tire_normal.png


def tire_uv(me):
    """UV0 for the tyre: outer sidewall = (angle / 2pi, radius band), every other face on the flat strip."""
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    uvl = me.uv_layers.new(name="UV0")
    r0, r1 = TIRE_UV
    for p in me.polygons:
        c, n = p.center, p.normal
        rc = math.hypot(c.x, c.z)
        side = c.y > 0.06 and n.y > 0.35 and r0 - 0.004 <= rc <= r1 + 0.004
        us = []
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            us.append((math.atan2(co.z, co.x) / (2 * math.pi)) % 1.0)
        if side and max(us) - min(us) > 0.5:
            us = [u + 1.0 if u < 0.5 else u for u in us]
        for k, li in enumerate(p.loop_indices):
            co = me.vertices[me.loops[li].vertex_index].co
            if side:
                r = math.hypot(co.x, co.z)
                v = 0.25 + 0.75 * min(1.0, max(0.0, (r - r0) / (r1 - r0)))
                uvl.data[li].uv = (us[k], v)
            else:
                uvl.data[li].uv = (0.5 + 0.0001 * k, 0.1)
