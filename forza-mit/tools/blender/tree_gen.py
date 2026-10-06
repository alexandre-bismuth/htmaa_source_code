"""Procedural street-tree generator (pure numpy, no bpy): skeleton growth, bark tubes, leaf geometry.

Model (sapling / Weber-Penn style, with a crown envelope):
  level 0  trunk (or several stems), optionally forking into co-dominant leaders at its top
  level 1  scaffold limbs (spiral along the trunk) / leaders (fork)
  level 2  branches, sprayed roughly in the horizontal plane of their parent
  level 3  twigs; they and the outer part of level-2 branches carry the leaves
Every level >= 1 grows step by step with wobble + tropism and stops when it leaves the species'
crown envelope (a height profile of radii with low-frequency lumps), so the silhouette is per species.

Leaves are real opaque polygons (4-10 triangles each, species outline), placed along twigs in
alternate/opposite/spur patterns, facing up/outward, with a midrib fold and a droop along the blade.
Everything is returned as numpy arrays; build_trees.py turns them into a Blender mesh.
"""
import math

import numpy as np

UP = np.array([0.0, 0.0, 1.0])


def unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-9)


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ---------------------------------------------------------------------------------------------
class Envelope:
    """Crown volume: radius profile r(h) (h = 0 at crown base, 1 at top) with random lumps."""

    def __init__(self, sp, rng):
        self.H = sp["height"]
        self.zb = sp["crown_base"]
        self.R = sp["crown_radius"]
        prof = np.array(sp["envelope"], dtype=np.float64)
        self.ph, self.pr = prof[:, 0], prof[:, 1]
        self.cx, self.cy = sp.get("crown_offset", (0.0, 0.0))
        amp = sp.get("lumpiness", 0.14)
        k = 7
        self.lump_m = rng.integers(1, 5, k)                  # around (angular harmonics)
        self.lump_n = rng.uniform(0.5, 3.0, k)               # along height
        self.lump_p = rng.uniform(0, 2 * math.pi, (k, 2))
        self.lump_a = rng.uniform(0.4, 1.0, k)
        self.lump_a *= amp / self.lump_a.sum() * 2.0

    def hfrac(self, z):
        return (z - self.zb) / (self.H - self.zb)

    def rmax(self, x, y, z):
        h = self.hfrac(z)
        ang = np.arctan2(y - self.cy, x - self.cx)
        base = np.interp(h, self.ph, self.pr, left=self.pr[0], right=0.0) * self.R
        lump = 1.0
        for m, n, p, a in zip(self.lump_m, self.lump_n, self.lump_p, self.lump_a):
            lump = lump + a * np.cos(m * ang + p[0]) * np.cos(n * math.pi * h + p[1])
        return base * lump

    def rho(self, x, y):
        return np.hypot(x - self.cx, y - self.cy)

    def inside(self, p, tol=1.0):
        x, y, z = p
        if z > self.H * (0.97 + 0.05 * tol):
            return False
        if z < self.zb - 0.5:
            return self.rho(x, y) < 0.35 * self.R * tol
        return self.rho(x, y) <= self.rmax(x, y, z) * tol

    def depth(self, P):
        """Approximate depth (m) of points below the crown surface (horizontal and from the top)."""
        x, y, z = P[:, 0], P[:, 1], P[:, 2]
        rm = self.rmax(x, y, z)
        dh = rm - self.rho(x, y)
        # distance below the top surface: find height where profile radius = rho (cheap approx)
        dz = (self.H - z) * np.clip(1.0 - self.rho(x, y) / np.maximum(rm, 1e-3), 0, 1)
        return np.maximum(np.minimum(dh, dz + 0.5 * dh), 0.0)


# ---------------------------------------------------------------------------------------------
class Branch:
    __slots__ = ("pts", "rad", "level", "s", "length", "ku", "v0", "children", "parent_t", "stem")

    def __init__(self, pts, rad, level):
        self.pts = np.asarray(pts, dtype=np.float64)
        self.rad = np.asarray(rad, dtype=np.float64)
        self.level = level
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        self.s = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = self.s[-1]
        self.children = 0
        self.stem = False

    def at(self, t):
        """Point, tangent and radius at arc fraction t."""
        s = t * self.length
        i = int(np.clip(np.searchsorted(self.s, s) - 1, 0, len(self.s) - 2))
        f = (s - self.s[i]) / max(self.s[i + 1] - self.s[i], 1e-9)
        p = self.pts[i] * (1 - f) + self.pts[i + 1] * f
        d = unit(self.pts[i + 1] - self.pts[i])
        r = self.rad[i] * (1 - f) + self.rad[i + 1] * f
        return p, d, r


