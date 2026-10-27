"""Hero geometry for the landmark porticos (round v2): MIT Building 10 on Killian Court, Lobby 7 at 77 Mass Ave,
Widener Library and Memorial Church's Widener porch on the Tercentenary Theatre.

The City's 3D models (CyberCity3D) have each colonnade as a solid slab in front of the building's wall, so the facade
shader painted windows on it. build_meshes.py calls apply() for the model: the slab's front and end walls are dropped
and replaced by generated meshes in the facade classes:
  - the columns: 24-sided shafts on square plinths with an echinus band and an abacus;
  - an entablature box over them (and a solid attic above it where the slab is taller);
  - the building's own wall, recessed behind (windows and doors from the facade shader);
  - optionally a podium with a flight of steps in front of it (Widener, Lobby 7).
Column counts: Building 10 has ten Ionic columns (MIT Technology Review, "The backstory of Killian Court"). The
Widener (12, Corinthian), Lobby 7 (6, Ionic) and Memorial Church (6, Doric) counts are NOT verified from a source:
change "columns" if needed.

Columns, entablature, podium and steps use the "stone" class with UV1.x (plane width) 0.3 m on the shafts, which the
shader treats as too narrow for windows, and UV2.x (plane bottom) above 1 m, so no ground-floor base course is
painted on them. Coordinates are the world frame's East/North metres (tools/mapgen/config.json), measured on the model.
"""
import numpy as np

HERO = {
    "668-10": {
        "name": "Building 10 portico (Killian Court)",
        "back": [(1017.5, -843.2), (1057.1, -825.1)],      # the building's wall line behind the portico
        "front": [(1018.9, -846.4), (1058.6, -828.3)],     # the slab's front face (entablature face)
        "z0": 0.2, "z_col": 18.6, "z_top": 21.3,
        "columns": 10, "diameter": 1.8, "end_margin": 2.6,
        "style": "limestone", "stone": "limestone",
    },
    "668-7": {
        "name": "Lobby 7 portico (77 Massachusetts Ave)",
        "back": [(916.3, -862.7), (926.4, -885.0)],
        "front": [(914.0, -863.7), (923.9, -886.2)],
        "base": 0.0, "z0": 1.6, "z_col": 16.5, "z_top": 20.0, "z_slab": 24.1,
        "steps": 8, "steps_inset": 3.0,                   # 8 x 0.2 m risers, 0.4 m treads: 3.2 m onto the plaza
        "columns": 6, "diameter": 1.7, "end_margin": 2.4,
        "style": "limestone", "stone": "limestone",
    },
    "318-24": {
        "name": "Widener Library colonnade (Tercentenary Theatre)",
        "back": [(-998.76, 758.55), (-959.86, 749.45)],     # the end pavilions' wall plane
        "front": [(-998.3, 760.5), (-959.4, 751.4)],        # the 2 m projecting centre
        "base": 0.3, "z0": 4.8, "z_col": 19.6, "z_top": 22.9,
        "steps": 24, "steps_inset": 4.0,                  # the great flight: 24 x 0.19 m, 8.6 m deep
        "columns": 12, "diameter": 1.5, "end_margin": 2.0,
        "style": "brick_georgian", "stone": "granite",
    },
    "318-13": {
        "name": "Memorial Church south (Widener) porch",   # Archipedia: "heavy Doric porches", one facing Widener
        "back": [(-963.55, 862.39), (-947.65, 858.69)],    # 4 m behind the porch front (the narthex stays solid)
        "front": [(-964.5, 858.4), (-948.6, 854.7)],
        "base": 0.0, "z0": 1.2, "z_col": 10.4, "z_top": 12.7,    # the pediment above 12.7 m is the model's own gable
        "steps": 6, "steps_inset": 1.5,
        "columns": 6, "diameter": 1.3, "end_margin": 1.6,
        "style": "brick_georgian", "stone": "white_trim",
    },
}


def _frame(h):
    b0, b1 = np.array(h["back"][0], float), np.array(h["back"][1], float)
    f0 = np.array(h["front"][0], float)
    t = (b1 - b0) / np.linalg.norm(b1 - b0)
    out = f0 - b0 - t * ((f0 - b0) @ t)            # back -> front offset (horizontal, perpendicular to the wall)
    return b0, b1, t, out, float(np.linalg.norm(out))


