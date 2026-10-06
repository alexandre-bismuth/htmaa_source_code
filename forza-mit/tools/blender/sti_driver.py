"""Static driver in the (right-hand-drive) driver's seat: race suit, gloves on the wheel at ten-to-two, harness,
helmet with a dark visor. A 1.75 m adult sitting low in the bucket seat. Parts: driver_suit, driver_helmet,
driver_visor; gloves, boots and harness go to 'black'.

All positions are heights above ground (h) in the car frame; the seat geometry is in sti_interior.py
(driver seat lowered 4 cm and moved 5 cm forward, see DRIVER_SEAT).
"""
import math

import bmesh
from mathutils import Matrix, Vector

from sti_common import G, grid_surface, lathe, merge, rounded_box, subsurf_bm, transformed

Y = -0.37                                    # driver centre line (right-hand drive)
WHEEL_C = Vector((0.40, Y, 0.90))            # steering-wheel centre (x, y, h), tilted 24 deg (sti_interior)
WHEEL_TILT = math.radians(24)
SPINE = Vector((-0.30, 0.0, 0.954)).normalized()
FWD = Vector((0.954, 0.0, 0.30)).normalized()   # chest normal, perpendicular to the spine
P0 = Vector((0.035, Y, 0.565))               # pelvis centre


def H(v):
    """height-above-ground vector -> mesh coordinates."""
    return Vector((v.x, v.y, v.z + G))


def tube(points, radii, seg=14, cap=True):
    """Smooth tube along a polyline with per-point radius (rotation-minimising frames)."""
    pts = [Vector(p) for p in points]
    n = len(pts)
    tans = []
    for i in range(n):
        t = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        tans.append(t.normalized())
    ref = Vector((0, 0, 1)) if abs(tans[0].z) < 0.9 else Vector((1, 0, 0))
    u = (ref - tans[0] * ref.dot(tans[0])).normalized()
    rings = []
    for i in range(n):
        if i:
            u = (u - tans[i] * u.dot(tans[i])).normalized()
        v = tans[i].cross(u)
        rings.append([pts[i] + (u * math.cos(2 * math.pi * k / seg) + v * math.sin(2 * math.pi * k / seg)) * radii[i]
                      for k in range(seg)])
    bm = grid_surface(rings, closed_v=True)
    if cap:
        for ring, c in ((rings[0], pts[0] - tans[0] * radii[0] * 0.6), (rings[-1], pts[-1] + tans[-1] * radii[-1] * 0.6)):
            cv = bm.verts.new(c)
            vs = [bm.verts.new(p) for p in ring]
            for k in range(seg):
                bm.faces.new((vs[k], vs[(k + 1) % seg], cv))
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def bezier(a, b, c, n=8):
    return [a * (1 - t) ** 2 + b * 2 * (1 - t) * t + c * t * t for t in [k / (n - 1) for k in range(n)]]


def two_bone(root, target, l1, l2, pole):
    """Elbow / knee position for a two-segment limb, bending toward `pole`."""
    d = target - root
    L = min(d.length, l1 + l2 - 1e-4)
    dn = d.normalized()
    a = (l1 * l1 - l2 * l2 + L * L) / (2 * L)
    hgt = math.sqrt(max(l1 * l1 - a * a, 0.0))
    p = (pole - dn * pole.dot(dn)).normalized()
    return root + dn * a + p * hgt