def perp_basis(t):
    a = np.cross(t, UP)
    if np.linalg.norm(a) < 1e-4:
        a = np.cross(t, np.array([1.0, 0.0, 0.0]))
    a = unit(a)
    b = np.cross(t, a)
    return a, b


class TreeGen:
    def __init__(self, sp, seed):
        self.sp = sp
        self.rng = np.random.default_rng(seed)
        self.env = Envelope(sp, self.rng)
        self.branches = []

    # ---- growth --------------------------------------------------------------------------
    def grow(self, start, d, length, r0, level, check_env=True, trop=None, r_end_frac=None):
        sp, rng, L = self.sp, self.rng, self.sp["levels"][level]
        seg = L["seg"]
        n = max(2, int(math.ceil(length / seg)))
        step = length / n
        trop = L["tropism"] if trop is None else trop
        wob = L["wobble"]
        droop = L.get("droop", 0.0)          # gravity bend that grows along the branch
        tol = rng.uniform(*sp.get("env_tol", (0.88, 1.08)))
        pts = [np.asarray(start, dtype=np.float64)]
        d = unit(np.asarray(d, dtype=np.float64))
        p = pts[0].copy()
        for i in range(n):
            f = (i + 0.5) / n
            w = rng.normal(size=3) * wob
            d = unit(d + w - (w @ d) * d)
            d = unit(d + UP * (trop * step) - UP * (droop * f * step))
            q = p + d * step
            if q[2] < sp.get("min_branch_z", 0.3) and level > 0:
                d[2] = abs(d[2]) * 0.5 + 0.05
                d = unit(d)
                q = p + d * step
            if check_env and level > 0 and i > 0 and not self.env.inside(q, tol):
                break
            if level > 0 and i > 0 and (self.env.rho(q[0], q[1]) > 1.12 * self.env.R or q[2] > 1.02 * self.env.H):
                break
            p = q
            pts.append(p.copy())
        pts = np.array(pts)
        seglen = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seglen)])
        Lact = max(s[-1], 1e-6)
        tip = max(sp["tip_radius"], r0 * (L.get("tip_frac", 0.18) if r_end_frac is None else r_end_frac))
        tip = min(tip, r0)
        u = s / Lact
        rad = r0 + (tip - r0) * u ** L.get("taper_pow", 1.0)
        b = Branch(pts, rad, level)
        self.branches.append(b)
        return b

    def reach(self, p, d, step=0.25, maxd=25.0):
        """Distance from p along d (bent by the level-1 tropism a little) to the crown surface."""
        q = np.array(p, dtype=np.float64)
        s = 0.0
        while s < maxd:
            q = q + d * step
            s += step
            if q[2] > self.env.zb - 0.5 and not self.env.inside(q, 1.0):
                break
        return s

    def spawn_children(self, parent, level):
        """Grow level-`level` children on `parent` and recurse."""
        sp, rng, env = self.sp, self.rng, self.env
        if level >= len(sp["levels"]):
            return
        L = sp["levels"][level]
        if parent.length < 0.05:
            return
        t0, t1 = L.get("range", (0.15, 1.0))
        if parent.level == 0 and level == 1:
            # limbs start at the first-branch height
            z0 = sp["first_branch"]
            ts = parent.s / parent.length
            zs = parent.pts[:, 2]
            ok = np.nonzero(zs >= z0)[0]
            if len(ok) == 0:
                return
            t0 = max(t0, ts[ok[0]])
        span = max(t1 - t0, 0.0) * parent.length
        count = L["per_m"] * span
        count = int(count) + (rng.random() < count - int(count))
        if level == 1 and parent.level == 0:
            count = int(L.get("count", count) * (parent.length / max(sp.get("trunk_len_ref", parent.length), 1e-6)))
            count = max(count, L.get("min_count", 0))
        if count <= 0:
            return
        ts = np.sort(t0 + (t1 - t0) * (np.arange(count) + rng.uniform(0.15, 0.85, count)) / count)
        phyl = rng.uniform(0, 2 * math.pi)
        side = 1.0 if rng.random() < 0.5 else -1.0
        for k, t in enumerate(ts):
            p, T, rp = parent.at(t)
            if L.get("leafy") and p[2] < sp["min_leaf_z"] - 0.3:
                continue
            # angle from parent axis, interpolated along the parent (e.g. drooping low limbs)
            a_lo, a_hi = L["angle"]
            ang = math.radians(a_lo + (a_hi - a_lo) * t + rng.normal() * L.get("angle_sd", 8.0))
            if parent.level == 0:
                phyl += math.radians(L.get("phyllo", 137.5)) + rng.normal() * 0.35
                a, b = perp_basis(T)
                radial = math.cos(phyl) * a + math.sin(phyl) * b
            else:
                # spray children left/right of the parent, biased toward the horizontal plane
                side = -side if L.get("alternate", True) else (1.0 if rng.random() < 0.5 else -1.0)
                sv = np.cross(T, UP)
                if np.linalg.norm(sv) < 1e-3:
                    sv, _ = perp_basis(T)
                sv = unit(sv)
                upv = unit(np.cross(sv, T))
                psi = math.radians(L.get("roll_bias", 15.0) + rng.normal() * L.get("roll_sd", 35.0))
                radial = side * math.cos(psi) * sv + math.sin(psi) * upv
            d = unit(math.cos(ang) * T + math.sin(ang) * radial)
            # length
            if L.get("length_mode") == "reach":
                length = L["length"] * self.reach(p, d) * rng.uniform(0.8, 1.05)
                length *= (1.0 - L.get("top_shrink", 0.0) * t)
            elif L.get("length_mode") == "envelope":
                rm = env.rmax(p[0], p[1], max(p[2], env.zb + 0.2))
                length = L["length"] * max(rm, 0.25 * env.R) * rng.uniform(0.8, 1.15)
                length *= (1.0 - L.get("top_shrink", 0.0) * t)
            elif L.get("length_mode") == "abs":
                length = rng.uniform(*L["length"])
            else:
                rest = parent.length * (1 - t)
                length = L["length"] * rest * rng.uniform(0.7, 1.05)
            length = float(np.clip(length, *L.get("length_clip", (0.15, 99.0))))
            r0 = rp * L["radius_ratio"] * rng.uniform(0.85, 1.05)
            r0 = float(np.clip(r0, sp["tip_radius"], 0.85 * rp))
            # interior culling of twigs (shade-free crowns are hollow)
            if L.get("leafy"):
                dep = float(env.depth(p[None, :])[0])
                if dep > sp["shell"] and rng.random() < sp.get("interior_cull", 0.8):
                    continue
            start = p - T * 0.0 + d * min(rp * 0.3, 0.02)
            c = self.grow(start, d, length, r0, level)
            parent.children += 1
            self.spawn_children(c, level + 1)

    def build(self):
        sp, rng = self.sp, self.rng
        stems = sp.get("stems", 1)
        trunk_len = sp["trunk_frac"] * sp["height"]
        sp["trunk_len_ref"] = trunk_len
        for k in range(stems):
            if stems == 1:
                d = unit(np.array([rng.normal() * 0.03, rng.normal() * 0.03, 1.0]))
                base = np.array([0.0, 0.0, -0.15])
                r0 = sp["trunk_radius"]
            else:
                phi = 2 * math.pi * k / stems + rng.normal() * 0.3
                lean = math.radians(sp.get("stem_lean", 12.0) * rng.uniform(0.7, 1.3))
                d = np.array([math.sin(lean) * math.cos(phi), math.sin(lean) * math.sin(phi), math.cos(lean)])
                off = sp.get("stem_offset", 0.06)
                base = np.array([off * math.cos(phi), off * math.sin(phi), -0.15])
                r0 = sp["trunk_radius"] * rng.uniform(0.8, 1.0)
            tl = trunk_len * (rng.uniform(0.85, 1.0) if stems > 1 else 1.0)
            top = sp.get("trunk_top_frac", 0.7 if sp.get("fork", 0) else 0.04)
            trunk = self.grow(base, d, tl, r0, 0, check_env=False, r_end_frac=top)
            trunk.stem = True
            # co-dominant leaders at the trunk top (vase / decurrent crowns)
            nf = sp.get("fork", 0)
            if nf:
                p, T, rp = trunk.at(1.0)
                phi0 = rng.uniform(0, 2 * math.pi)
                for j in range(nf):
                    phi = phi0 + 2 * math.pi * j / nf + rng.normal() * 0.25
                    a, b = perp_basis(T)
                    ang = math.radians(sp["fork_angle"] * rng.uniform(0.8, 1.2))
                    dd = unit(math.cos(ang) * T + math.sin(ang) * (math.cos(phi) * a + math.sin(phi) * b))
                    ll = (sp["height"] - p[2]) * sp.get("fork_len", 0.85) / max(math.cos(ang), 0.4)
                    ll *= rng.uniform(0.85, 1.05)
                    rr = rp * sp.get("fork_radius", 0.75) * rng.uniform(0.9, 1.05)
                    c = self.grow(p - T * rp * 0.5, dd, ll, rr, 1, check_env=False,
                                  trop=sp.get("fork_tropism", None))
                    self.spawn_children(c, 2)
            self.spawn_children(trunk, 1)
        return self