def _drop_mask(verts, faces, h):
    """Faces of the portico slab to drop: vertical faces between the back and front lines, below the slab top."""
    tri = verts[faces]
    c = tri.mean(1)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nz = np.abs(n[:, 2]) / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    b0, b1, t, out, depth = _frame(h)
    o = out / depth
    s = (c[:, :2] - b0) @ t
    d = (c[:, :2] - b0) @ o
    L = np.linalg.norm(b1 - b0)
    ztop = h.get("z_slab", h["z_top"])
    return (nz < 0.12) & (d > 0.3) & (d < depth + 0.3) & (s > -2.5) & (s < L + 2.5) & (c[:, 2] < ztop - 0.05)


def _quad(mb, p0, p1, z0, z1, normal, seed, pb=None, plane_w=None):
    """Vertical quad p0 -> p1 (u increasing from p0, which must be on the viewer's left seen from `normal`).
    plane_w: the plane width the shader fits bays to (UV1.x; default the quad's width, 0.3 = no windows)."""
    w = float(np.linalg.norm(np.subtract(p1, p0)))
    pos = [[p0[0], p0[1], z0], [p1[0], p1[1], z0], [p1[0], p1[1], z1], [p0[0], p0[1], z1]]
    mb.add(pos, [list(normal) + [0.0]] * 4, [[0, z0], [w, z0], [w, z1], [0, z1]], [[w if plane_w is None else plane_w, seed]] * 4,
           [[0, 1, 2], [0, 2, 3]], [[z0 if pb is None else pb, z1]] * 4)


def _ring(mb, corners, z0, z1, seed, pb):
    """Vertical sides of a CCW (from above) corner ring."""
    for k in range(len(corners)):
        p, q = corners[k], corners[(k + 1) % len(corners)]
        e = (q - p) / np.linalg.norm(q - p)
        _quad(mb, p, q, z0, z1, np.array([e[1], -e[0]]), seed, pb)   # right-hand normal of a CCW ring = outward


def _flat(roofs, corners, z, seed, up=True):
    pos = [[p[0], p[1], z] for p in corners]
    f = [[0, 1, 2], [0, 2, 3]] if up else [[0, 2, 1], [0, 3, 2]]
    roofs.add(pos, [[0, 0, 1.0 if up else -1.0]] * 4, [p[:2] for p in pos], [[0.0, seed]] * 4, f)


def _box_corners(c, half_t, half_o, t):
    """CCW (from above) corners of a box centred at c, half sizes along t and along t's left normal."""
    t = np.asarray(t, float)
    o = np.array([-t[1], t[0]])
    c = np.asarray(c, float)
    return [c - t * half_t - o * half_o, c + t * half_t - o * half_o, c + t * half_t + o * half_o, c - t * half_t + o * half_o]


def _column(mb, centre, r, z0, z1, seed, seg=24):
    """Smooth-shaded cylinder: UV0 = (metres round the shaft, height), narrow UV1.x so no windows."""
    a = np.linspace(0.0, 2.0 * np.pi, seg + 1)
    ring = np.column_stack([np.cos(a), np.sin(a)])
    pos, nrm, uv0 = [], [], []
    for k in range(seg + 1):
        x, y = centre[0] + r * ring[k, 0], centre[1] + r * ring[k, 1]
        u = a[k] * r                                    # counter-clockwise from above = left-to-right from outside
        pos += [[x, y, z0], [x, y, z1]]
        nrm += [[ring[k, 0], ring[k, 1], 0.0]] * 2
        uv0 += [[u, z0], [u, z1]]
    faces = []
    for k in range(seg):
        i = 2 * k
        faces += [[i, i + 2, i + 3], [i, i + 3, i + 1]]
    n = len(pos)
    mb.add(pos, nrm, uv0, [[0.3, seed]] * n, faces, [[1.5, z1]] * n)


