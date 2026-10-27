"""Simple dark interior, visible through the glass: inner liner (door cards, pillars, headliner), floor,
dashboard with the instrument binnacle, right-hand-drive steering wheel, bucket seats, rear bench, console,
parcel shelf. All in the 'interior' part."""
import math

import bmesh
from mathutils import Matrix, Vector

from sti_common import G, grid_surface, lathe, merge, rounded_box, subsurf_bm, transformed

DRIVER_Y = -0.37      # JDM car: right-hand drive


def liner(src_bm):
    """Inward offset copy of the cabin skin (non-glass faces), facing inward."""
    zl = src_bm.faces.layers.int.get("zone")
    b = src_bm.copy()
    zl2 = b.faces.layers.int.get("zone")
    keep = []
    for f in b.faces:
        c = f.calc_center_median()
        if f[zl2] == 1:
            continue
        if not (-1.66 < c.x < 0.98 and c.z > 0.30 + G and abs(c.y) < 0.95):
            continue
        # only the cabin: above the belt in front/behind the doors, everything between the A and C pillars
        if (c.x > 0.90 or c.x < -1.45) and c.z < 0.95 + G:
            continue
        # never in front of the wheels (this skin is not cut at the arches)
        if any(math.hypot(c.x - xa, c.z - (0.231 + 0.012)) < 0.44 for xa in (1.2915, -1.2335)):
            continue
        keep.append(f)
    bmesh.ops.delete(b, geom=[f for f in b.faces if f not in set(keep)], context="FACES")
    b.normal_update()
    for v in b.verts:
        v.co -= v.normal * 0.03
    bmesh.ops.reverse_faces(b, faces=b.faces)
    return b


def _bump(a, inner, peak, outer):
    """0 inside `inner`, rising to 1 at `peak`, back to 0.3 at `outer` (bolster cross-section)."""
    if a <= inner:
        return 0.0
    if a <= peak:
        t = (a - inner) / (peak - inner)
        return t * t * (3 - 2 * t)
    t = min(1.0, (a - peak) / max(outer - peak, 1e-6))
    return 1.0 - 0.7 * t * t


def _loft_closed(rows):
    """Loft of closed section loops (list of lists of Vector) with both ends capped -> bmesh."""
    bm = grid_surface(rows, closed_v=True)
    for r in (rows[0], rows[-1]):
        bm.faces.new([bm.verts.new(p) for p in r])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def seat(width=0.50, front=True):
    """Sport bucket seat at the origin (seat H-point region), facing +x: lofted cushion and backrest with real side
    bolsters (thigh and torso), the backrest's bolsters fading out over the shoulders, a separate headrest on
    posts (front seats) / two headrests (rear bench). Same envelope as the old box seat (the driver fits)."""
    W = width / 2
    ny = 13
    ys = [-W + 2 * W * j / (ny - 1) for j in range(ny)]
    bm = bmesh.new()
    # cushion: stations along x (rear -> front), section across y: top surface with bolsters, flat bottom
    rows = []
    nx = 9
    for i in range(nx):
        u = i / (nx - 1)
        x = -0.19 + 0.49 * u
        end = math.sin(math.pi * min(u, 1 - u) / 0.24 * 0.5) if min(u, 1 - u) < 0.12 else 1.0  # round the ends
        thigh = 0.018 * max(0.0, (u - 0.55) / 0.45) ** 1.5
        row = []
        for y in ys:
            z = 0.035 + thigh + 0.075 * _bump(abs(y), 0.56 * W, 0.84 * W, W) * (1 if front else 0.45)
            row.append(Vector((x, y * (0.85 + 0.15 * end), -0.05 + (z + 0.05) * end)))
        row += [Vector((x, W * (0.85 + 0.15 * end), -0.05)), Vector((x, -W * (0.85 + 0.15 * end), -0.05))]
        rows.append(row)
    merge(bm, subsurf_bm(_loft_closed(rows), 2))
    # backrest: stations up the back (local z), section across y in depth x: bolsters wrap forward
    back_rows = []
    nz = 10
    for i in range(nz):
        u = i / (nz - 1)
        z = 0.02 + 0.60 * u
        end = 1.0 if 0.06 < u < 0.94 else math.sin(0.5 * math.pi * min(u, 1 - u) / 0.06)
        Wz = W * (1 - 0.14 * u)
        bol = (1 - 0.75 * max(0.0, (u - 0.62) / 0.38)) * (1 if front else 0.4)
        row = []
        for y in ys:
            yy = y * (1 - 0.14 * u)
            xf = 0.050 + 0.085 * bol * _bump(abs(yy), 0.56 * Wz, 0.86 * Wz, Wz)
            row.append(Vector((-0.055 + (xf + 0.055) * max(end, 0.15), yy, z)))
        row += [Vector((-0.055, Wz, z)), Vector((-0.055, -Wz, z))]
        back_rows.append(row)
    back = subsurf_bm(_loft_closed(back_rows), 2)
    if front:
        merge(back, rounded_box((0.10, 0.25, 0.16), (0.005, 0, 0.73), 1, 0.4))
        for yp in (-0.07, 0.07):                     # headrest posts
            merge(back, rounded_box((0.010, 0.010, 0.09), (0.0, yp, 0.645), 1, 0.4))
    else:
        for yh in (-0.24, 0.24):
            merge(back, rounded_box((0.08, 0.20, 0.13), (0.0, yh, 0.70), 1, 0.4))
    transformed(back, Matrix.Translation((-0.20, 0, 0.02)) @ Matrix.Rotation(math.radians(-18), 4, "Y"))
    merge(bm, back)
    return bm