# ---------------------------------------------------------------------------------------------
def tube_mesh(branches, sp, bark_size, rng):
    """Bark tubes for all branches. Returns dict of arrays (verts, tris, uv, normals, ao)."""
    V, F, UV, N, A = [], [], [], [], []   # A: per-vertex branch radius
    nv = 0
    su, sv = bark_size
    env_flare = sp.get("flare", 0.35)
    lobes = sp.get("buttress_lobes", 5)
    for b in branches:
        P, R = b.pts, b.rad
        m = len(P)
        if m < 2:
            continue
        T = np.zeros_like(P)
        T[1:-1] = P[2:] - P[:-2]
        T[0] = P[1] - P[0]
        T[-1] = P[-1] - P[-2]
        T = unit(T)
        r0 = R[0]
        S = int(np.clip(round(2 * math.pi * r0 / sp.get("bark_edge", 0.045)), 3, 24))
        if r0 < 0.006:
            S = 3
        # parallel-transport frames
        nrm = np.zeros_like(P)
        a, _ = perp_basis(T[0])
        nrm[0] = a
        for i in range(1, m):
            v = nrm[i - 1] - (nrm[i - 1] @ T[i]) * T[i]
            nrm[i] = unit(v) if np.linalg.norm(v) > 1e-6 else perp_basis(T[i])[0]
        bin_ = np.cross(T, nrm)
        th = np.linspace(0, 2 * math.pi, S + 1)
        ct, st = np.cos(th), np.sin(th)
        rad = np.repeat(R[:, None], S + 1, 1)
        if b.level == 0 and b.stem:
            z = P[:, 2:3]
            fl = 1.0 + env_flare * np.exp(-np.maximum(z + 0.15, 0) / 0.45)
            lobe = 1.0 + sp.get("buttress", 0.12) * np.exp(-np.maximum(z + 0.15, 0) / 0.6) * \
                np.cos(lobes * th[None, :] + rng.uniform(0, 6.28))
            bumps = 1.0 + 0.035 * np.sin(3 * th[None, :] + 1.7 * z + 0.5) * np.sin(2.3 * z + 1.1)
            rad = rad * fl * lobe * bumps
        ring_dir = ct[None, :, None] * nrm[:, None, :] + st[None, :, None] * bin_[:, None, :]
        verts = P[:, None, :] + rad[..., None] * ring_dir
        # radial normals (lean slightly along the taper)
        dr = np.gradient(R) / np.maximum(np.gradient(b.s), 1e-6)
        nn = unit(ring_dir - dr[:, None, None] * T[:, None, :])
        ku = max(1, round(2 * math.pi * r0 / su))
        v0 = rng.uniform(0, 1)
        uu = np.repeat((th / (2 * math.pi) * ku)[None, :], m, 0)
        vv = np.repeat((v0 + b.s / sv)[:, None], S + 1, 1)
        idx = np.arange(m * (S + 1)).reshape(m, S + 1) + nv
        q0, q1 = idx[:-1, :-1], idx[:-1, 1:]
        q2, q3 = idx[1:, 1:], idx[1:, :-1]
        tri = np.concatenate([np.stack([q0, q1, q2], -1).reshape(-1, 3),
                              np.stack([q0, q2, q3], -1).reshape(-1, 3)])
        V.append(verts.reshape(-1, 3))
        A.append(np.repeat(R, S + 1))
        N.append(nn.reshape(-1, 3))
        UV.append(np.stack([uu, vv], -1).reshape(-1, 2))
        F.append(tri)
        nv += m * (S + 1)
        # cap thick ends (cut or truncated limbs would show a hole from above)
        if R[-1] > 0.012:
            V.append(P[-1:] + T[-1:] * R[-1] * 0.6)
            A.append(R[-1:])
            N.append(T[-1:])
            UV.append(np.array([[0.5, v0 + b.s[-1] / sv]]))
            ring = idx[-1]
            F.append(np.stack([ring[:-1], ring[1:], np.full(S, nv)], -1))
            nv += 1
    V = np.concatenate(V)
    return {"verts": V, "tris": np.concatenate(F).astype(np.int32), "uv": np.concatenate(UV),
            "normals": np.concatenate(N), "radius": np.concatenate(A)}