def torso():
    """Lofted elliptical sections along the reclined spine: pelvis, waist, chest, shoulders, neck."""
    lat = Vector((0, 1, 0))
    secs = []
    prof = [(-0.10, 0.160, 0.105, 0.00), (-0.02, 0.178, 0.118, 0.00), (0.08, 0.162, 0.112, 0.01),
            (0.18, 0.165, 0.116, 0.015), (0.28, 0.182, 0.122, 0.02), (0.36, 0.198, 0.120, 0.02),
            (0.43, 0.200, 0.108, 0.01), (0.475, 0.160, 0.088, 0.0), (0.505, 0.098, 0.068, 0.0),
            (0.535, 0.066, 0.060, 0.005), (0.57, 0.058, 0.055, 0.01)]
    for s, rx, rz, fwd in prof:
        c = H(P0) + SPINE * s + FWD * fwd
        sec = []
        for k in range(20):
            a = 2 * math.pi * k / 20
            ca, sa = math.cos(a), math.sin(a)
            # flatten the back against the seat, round the front
            depth = rz * (sa if sa > 0 else 0.75 * sa)
            sec.append(c + lat * (rx * math.copysign(abs(ca) ** 0.8, ca)) + FWD * depth)
        secs.append(sec)
    bm = grid_surface(secs, closed_v=True)
    for ring in (secs[0], secs[-1]):
        bm.faces.new([bm.verts.new(p) for p in ring])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return subsurf_bm(bm, 2)


# --- helmet -------------------------------------------------------------------------------------------------
EYE = (math.radians(56), math.radians(-3), math.radians(16.5))       # eyeport half-width, centre el, half-height
VISOR = (math.radians(66), math.radians(-3), math.radians(21.5))


def shell_point(c, az, el, scale=1.0):
    """Closed-face rally helmet shell: longer back, squared jaw, deeper chin. az 0 = forward (+x)."""
    d = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    # squared jaw / cheeks: horizontal superellipse, stronger toward the bottom
    p = 2.0 + 1.0 * min(1.0, max(0.0, -math.sin(el) / 0.8))
    phi = math.atan2(d.y, d.x)
    rho = 1.0 / (abs(math.cos(phi)) ** p + abs(math.sin(phi)) ** p) ** (1.0 / p)
    hx, hy = d.x * rho, d.y * rho
    sx = 0.143 if hx > 0 else 0.163
    sy = 0.124
    sz = 0.140 if d.z > 0 else 0.150
    v = Vector((hx * sx, hy * sy, d.z * sz))
    # chin bar juts forward a little at the bottom front
    if d.z < 0 and hx > 0:
        v.x += 0.012 * (-d.z) * hx
    return c + v * scale


def in_super(az, el, box, k=0.0):
    A, e0, E = box
    return (abs(az) / (A + k)) ** 6 + (abs(el - e0) / (E + k)) ** 6 < 1.0


def snap_super(az, el, box):
    """Move a param point radially (in param space) onto the superellipse boundary."""
    A, e0, E = box
    x, y = az / A, (el - e0) / E
    r = (abs(x) ** 6 + abs(y) ** 6) ** (1 / 6)
    if r < 1e-6:
        return az, el
    return az / r, e0 + (el - e0) / r


