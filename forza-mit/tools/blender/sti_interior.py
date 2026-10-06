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


def seat(width=0.50, front=True):
    """Bucket seat at the origin (seat H-point region), facing +x."""
    bm = bmesh.new()
    # cushion with side bolsters
    cush = rounded_box((0.50, width * 0.62, 0.10), (0.06, 0, 0.0), 1, 0.3)
    merge(bm, cush)
    for s in (-1, 1):
        merge(bm, rounded_box((0.48, 0.10, 0.15), (0.06, s * width * 0.40, 0.03), 1, 0.4))
    # backrest (reclined ~20 deg) with bolsters and a headrest
    back = bmesh.new()
    merge(back, rounded_box((0.11, width * 0.62, 0.62), (0, 0, 0.31), 1, 0.3))
    for s in (-1, 1):
        merge(back, rounded_box((0.16, 0.11, 0.58), (0.02, s * width * 0.40, 0.29), 1, 0.4))
    merge(back, rounded_box((0.10, 0.26, 0.17), (0.0, 0, 0.72), 1, 0.4) if front else rounded_box((0.01, 0.01, 0.01)))
    transformed(back, Matrix.Translation((-0.20, 0, 0.02)) @ Matrix.Rotation(math.radians(-18), 4, "Y"))
    merge(bm, back)
    return bm


def steering_wheel():
    bm = bmesh.new()
    R, r = 0.185, 0.016
    ring = bmesh.new()
    res = bmesh.ops.create_circle(ring, segments=48, radius=R)
    # torus via lathe of a small circle around Y, then rotate so the wheel plane faces the driver
    tor = lathe([(R + r * math.cos(a), r * math.sin(a)) for a in [2 * math.pi * k / 12 for k in range(13)]], 48)
    ring.free()
    merge(bm, tor)
    merge(bm, lathe([(0.0001, 0.02), (0.06, 0.018), (0.065, 0.0), (0.0001, -0.01)], 32))
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
    if f.normal.z < 0:
        f.normal_flip()
    parts.add("interior", shelf)
    parts.add("interior", dashboard(), smooth=50)
    # gauges: two dark rings in the binnacle face are implied; steering wheel (RHD)
    sw = steering_wheel()
    M = Matrix.Translation((0.40, DRIVER_Y, 0.90 + G)) @ Matrix.Rotation(math.radians(24), 4, "Y") \
        @ Matrix.Rotation(math.radians(90), 4, "Z")
    parts.add("interior", transformed(sw, M), smooth=40)
    for y in (-0.37, 0.37):
        # driver's bucket (RHD, y < 0) sits 4 cm lower and 5 cm further forward than the passenger seat
        x0, h0 = (0.07, 0.43) if y < 0 else (0.02, 0.47)
        parts.add("interior", transformed(seat(), Matrix.Translation((x0, y, h0 + G))), smooth=50)
    rear = seat(1.30, front=False)
    parts.add("interior", transformed(rear, Matrix.Translation((-0.82, 0.0, 0.47 + G))
                                      @ Matrix.Rotation(math.radians(-6), 4, "Y")), smooth=50)
    # centre console with the shifter and handbrake
    parts.add("interior", rounded_box((0.62, 0.20, 0.16), (0.30, 0.0, 0.40 + G), 1, 0.3), smooth=50)
    parts.add("interior", rounded_box((0.06, 0.018, 0.18), (0.38, 0.0, 0.54 + G), 1, 0.45), smooth=50)
    parts.add("interior", rounded_box((0.07, 0.05, 0.05), (0.38, 0.0, 0.64 + G), 1, 0.45), smooth=50)
    parts.add("interior", rounded_box((0.26, 0.035, 0.035), (0.05, -0.02, 0.50 + G), 1, 0.45), smooth=50)