# ---------------------------------------------------------------------------------------------
LEAF_SHAPES = {
    # (x along blade 0..1, y across, z up) outlines; triangles index into the list.
    # 'simple': 6 verts / 4 tris diamond-ish ovate
    "ovate": ([(0, 0), (0.25, -0.42), (0.25, 0.42), (0.62, -0.38), (0.62, 0.38), (1, 0)],
              [(0, 1, 2), (1, 3, 4), (1, 4, 2), (3, 5, 4)]),
    "lanceolate": ([(0, 0), (0.3, -0.26), (0.3, 0.26), (0.68, -0.22), (0.68, 0.22), (1, 0)],
                   [(0, 1, 2), (1, 3, 4), (1, 4, 2), (3, 5, 4)]),
    # oak: lobed outline, 10 verts / 8 tris (mid-rib verts give the fold)
    "oak": ([(0, 0), (0.2, -0.3), (0.2, 0.3), (0.4, 0), (0.52, -0.42), (0.52, 0.42),
             (0.72, 0), (0.82, -0.3), (0.82, 0.3), (1, 0)],
            [(0, 1, 3), (0, 3, 2), (1, 4, 3), (3, 5, 2), (4, 6, 3), (3, 6, 5), (4, 7, 6), (6, 8, 5),
             (7, 9, 6), (6, 9, 8)]),
    # heart-shaped (linden): wide base lobes
    "cordate": ([(0, 0), (0.05, -0.45), (0.05, 0.45), (0.4, -0.5), (0.4, 0.5), (0.45, 0),
                 (0.78, -0.3), (0.78, 0.3), (1, 0)],
                [(0, 1, 5), (0, 5, 2), (1, 3, 5), (5, 4, 2), (3, 6, 5), (5, 7, 4), (6, 8, 5), (5, 8, 7)]),
    # palmate (maple / plane): fan from the petiole end, lobe tips and notches
    "palmate": ([(0, 0), (0.15, -0.55), (0.45, -0.75), (0.5, -0.3), (0.95, -0.38), (0.6, 0),
                 (1.05, 0), (0.95, 0.38), (0.5, 0.3), (0.45, 0.75), (0.15, 0.55), (0.32, 0)],
                [(0, 1, 11), (1, 2, 11), (2, 3, 11), (3, 4, 5), (3, 5, 11), (4, 6, 5), (5, 6, 7),
                 (5, 7, 8), (5, 8, 11), (8, 9, 11), (9, 10, 11), (10, 0, 11)]),
    # ginkgo fan: wedge widening to a notched rim
    "fan": ([(0, 0), (0.75, -0.62), (0.95, -0.3), (0.85, 0), (0.95, 0.3), (0.75, 0.62), (0.35, 0)],
            [(0, 1, 6), (1, 2, 6), (2, 3, 6), (3, 4, 6), (4, 5, 6), (5, 0, 6)]),
    # birch / elm: ovate with an acute tip
    "birch": ([(0, 0), (0.22, -0.4), (0.22, 0.4), (0.55, -0.36), (0.55, 0.36), (1, 0)],
              [(0, 1, 2), (1, 3, 4), (1, 4, 2), (3, 5, 4)]),
    # honey locust leaflet: 4 verts / 2 tris
    "leaflet": ([(0, 0), (0.5, -0.5), (0.5, 0.5), (1, 0)], [(0, 1, 2), (1, 3, 2)]),
}