def helmet(parts, c):
    r = math.radians
    naz, nel = 72, 40
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UV0")
    grid, params = [], {}
    for i in range(nel + 1):
        row = []
        for k in range(naz + 1):
            az = -math.pi + 2 * math.pi * k / naz
            el_min = r(-50) - r(17) * max(0.0, math.cos(az)) ** 1.5
            el = el_min + (r(89.5) - el_min) * i / nel
            v = bm.verts.new(shell_point(c, az, el))
            params[v] = (az, el)
            row.append(v)
        grid.append(row)
    for i in range(nel):
        for k in range(naz):
            a0, e0 = params[grid[i][k]]
            a1, e1 = params[grid[i + 1][k + 1]]
            if in_super(0.5 * (a0 + a1), 0.5 * (e0 + e1), EYE):
                continue                                   # eyeport opening
            f = bm.faces.new((grid[i][k], grid[i][k + 1], grid[i + 1][k + 1], grid[i + 1][k]))
            for l in f.loops:
                az, el = params[l.vert]
                l[uvl].uv = (az / (2 * math.pi) + 0.5, (el + math.pi / 2) / math.pi)
    # snap the eyeport edge onto the rounded-rectangle outline, then roll it inward (padding rim)
    bm.verts.ensure_lookup_table()
    eye_edge = [v for v in bm.verts if v.is_boundary and in_super(*params[v], EYE, r(9)) and v.link_faces]
    for v in eye_edge:
        az, el = snap_super(*params[v], EYE)
        params[v] = (az, el)
        v.co = shell_point(c, az, el)
    for f in bm.faces:
        for l in f.loops:
            az, el = params[l.vert]
            l[uvl].uv = (az / (2 * math.pi) + 0.5, (el + math.pi / 2) / math.pi)
    bm.normal_update()
    if sum(f.normal.dot(f.calc_center_median() - c) for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    parts.add("driver_helmet", bm, smooth=50)
    # eyeport rim wall (shell colour, 18 mm deep) and the dark padding cavity behind it
    def loop_of(pred_box, scale_in):
        pts = []
        for k in range(96):
            t = 2 * math.pi * k / 96
            x, y = math.cos(t), math.sin(t)
            q = (abs(x) ** 6 + abs(y) ** 6) ** (1 / 6)
            az, el = pred_box[0] * x / q, pred_box[1] + pred_box[2] * y / q
            pts.append((shell_point(c, az, el), shell_point(c, az, el, scale_in)))
        return pts
    rim = loop_of(EYE, 0.86)
    wall = grid_surface([[o, o.lerp(i, 0.5), i] for o, i in rim], closed_u=True)
    wall.normal_update()
    if sum(f.normal.dot(c - f.calc_center_median()) for f in wall.faces) < 0:
        bmesh.ops.reverse_faces(wall, faces=wall.faces)
    parts.add("black", wall, smooth=50)
    cav = bmesh.new()
    rows = []
    for i in range(9):
        row = []
        for k in range(17):
            az = r(-64) + r(128) * k / 16
            el = r(-24) + r(46) * i / 8
            row.append(shell_point(c, az, el, 0.84))
        rows.append(row)
    cav = grid_surface(rows)
    cav.normal_update()
    if sum(f.normal.dot(c - f.calc_center_median()) for f in cav.faces) > 0:
        bmesh.ops.reverse_faces(cav, faces=cav.faces)
    parts.add("black", cav, smooth=50)
    # dark smoked visor: a curved sheet a little proud of the shell, rounded corners, with a lift tab
    vrows = []
    for i in range(13):
        row = []
        for k in range(41):
            x = -1 + 2 * k / 40
            y = -1 + 2 * i / 12
            q = max(1e-6, (abs(x) ** 6 + abs(y) ** 6) ** (1 / 6))
            s_ = max(abs(x), abs(y)) / q              # square -> superellipse
            az, el = VISOR[0] * x * s_, VISOR[1] + VISOR[2] * y * s_
            row.append(shell_point(c, az, el, 1.032))
        vrows.append(row)
    vis = grid_surface(vrows)
    vis.normal_update()
    if sum(f.normal.dot(f.calc_center_median() - c) for f in vis.faces) < 0:
        bmesh.ops.reverse_faces(vis, faces=vis.faces)
    parts.add("driver_visor", vis, smooth=60)
    # visor pivot plates + screws, top vent, rear spoiler
    for side in (-1, 1):
        p0 = shell_point(c, side * r(76), r(-4), 1.045)
        n = (p0 - c).normalized()
        plate = lathe([(0.0001, 0.004), (0.020, 0.003), (0.024, 0.0)], 20)
        parts.add("black", transformed(plate, Matrix.Translation(p0 - n * 0.004) @ frame_y(n)), smooth=40)
        screw = lathe([(0.0001, 0.0065), (0.006, 0.005), (0.007, 0.0)], 12)
        parts.add("chrome", transformed(screw, Matrix.Translation(p0) @ frame_y(n)), smooth=40)
    top = shell_point(c, 0.0, r(52), 1.0)
    n = (top - c).normalized()
    vent = rounded_box((0.060, 0.040, 0.016), (0, 0, 0), 2, 0.4)
    parts.add("black", transformed(vent, Matrix.Translation(top) @ frame_z(n)), smooth=50)
    back = shell_point(c, math.pi, r(14), 1.0)
    n = (back - c).normalized()
    spoiler = rounded_box((0.016, 0.115, 0.034), (0, 0, 0), 2, 0.4)
    for v in spoiler.verts:
        if v.co.z > 0:
            v.co.x -= 0.012          # trailing lip
    parts.add("black", transformed(spoiler, Matrix.Translation(back + n * 0.006) @ frame_z(Vector((0, 0, 1)))), smooth=50)
    # neck roll along the lower edge
    loop = []
    for k in range(64):
        az = -math.pi + 2 * math.pi * k / 64
        el_min = r(-50) - r(17) * max(0.0, math.cos(az)) ** 1.5
        loop.append(shell_point(c, az, el_min, 0.95))
    roll = tube(loop + [loop[0]], [0.013] * 65, 10, cap=False)
    parts.add("black", roll, smooth=60)


def frame_y(n):
    """Rotation taking local +Y to n (for lathed discs)."""
    y = n.normalized()
    x = Vector((0, 0, 1)).cross(y)
    if x.length < 1e-6:
        x = Vector((1, 0, 0))
    x.normalize()
    z = x.cross(y)
    return Matrix((x, y, z)).transposed().to_4x4()


def frame_z(n):
    z = n.normalized()
    x = Vector((0, 1, 0)).cross(z).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_4x4()


def hans(parts, sh_c, hc):
    """HANS-style head restraint: a U yoke over the shoulders + a riser behind the neck + tethers."""
    lat = Vector((0, 1, 0))
    pts = []
    for k in range(17):
        t = -1 + 2 * k / 16                           # -1 .. 1 around the back of the neck
        ang = t * math.radians(100)
        p = sh_c + FWD * (0.02 + 0.075 * math.cos(ang) * -1 + 0.04 * (abs(t) ** 2)) \
            + lat * (0.115 * math.sin(ang)) + SPINE * (0.035 - 0.01 * abs(t))
        pts.append(p)
    yoke = tube(pts, [0.016] * len(pts), 10)
    for v in yoke.verts:                              # flatten into a strap-like collar
        rel = v.co - sh_c
        v.co = sh_c + rel - SPINE * (rel.dot(SPINE) - 0.035) * 0.55
    parts.add("black", yoke, smooth=50)
    riser = rounded_box((0.020, 0.085, 0.10), (0, 0, 0), 2, 0.4)
    rc = sh_c - FWD * 0.085 + SPINE * 0.09
    R = Matrix((FWD, lat, SPINE)).transposed().to_4x4()
    parts.add("black", transformed(riser, Matrix.Translation(rc) @ R), smooth=50)
    for side in (-1, 1):
        a = rc + SPINE * 0.04 + lat * side * 0.035
        b = hc + lat * side * 0.118 - FWD * 0.04 - SPINE * 0.03
        parts.add("black", tube([a, (a + b) * 0.5 - FWD * 0.01, b], [0.005] * 3, 6), smooth=50)


def build(parts):
    # torso + harness
    parts.add("driver_suit", torso(), smooth=60)
    sh_c = H(P0) + SPINE * 0.44
    for side in (-1, 1):
        # harness straps over the shoulders down to the lap (black)
        a = sh_c + Vector((0, side * 0.09, 0)) + FWD * 0.09 + SPINE * 0.03
        b = H(P0) + SPINE * 0.20 + FWD * 0.135 + Vector((0, side * 0.06, 0))
        cc = H(P0) + SPINE * 0.02 + FWD * 0.12 + Vector((0, side * 0.02, 0))
        parts.add("black", tube(bezier(a, (a + b) * 0.5 + FWD * 0.03, b, 8) + [cc], [0.012] * 9, 6), smooth=60)
    # neck (suit collar)
    parts.add("driver_suit", tube([sh_c + SPINE * 0.03, sh_c + SPINE * 0.08 + FWD * 0.01, sh_c + Vector((0.03, 0, 0.12))],
                                  [0.066, 0.056, 0.050], 18), smooth=60)
    # arms: shoulder -> elbow -> wrist, gloves on the rim at ten-to-two
    u_in = Vector((math.sin(WHEEL_TILT), 0, math.cos(WHEEL_TILT)))
    face = Vector((-math.cos(WHEEL_TILT), 0, math.sin(WHEEL_TILT)))
    for side in (-1, 1):
        shoulder = sh_c + Vector((0, side * 0.185, -0.02))
        parts.add("driver_suit", tube([shoulder - Vector((0, side * 0.06, -0.012)), shoulder - Vector((0, side * 0.02, 0)),
                                       shoulder + Vector((0, side * 0.012, -0.01))], [0.050, 0.066, 0.060], 18),
                  smooth=60)
        grip = H(WHEEL_C) + Vector((0, side * 0.160, 0)) + u_in * 0.090 + face * 0.018
        wrist = grip + face * 0.035 - Vector((0, side * 0.01, 0)) - u_in * 0.03
        elbow = two_bone(shoulder, wrist, 0.29, 0.27, Vector((0, side * 0.7, -0.7)))
        arm = [shoulder] + bezier(shoulder, (shoulder + elbow) * 0.5, elbow, 5)[1:] + \
            bezier(elbow, (elbow + wrist) * 0.5, wrist, 5)[1:]
        radii = [0.056, 0.054, 0.052, 0.050, 0.048, 0.046, 0.042, 0.037, 0.033]
        parts.add("driver_suit", tube(arm, radii, 18), smooth=60)
        # glove: a fist wrapped round the rim, with a cuff
        fist = rounded_box((0.075, 0.095, 0.09), (0, 0, 0), 2, 0.38)
        M = Matrix.Translation(grip) @ Matrix((face, Vector((0, 1, 0)), u_in)).transposed().to_4x4() \
            @ Matrix.Rotation(math.radians(side * 25), 4, "X")
        parts.add("black", transformed(fist, M), smooth=60)
        parts.add("black", tube([wrist + (wrist - elbow).normalized() * -0.02, wrist + (wrist - elbow).normalized() * 0.03],
                                [0.040, 0.040], 14), smooth=60)
    # legs: hip -> knee -> ankle, boots on the pedals (mostly hidden under the dash)
    for side in (-1, 1):
        hip = H(P0) + Vector((0.04, side * 0.095, -0.01))
        ankle = H(Vector((0.80, Y + side * 0.13, 0.355)))
        knee = two_bone(hip, ankle, 0.44, 0.43, Vector((0.2, side * 0.15, 1.0)))
        leg = [hip] + bezier(hip, (hip + knee) * 0.5, knee, 5)[1:] + bezier(knee, (knee + ankle) * 0.5, ankle, 5)[1:]
        parts.add("driver_suit", tube(leg, [0.082, 0.080, 0.074, 0.066, 0.058, 0.055, 0.050, 0.044, 0.040], 14),
                  smooth=60)
        boot = rounded_box((0.26, 0.09, 0.10), (0, 0, 0), 2, 0.4)
        R = Matrix.Rotation(math.radians(-35), 4, "Y")
        parts.add("black", transformed(boot, Matrix.Translation(ankle + Vector((0.07, 0, -0.02))) @ R), smooth=60)
    # helmet: looking ahead, slightly forward of the shoulders; HANS on the shoulders
    hc = sh_c + Vector((0.035, 0, 0.215))
    helmet(parts, hc)
    hans(parts, sh_c, hc)