def apply(building_id, verts, faces, walls_by_style, roofs, seed):
    """Returns the model's faces with the portico slab removed (or the input faces) and adds the hero meshes."""
    h = HERO.get(building_id)
    if h is None:
        return faces
    keep = ~_drop_mask(verts, faces, h)
    wall_mb = walls_by_style[h["style"]]
    st = walls_by_style[h.get("stone", h["style"])]
    b0, b1, t, out, depth = _frame(h)
    nrm = out / depth                                  # the portico faces this way
    L = float(np.linalg.norm(b1 - b0))
    # u runs left -> right seen from outside: start each quad from the end on the viewer's left
    left_is_0 = (np.array([-nrm[1], nrm[0]]) @ t) > 0
    p0, p1 = (b0, b1) if left_is_0 else (b1, b0)
    q0, q1 = p0 + out, p1 + out
    base = h.get("base", h["z0"])
    z0, zc, zt = h["z0"], h["z_col"], h["z_top"]
    zs = h.get("z_slab", zt)
    centre_line = (b0 + b1) / 2.0 + out / 2.0
    # recessed wall of the building behind the columns (windows / doors from the shader)
    _quad(wall_mb, p0, p1, z0, zc, nrm, seed)
    # entablature (+ solid attic): front face, end faces, soffit (narrow plane width: no windows fitted)
    _quad(st, q0, q1, zc, zs, nrm, seed, plane_w=0.3)
    for a, b in ((p0, q0), (q1, p1)):
        e = (b - a) / np.linalg.norm(b - a)
        _quad(st, a, b, zc, zs, np.array([e[1], -e[0]]), seed, plane_w=0.3)
    _flat(roofs, _box_corners(centre_line, L / 2.0, depth / 2.0, t), zc, seed, up=False)
    # podium under the colonnade (its top is the portico floor) and the flight of steps in front of it
    if z0 > base + 0.05:
        _ring(st, _box_corners(centre_line, L / 2.0, depth / 2.0, t), base, z0, seed, 1.5)
        _flat(roofs, _box_corners(centre_line, L / 2.0, depth / 2.0, t), z0, seed)
        n_st = int(h.get("steps", 0))
        if n_st:
            rise, tread = (z0 - base) / n_st, (0.36 if n_st > 12 else 0.4)
            half_w = L / 2.0 - h.get("steps_inset", 0.0)
            front_c = (b0 + b1) / 2.0 + out             # centre of the podium's front edge
            for k in range(n_st):
                # step k (0 = top, at the portico floor): its tread runs from k to k+1 treads beyond the podium,
                # its riser at the outer edge goes down to the next step (the last one to the ground)
                zk = z0 - k * rise
                d0, d1 = k * tread, (k + 1) * tread
                cor = _box_corners(front_c + nrm * (d0 + d1) / 2.0, half_w, (d1 - d0) / 2.0, t)
                _flat(roofs, cor, zk, seed)
                e = front_c + nrm * d1
                _quad_auto(st, e - t * half_w, e + t * half_w, zk - rise, zk, nrm, seed)
                for sgn in (-1.0, 1.0):                  # stepped cheek walls at both ends of the flight
                    a = front_c + t * (sgn * half_w) + nrm * d0
                    _quad_auto(st, a, a + nrm * tread, base, zk, t * sgn, seed)
    # columns on plinths, with an echinus band and an abacus
    r = h["diameter"] / 2.0
    line0 = b0 + out - nrm * (r + 0.35)
    n = h["columns"]
    for k in range(n):
        c = line0 + t * (h["end_margin"] + k * (L - 2 * h["end_margin"]) / (n - 1))
        _ring(st, _box_corners(c, r * 1.3, r * 1.3, t), z0, z0 + 0.9, seed, 1.5)       # plinth
        _flat(roofs, _box_corners(c, r * 1.3, r * 1.3, t), z0 + 0.9, seed)
        _column(st, c, r * 0.92, z0 + 0.9, zc - 0.7, seed)            # shaft
        _column(st, c, r * 1.02, zc - 0.7, zc - 0.45, seed)           # echinus / volute band
        _ring(st, _box_corners(c, r * 1.25, r * 1.25, t), zc - 0.45, zc, seed, 1.5)   # abacus
        _flat(roofs, _box_corners(c, r * 1.25, r * 1.25, t), zc - 0.45, seed, up=False)
    return faces[keep]


def _quad_auto(mb, a, b, z0, z1, normal, seed, pb=1.5):
    """Vertical quad between a and b facing `normal`, ordered so u runs left -> right seen from outside."""
    normal = np.asarray(normal, float)
    right = np.array([-normal[1], normal[0]])
    if (np.asarray(b) - np.asarray(a)) @ right < 0:
        a, b = b, a
    _quad(mb, a, b, z0, z1, normal, seed, pb)