def leaf_template(name, width):
    pts, tris = LEAF_SHAPES[name]
    p = np.array(pts, dtype=np.float64)
    p[:, 1] *= width
    return p, np.array(tris, dtype=np.int32)


def leaf_mesh(gen, sp, rng):
    """Place leaves on the leaf-bearing branches. Returns arrays like tube_mesh plus colours."""
    env = gen.env
    LS = sp["leaf"]
    min_z = sp["min_leaf_z"]
    # ---- collect attachment points along bearing branches -----------------------------------
    nlev = len(sp["levels"]) - 1
    bearing = []
    for b in gen.branches:
        if b.level == nlev:
            bearing.append((b, 0.05, 1.0))
        elif b.level == nlev - 1 and b.level > 0:
            bearing.append((b, LS.get("parent_from", 0.55), 1.0))
    total = sum(b.length * (t1 - t0) for b, t0, t1 in bearing)
    per_node = LS.get("per_node", 1)
    tip_n = LS.get("tip_cluster", 0)
    target = sp["leaf_target"]
    n_tips = len(bearing)
    spacing = total * per_node / max(target - n_tips * tip_n, target * 0.3)
    P, T, ROLL, TIPF = [], [], [], []
    for b, t0, t1 in bearing:
        L = b.length * (t1 - t0)
        n = int(L / spacing)
        if n > 0:
            ts = t0 + (t1 - t0) * (np.arange(n) + rng.uniform(0.2, 0.8, n)) / n
            # cumulative phyllotaxis roll
            if LS.get("arrangement") == "opposite":
                roll = (np.arange(n) % 2) * (math.pi / 2) + rng.uniform(0, math.pi)
            else:
                roll = np.arange(n) * math.radians(LS.get("phyllo", 144.0)) + rng.uniform(0, 6.28)
            for t, r in zip(ts, roll):
                p, d, _ = b.at(t)
                for j in range(per_node):
                    P.append(p)
                    T.append(d)
                    ROLL.append(r + j * math.pi * 2 / per_node)
                    TIPF.append(0.0)
        # terminal cluster
        p, d, _ = b.at(1.0)
        for j in range(tip_n):
            P.append(p)
            T.append(d)
            ROLL.append(j * 2 * math.pi / tip_n + rng.normal() * 0.3)
            TIPF.append(1.0)
    P, T = np.array(P), unit(np.array(T))
    ROLL, TIPF = np.array(ROLL), np.array(TIPF)
    keep = P[:, 2] >= min_z
    P, T, ROLL, TIPF = P[keep], T[keep], ROLL[keep], TIPF[keep]
    n = len(P)
    # ---- orientation ---------------------------------------------------------------------------
    A = np.cross(T, UP)
    bad = np.linalg.norm(A, axis=1) < 1e-3
    A[bad] = np.array([1.0, 0, 0])
    A = unit(A)
    B = np.cross(T, A)
    radial = np.cos(ROLL)[:, None] * A + np.sin(ROLL)[:, None] * B
    beta = np.radians(LS.get("petiole_angle", 55.0) + rng.normal(0, 12, n))
    beta = np.where(TIPF > 0, np.radians(LS.get("tip_angle", 30.0)) + rng.normal(0, 0.15, n), beta)
    D = unit(np.cos(beta)[:, None] * T + np.sin(beta)[:, None] * radial)
    D = unit(D - UP * LS.get("droop", 0.3))
    out = P.copy()
    out[:, 0] -= env.cx
    out[:, 1] -= env.cy
    out[:, 2] = 0
    out = unit(out)
    cen = np.array([env.cx, env.cy, env.zb + 0.5 * (env.H - env.zb)])
    out3 = unit((P - cen) / np.array([env.R, env.R, 0.5 * (env.H - env.zb) + 1e-3]))
    npref = unit(UP * LS.get("face_up", 1.0) + out3 * LS.get("face_out", 0.6) + rng.normal(0, 0.45, (n, 3)))
    Nl = unit(npref - (npref * D).sum(1, keepdims=True) * D)
    Sd = np.cross(Nl, D)
    size = LS["length"] * rng.uniform(0.75, 1.2, n) * sp.get("leaf_scale", 1.0)
    # sunlit outer leaves are smaller, shade leaves bigger
    dep = env.depth(P)
    size *= 1.0 + 0.25 * np.clip(dep / sp["shell"], 0, 1)
    base = P + D * (LS.get("petiole", 0.25) * size)[:, None]
    # ---- geometry --------------------------------------------------------------------------------
    if LS["shape"] == "pinnate":
        return pinnate_leaves(base, D, Sd, Nl, size, LS, rng, env, sp, out3, dep)
    tpl, tris = leaf_template(LS["shape"], LS.get("width", 1.0))
    k = len(tpl)
    x = tpl[None, :, 0] * size[:, None]
    y = tpl[None, :, 1] * size[:, None]
    bend = LS.get("bend", 0.18) * rng.uniform(0.4, 1.4, n)
    fold = LS.get("fold", 0.15) * rng.uniform(0.5, 1.3, n)
    z = -bend[:, None] * (tpl[None, :, 0] ** 2) * size[:, None] + fold[:, None] * np.abs(y)
    # random twist about the blade axis
    tw = rng.normal(0, 0.25, n)
    ys = y * np.cos(tw)[:, None] - z * np.sin(tw)[:, None]
    zs = y * np.sin(tw)[:, None] + z * np.cos(tw)[:, None]
    V = base[:, None, :] + x[..., None] * D[:, None, :] + ys[..., None] * Sd[:, None, :] + \
        zs[..., None] * Nl[:, None, :]
    F = (tris[None, :, :] + (np.arange(n) * k)[:, None, None]).reshape(-1, 3)
    uv = np.stack([0.5 + tpl[:, 1] / (2 * max(LS.get("width", 1.0), 0.3) * 1.1), tpl[:, 0]], -1)
    UV = np.tile(uv, (n, 1))
    # shading normal: blend of the leaf's own normal and the crown's outward normal
    so = LS.get("normal_out", 0.55)
    Nv = unit(Nl * (1 - so) + out3 * so + UP * 0.15)
    Nv = np.repeat(Nv, k, 0) + 0.12 * np.sign(tpl[:, 1])[None, :, None].repeat(n, 0).reshape(-1, 1) * \
        np.repeat(Sd, k, 0)
    Nv = unit(Nv)
    col, ao = leaf_colors(n, P, dep, sp, rng, env)
    return {"verts": V.reshape(-1, 3), "tris": F.astype(np.int32), "uv": UV, "normals": Nv,
            "color": np.repeat(col, k, 0), "ao": np.repeat(ao, k, 0), "count": n}