def steering_wheel():
    bm = bmesh.new()
    R, r = 0.182, 0.0185
    # rim: torus (slightly oval grip section) via lathe about Y; the wheel plane faces the driver after the transform
    tor = lathe([(R + 1.15 * r * math.cos(a), r * math.sin(a)) for a in [2 * math.pi * k / 14 for k in range(15)]], 64)
    merge(bm, tor)
    # airbag hub: a padded boss
    merge(bm, lathe([(0.0001, 0.034), (0.045, 0.032), (0.068, 0.024), (0.076, 0.010), (0.074, -0.004),
                     (0.0001, -0.012)], 40))
    for a in (0, 180, 270):
        aa = math.radians(a)
        sp = rounded_box((0.13, 0.016, 0.045), (0, 0, 0), 1, 0.4)
        transformed(sp, Matrix.Rotation(-aa, 4, "Y") @ Matrix.Translation((0.11, 0.0, 0)))
        merge(bm, sp)
    col = lathe([(0.03, 0.0), (0.035, -0.35), (0.0001, -0.35)], 16)
    merge(bm, col)
    return bm


def dashboard():
    rows = []
    for k in range(29):
        y = -0.70 + 1.40 * k / 28
        hump = 0.055 * math.exp(-((y - DRIVER_Y) / 0.16) ** 2)
        w = 1 - (abs(y) / 0.74) ** 6
        sec = [(0.93, 0.955), (0.80, 0.985), (0.66, 1.0 + hump), (0.58, 0.99 + hump), (0.53, 0.93), (0.52, 0.80),
               (0.56, 0.62), (0.70, 0.50)]
        rows.append([Vector((x, y, h * w + (1 - w) * 0.80 + G)) for x, h in sec])
    return subsurf_bm(grid_surface(rows), 1)