def pinnate_leaves(base, D, Sd, Nl, size, LS, rng, env, sp, out3, dep):
    """Compound leaves: leaflet pairs along a rachis (honey locust)."""
    n = len(base)
    pairs = LS.get("pairs", 8)
    tpl, tris = leaf_template("leaflet", LS.get("width", 0.4))
    k = len(tpl)
    ts = (np.arange(pairs) + 0.6) / (pairs + 0.3)
    # rachis arches down
    arch = LS.get("bend", 0.2)
    lf = LS["leaflet"] * sp.get("leaf_scale", 1.0)
    allV, allN, allUV = [], [], []
    so = LS.get("normal_out", 0.55)
    Nv_leaf = unit(Nl * (1 - so) + out3 * so + UP * 0.15)
    for j, t in enumerate(ts):
        c = base + D * (t * size)[:, None] - Nl * (arch * t * t * size)[:, None]
        for sgn in (-1.0, 1.0):
            ang = math.radians(LS.get("leaflet_angle", 70.0)) + rng.normal(0, 0.12, n)
            dl = unit(np.cos(ang)[:, None] * D + sgn * np.sin(ang)[:, None] * Sd + Nl * rng.normal(0, 0.2, (n, 1)))
            sl = np.cross(Nl, dl)
            ln = lf * rng.uniform(0.8, 1.15, n) * (1.0 - 0.3 * abs(t - 0.5))
            x = tpl[None, :, 0] * ln[:, None]
            y = tpl[None, :, 1] * ln[:, None]
            V = c[:, None, :] + x[..., None] * dl[:, None, :] + y[..., None] * sl[:, None, :]
            allV.append(V)
            allN.append(np.repeat(Nv_leaf[:, None, :], k, 1))
            allUV.append(np.repeat(np.stack([0.5 + tpl[:, 1], tpl[:, 0]], -1)[None], n, 0))
        # terminal leaflet pair counts already; nothing else
    m = len(allV)                                     # leaflets per compound leaf
    V = np.stack(allV, 1).reshape(n, m * k, 3)
    Nn = np.stack(allN, 1).reshape(n, m * k, 3)
    UV = np.stack(allUV, 1).reshape(n, m * k, 2)
    F = (tris[None, None] + (np.arange(m) * k)[None, :, None, None] +
         (np.arange(n) * m * k)[:, None, None, None]).reshape(-1, 3)
    col, ao = leaf_colors(n, base, dep, sp, rng, env)
    # a little per-leaflet variation
    colv = np.repeat(col, m * k, 0) * rng.uniform(0.9, 1.08, (n * m, 1)).repeat(k, 0)
    return {"verts": V.reshape(-1, 3), "tris": F.astype(np.int32), "uv": UV.reshape(-1, 2),
            "normals": Nn.reshape(-1, 3), "color": colv, "ao": np.repeat(ao, m * k, 0), "count": n * m}


def leaf_colors(n, P, dep, sp, rng, env):
    """Per-leaf albedo (linear) with variation, plus a baked crown-occlusion term."""
    pal = np.array(sp["leaf_colors"], dtype=np.float64)          # sRGB swatches
    w = np.array(sp.get("leaf_color_weights", [1.0] * len(pal)), dtype=np.float64)
    pick = rng.choice(len(pal), n, p=w / w.sum())
    # cluster-coherent variation: noise from position (leaves on one twig share a tint)
    cell = np.floor(P / 0.9).astype(np.int64)
    h = (cell[:, 0] * 73856093 ^ cell[:, 1] * 19349663 ^ cell[:, 2] * 83492791) % 1000 / 1000.0
    c = pal[pick] * sp.get("leaf_gain", 1.15) * (0.82 + 0.3 * h[:, None]) * rng.uniform(0.9, 1.1, (n, 1))
    # hue jitter: shift toward yellow (more red) or blue-green
    c[:, 0] *= rng.uniform(0.85, 1.18, n)
    c[:, 2] *= rng.uniform(0.85, 1.15, n)
    # top of crown slightly lighter/yellower (young growth, more sun)
    hf = np.clip(env.hfrac(P[:, 2]), 0, 1)
    c *= (0.95 + 0.1 * hf)[:, None]
    c = np.clip(c, 0, 1)
    lin = srgb_to_linear(c)
    ao = 0.62 + 0.38 * np.clip(1.0 - dep / (sp["shell"] * 1.2), 0, 1)
    ao *= 0.85 + 0.15 * hf
    return lin, ao


def generate(sp, seed, bark_size):
    gen = TreeGen(sp, seed).build()
    rng = np.random.default_rng(seed + 1)
    bark = tube_mesh(gen.branches, sp, bark_size, rng)
    leaves = leaf_mesh(gen, sp, rng)
    # bark occlusion: darker inside the crown
    dep = gen.env.depth(bark["verts"])
    inside = bark["verts"][:, 2] > gen.env.zb
    bark["ao"] = np.where(inside, 0.55 + 0.45 * np.clip(1 - dep / (sp["shell"] * 1.5), 0, 1), 1.0)
    # young wood is darker / browner than the trunk bark: tint thin branches (multiplier on the texture)
    tw = np.clip((bark["radius"] - 0.008) / 0.035, 0, 1)[:, None]
    tc = np.array(sp.get("twig_tint", (0.72, 0.66, 0.6)))
    bark["tint"] = (tc * (1 - tw) + tw) * bark["ao"][:, None]
    return gen, bark, leaves