def binnacle(parts):
    """Instrument binnacle in front of the (RHD) driver: a hood lip over the gauge face, two dials with chrome
    bezels (they catch the light through the windshield)."""
    rows = []
    for k in range(13):
        y = DRIVER_Y - 0.15 + 0.30 * k / 12
        hump = 0.055 * math.exp(-((y - DRIVER_Y) / 0.16) ** 2)
        rows.append([Vector((0.60, y, 0.993 + hump + G)), Vector((0.556, y, 0.998 + hump + G)),
                     Vector((0.548, y, 0.986 + hump + G)), Vector((0.556, y, 0.982 + hump + G))])
    lip = grid_surface(rows)
    lip.normal_update()
    if sum(f.normal.z for f in lip.faces) < 0:
        bmesh.ops.reverse_faces(lip, faces=lip.faces)
    parts.add("interior", lip, smooth=50)
    n = Vector((-0.92, 0.0, 0.40)).normalized()
    from sti_details import frame
    for dy in (-0.066, 0.066):
        c = Vector((0.551, DRIVER_Y + dy, 0.982 + G))
        M = Matrix.Translation(c) @ frame(n)
        parts.add("interior", transformed(lathe([(0.0001, -0.004), (0.040, -0.004), (0.040, -0.012)], 32), M),
                  smooth=30)
        parts.add("chrome", transformed(lathe([(0.044, -0.006), (0.044, 0.001), (0.0395, 0.002), (0.0395, -0.004)], 32),
                                        M), smooth=30)


def build(parts, src_bm):
    parts.add("interior", liner(src_bm), smooth=50)
    # floor + firewall + parcel shelf + rear bulkhead
    fl = bmesh.new()
    pts = [(0.92, -0.70), (0.92, 0.70), (-1.20, 0.72), (-1.20, -0.72)]
    fl.faces.new([fl.verts.new((x, y, 0.30 + G)) for x, y in pts])
    parts.add("interior", fl)
    shelf = bmesh.new()
    pts = [(-1.30, -0.70, 1.00), (-1.30, 0.70, 1.00), (-1.62, 0.66, 1.045), (-1.62, -0.66, 1.045)]
    f = shelf.faces.new([shelf.verts.new((x, y, h + G)) for x, y, h in pts])
    f.normal_update()             # (a new face's normal is not computed yet)
    if f.normal.z < 0:
        f.normal_flip()
    parts.add("interior", shelf)
    parts.add("interior", dashboard(), smooth=50)
    binnacle(parts)
    # gauges: two dark rings in the binnacle face are implied; steering wheel (RHD)
    sw = steering_wheel()
    M = Matrix.Translation((0.40, DRIVER_Y, 0.90 + G)) @ Matrix.Rotation(math.radians(24), 4, "Y") \
        @ Matrix.Rotation(math.radians(90), 4, "Z")
    parts.add("interior", transformed(sw, M), smooth=40)
    for y in (-0.37, 0.37):
        # driver's bucket (RHD, y < 0) sits 4 cm lower and 5 cm further forward than the passenger seat
        x0, h0 = (0.07, 0.43) if y < 0 else (0.02, 0.47)
        parts.add("interior", transformed(seat(), Matrix.Translation((x0, y, h0 + G))), smooth=50)
    rear = seat(0.92, front=False)      # between the rear wheel wells (inner walls at |y| = 0.43)
    parts.add("interior", transformed(rear, Matrix.Translation((-0.82, 0.0, 0.47 + G))
                                      @ Matrix.Rotation(math.radians(-6), 4, "Y")), smooth=50)
    # centre console with the shifter and handbrake
    parts.add("interior", rounded_box((0.62, 0.20, 0.16), (0.30, 0.0, 0.40 + G), 1, 0.3), smooth=50)
    parts.add("interior", rounded_box((0.06, 0.018, 0.18), (0.38, 0.0, 0.54 + G), 1, 0.45), smooth=50)
    parts.add("interior", rounded_box((0.07, 0.05, 0.05), (0.38, 0.0, 0.64 + G), 1, 0.45), smooth=50)
    parts.add("interior", rounded_box((0.26, 0.035, 0.035), (0.05, -0.02, 0.50 + G), 1, 0.45), smooth=50)
