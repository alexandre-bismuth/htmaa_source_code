"""Procedural 2002 Subaru Impreza WRX STi (GDB "bugeye") body + wheels, in the WRC-style livery
(WR Blue, yellow swoosh with the Pleiades stars, gold wheels).

Usage:  uv run make_sti.py
Output: data/processed/common/car/sti_<part>.glb  (paint, glass, black, lens, red, rim, tire, brake)
        data/processed/common/car/sti_livery.png  (paint texture: side / side / top projections)

Frame: car-local metres, x forward, y LEFT, z up (right-handed; written to glTF as E=x, N=y, U=z,
which Unreal imports as X=x, Y=-y = right, Z=z). The origin is the vehicle actor's mesh origin:
the template physics skeleton, whose ground sits at z = -0.086 at rest (settle test).
Wheel centres (from the STi offsets in ImprezaSTi.cpp): front x=1.2915, rear x=-1.2335,
track 1.485 / 1.490 m, radius 0.317 m.

Dimensions: GDB-B 4405 x 1740 x 1425 mm, wheelbase 2525 mm, overhangs ~905 / 975 mm.
The body is a loft of cross-sections; every profile is a function of x (see SECTION_*).
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from gltf import write_glb

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/processed/common/car"

G = -0.086                        # ground z
XF, XR = 2.1965, -2.2085          # bumper tips
XA_F, XA_R = 1.2915, -1.2335      # axles
TRACK_F, TRACK_R = 1.485, 1.490
R_WHEEL, W_TIRE = 0.317, 0.225
R_ARCH = 0.365
L = XF - XR

# --- side elevation (heights above ground, m) ---------------------------------------------
X_COWL, X_WS_TOP, X_ROOF_END, X_DECK = 0.86, 0.02, -0.92, -1.50


def interp(x, pts):
    xs, ys = zip(*sorted(pts))
    return float(np.interp(x, xs, ys))


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def h_top(x):
    """Centre-line top: bumper/hood, windshield, roof, rear window, deck, tail."""
    if x >= X_COWL:
        # hood: 0.70 at the leading edge (x=2.12) -> 0.955 at the cowl, slight convex arc
        t = (XF - 0.07 - x) / (XF - 0.07 - X_COWL)
        h = 0.67 + 0.285 * (1 - (1 - min(max(t, 0), 1)) ** 1.5)
        if x > XF - 0.07:   # nose rolls down to the bumper face
            s = (x - (XF - 0.07)) / 0.07
            h = 0.67 - 0.17 * s ** 2
        return h
    if x >= X_WS_TOP:       # windshield: slightly convex
        t = (X_COWL - x) / (X_COWL - X_WS_TOP)
        return 0.955 + 0.465 * (t ** 0.85)
    if x >= X_ROOF_END:     # roof, peak just behind the B-pillar
        t = (X_WS_TOP - x) / (X_WS_TOP - X_ROOF_END)
        return 1.420 + 0.008 * math.sin(math.pi * t) - 0.02 * t ** 3
    if x >= X_DECK:         # rear window
        t = (X_ROOF_END - x) / (X_ROOF_END - X_DECK)
        return 1.398 - 0.338 * smooth(t) ** 0.9
    # trunk deck then the tail face
    if x >= -2.08:
        return 1.060 - 0.02 * (X_DECK - x) / (X_DECK + 2.08)
    s = (-2.08 - x) / (XR + 2.08) * -1
    return 1.040 - 0.48 * min(max(s, 0), 1) ** 1.5


def h_belt(x):
    """Beltline (bottom of the side glass / top of the fenders and deck edge)."""
    return interp(x, [(XF, 0.66), (1.95, 0.76), (1.40, 0.84), (X_COWL, 0.93), (0.0, 0.965),
                      (-0.95, 0.99), (X_DECK, 1.03), (-2.08, 1.025), (XR, 0.86)])


def h_bottom(x):
    return interp(x, [(XF, 0.30), (2.12, 0.19), (1.90, 0.17), (-1.95, 0.20), (-2.12, 0.24), (XR, 0.34)])


def wheel_centre(x):
    for xa in (XA_F, XA_R):
        if abs(x - xa) < R_ARCH:
            return xa
    return None


def h_rocker_side(x):
    """Lower edge of the body side, cut out by the wheel arches."""
    h = h_bottom(x) + 0.02
    xa = wheel_centre(x)
    if xa is not None:
        dx = x - xa
        h = max(h, R_WHEEL + 0.015 + math.sqrt(max(R_ARCH ** 2 - dx * dx, 0.0)) - 0.03)
    return h


# --- plan view (half widths, m) --------------------------------------------------------------
def plan(x, w_mid):
    """Rounds the corners of the nose and tail in plan view (flat-ish faces, ~0.33 m radius)."""
    for tip, rc, w_tip in ((XF, 0.36, 0.60), (XR, 0.30, 0.66)):
        d = (x - (tip - math.copysign(rc, tip))) / rc * math.copysign(1, tip)
        if d > 0:
            return w_tip + (w_mid - w_tip) * (1 - min(d, 1) ** 2.4) ** (1 / 2.4)
    return w_mid


def flare(x):
    """Fender flare over the wheels (the GDB's widened arches)."""
    xa = wheel_centre(x)
    if xa is None:
        return 0.0
    return 0.018 * math.cos(0.5 * math.pi * min(abs(x - xa) / R_ARCH, 1)) ** 2


W_SHOULDER, W_LOW, W_BELT, W_ROOF, W_INNER = 0.858, 0.835, 0.795, 0.585, 0.615


def upper(x):
    """Roof edge / A- and C-pillar line (half width, height)."""
    hb, ht = h_belt(x), h_top(x)
    if X_WS_TOP >= x >= X_ROOF_END:
        return W_ROOF, ht - 0.035
    if X_COWL > x > X_WS_TOP:            # A-pillar climbs from the cowl corner to the roof edge
        t = smooth((X_COWL - x) / (X_COWL - X_WS_TOP))
        return W_BELT - 0.06 + (W_ROOF - W_BELT + 0.06) * t, hb + 0.01 + (ht - 0.035 - hb - 0.01) * min(1, t * 1.15)
    if X_ROOF_END > x > X_DECK:          # C-pillar descends to the deck
        t = smooth((X_ROOF_END - x) / (X_ROOF_END - X_DECK))
        return W_ROOF + (W_BELT - 0.05 - W_ROOF) * t, (ht - 0.035) + (hb + 0.01 - (ht - 0.035)) * t
    return W_BELT - 0.05, (hb + ht) / 2 + 0.005   # hood / deck: crowned surface edge


SEGS = [("top", 7), ("glass", 5), ("upperside", 5), ("lowerside", 7), ("sill", 2), ("well", 2), ("floor", 3)]


def section(x):
    """Half section (left side, y >= 0) from the top centre around to the floor centre.
    Returns points [(y, z_above_ground)] and the segment label of each edge."""
    f = lambda w: plan(x, w)
    ht, hb = h_top(x), h_belt(x)
    wu, hu = upper(x)
    wu = f(wu) if not (X_COWL > x > X_DECK) else wu
    hs = max(0.66, h_rocker_side(x) + 0.06) if wheel_centre(x) is None else max(0.66, h_rocker_side(x) + 0.05)
    hs = min(hs, hb - 0.08)
    hl = h_rocker_side(x)
    hf = h_bottom(x)
    w_sh = f(W_SHOULDER + flare(x))
    w_belt = f(W_BELT)
    w_low = f(W_LOW + flare(x) * 0.6)
    w_in = min(f(W_INNER), w_low - 0.02)
    pts, labels = [], []

    def add(seq, label):
        for p in seq:
            if pts:
                labels.append(label)
            pts.append(p)

    # top: crown from centre to the roof/hood edge
    n = SEGS[0][1]
    crown = 0.035 if (X_WS_TOP >= x >= X_ROOF_END) else 0.02
    add([(wu * i / n, ht - (ht - hu - 0.0) * (i / n) ** 2.2 if i else ht) for i in range(n + 1)], "top")
    labels[-n:] = ["top"] * n
    # side glass / pillar: straight tumblehome line down to the beltline
    n = SEGS[1][1]
    add([(wu + (w_belt - wu) * i / n, hu + (hb - hu) * i / n) for i in range(1, n + 1)], "glass")
    # body side: beltline -> shoulder (max width) -> rocker, a smooth bulge
    n = SEGS[2][1]
    add([(w_belt + (w_sh - w_belt) * math.sin(0.5 * math.pi * i / n), hb + (hs - hb) * i / n) for i in range(1, n + 1)], "upperside")
    n = SEGS[3][1]
    add([(w_sh + (w_low - w_sh) * (i / n) ** 2, hs + (hl - hs) * i / n) for i in range(1, n + 1)], "lowerside")
    add([(w_in, hl)], "sill")
    add([(w_in, hf)], "well")
    n = SEGS[6][1]
    add([(w_in * (1 - i / n), hf) for i in range(1, n + 1)], "floor")
    return pts, labels


def stations():
    xs = list(np.linspace(XR, XF, 260))
    for xa in (XA_F, XA_R):          # densify around the arches
        xs += list(np.linspace(xa - R_ARCH - 0.02, xa + R_ARCH + 0.02, 50))
    for k in (X_COWL, X_WS_TOP, X_ROOF_END, X_DECK, -0.12, -0.04):
        xs += [k - 0.004, k + 0.004]
    return np.array(sorted(set(round(v, 5) for v in xs)))


# --- mesh accumulation -----------------------------------------------------------------------
class Part:
    def __init__(self):
        self.p, self.n, self.uv, self.f = [], [], [], []

    def tri(self, a, b, c, na, nb, nc, uva=(0, 0), uvb=(0, 0), uvc=(0, 0)):
        k = len(self.p)
        self.p += [a, b, c]
        self.n += [na, nb, nc]
        self.uv += [uva, uvb, uvc]
        self.f.append([k, k + 1, k + 2])

    def flat(self, a, b, c, outward_ref=None, uv=None):
        a, b, c = map(np.asarray, (a, b, c))
        nrm = np.cross(b - a, c - a)
        if outward_ref is not None and np.dot(nrm, (a + b + c) / 3 - outward_ref) < 0:
            b, c = c, b
            nrm = -nrm
        nrm = nrm / (np.linalg.norm(nrm) + 1e-12)
        uvs = uv or [(0, 0)] * 3
        self.tri(a, b, c, nrm, nrm, nrm, *uvs)

    def write(self, path, material):
        if not self.f:
            return 0
        p = np.array(self.p)
        write_glb(path, p, np.array(self.f), np.array(self.n), np.array(self.uv), np.zeros((len(p), 2)), material)
        return len(self.f)


PARTS = {k: Part() for k in ("paint", "glass", "black", "lens", "red", "chrome")}


# --- livery texture --------------------------------------------------------------------------
TEX = 4096
BLUE = (16, 62, 168)
YELLOW = (255, 204, 0)
FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
H_TEX = 1.50     # metres of height mapped onto one side band


def side_uv(x, z, side):
    """Side bands: left side in v 0..1/3, right side in 1/3..2/3. u = distance from the nose."""
    u = (XF - x) / L
    if side == "right":
        u = 1 - u
    v = (1.0 - min(max(z / H_TEX, 0), 1)) / 3.0 + (1 / 3 if side == "right" else 0)
    return (u, v)


def top_uv(x, y):
    return ((XF - x) / L, 2 / 3 + (0.5 - y / 1.9) / 3)


def draw_livery():
    img = Image.new("RGB", (TEX, TEX), BLUE)
    band = TEX // 3

    def side_band(right):
        """One side elevation, nose on the left (mirrored for the right side), in band pixels."""
        im = Image.new("RGB", (TEX, band), BLUE)
        d = ImageDraw.Draw(im)
        px = lambda dist, h: (dist / L * TEX, (1 - h / H_TEX) * band)

        def ellipse(cx, cy, rx, ry, fill):
            (x0, y0), (x1, y1) = px(cx - rx, cy + ry), px(cx + rx, cy - ry)
            d.ellipse([x0, y0, x1, y1], fill=fill)

        # the swoosh: a big yellow disc on the rear door, eaten by a blue disc -> crescent opening rearward,
        # plus two thin chevron streaks rising to the rear quarter
        ellipse(2.60, 0.62, 0.78, 0.40, YELLOW)
        ellipse(2.93, 0.635, 0.56, 0.355, BLUE)
        for (a, b, w) in (((3.10, 0.90), (3.62, 0.985), 0.028), ((3.18, 0.835), (3.58, 0.905), 0.022)):
            d.polygon([px(a[0], a[1] + w), px(b[0], b[1] + w * 0.4), px(b[0], b[1] - w * 0.4), px(a[0] + 0.08, a[1] - w)], fill=YELLOW)

        # the Pleiades: one big four-point star and five small ones inside the blue disc
        def star(cx, cy, r):
            pts = []
            for k in range(8):
                ang = math.pi / 2 + k * math.pi / 4
                rr = r if k % 2 == 0 else r * 0.28
                pts.append(px(cx + rr * math.cos(ang) * 0.9, cy + rr * math.sin(ang)))
            d.polygon(pts, fill=YELLOW)
        star(2.88, 0.66, 0.115)
        for (cx, cy, r) in ((3.08, 0.80, 0.055), (3.16, 0.64, 0.05), (3.04, 0.50, 0.05), (3.24, 0.74, 0.04), (3.22, 0.53, 0.038)):
            star(cx, cy, r)
        if right:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        d = ImageDraw.Draw(im)
        # text is drawn after mirroring so it reads correctly on both sides
        font = ImageFont.truetype(FONT, int(0.085 / H_TEX * band))
        dist = 2.42
        x0, y0 = dist / L * TEX, (1 - 0.43 / H_TEX) * band
        if right:
            w = d.textlength("SUBARU", font=font)
            x0 = TEX - x0 - w
        d.text((x0, y0), "SUBARU", font=font, fill=YELLOW)
        return im

    img.paste(side_band(False), (0, 0))
    img.paste(side_band(True), (0, band))
    # top band: "SUBARU" across the hood leading edge, reading from the front
    top = Image.new("RGB", (TEX, TEX - 2 * band), BLUE)
    d = ImageDraw.Draw(top)
    font = ImageFont.truetype(FONT, int(0.09 / 1.9 * top.height))
    word = Image.new("RGBA", (int(d.textlength("SUBARU", font=font)) + 20, font.size + 30), (0, 0, 0, 0))
    ImageDraw.Draw(word).text((10, 0), "SUBARU", font=font, fill=(235, 235, 235, 255))
    # letters run across the car, tops toward the windshield; the top projection is mirrored, hence the flip
    word = word.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
    u = (XF - 1.98) / L * TEX
    top.paste(word, (int(u - word.width / 2), int(top.height / 2 - word.height / 2)), word)
    img.paste(top, (0, 2 * band))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "sti_livery.png")


# --- body loft -------------------------------------------------------------------------------
def build_body():
    xs = stations()
    rings, labels = [], None
    for x in xs:
        half, lab = section(x)
        # full ring: left half (y>0) from top centre to floor centre, then the right half mirrored back up
        left = [(x, y, G + z) for (y, z) in half]
        right = [(x, -y, G + z) for (y, z) in reversed(half)][1:-1]
        rings.append(left + right)
        labels = lab + ["floor"] + list(reversed(lab))[1:]
    P = np.array(rings)                      # [stations, ring]
    ns, nr = P.shape[:2]
    # smooth normals on the closed ring grid (area-weighted face normals, oriented outward)
    acc = np.zeros_like(P)
    for i in range(ns - 1):
        for j in range(nr):
            j2 = (j + 1) % nr
            a, b, c, d = P[i, j], P[i + 1, j], P[i + 1, j2], P[i, j2]
            n = np.cross(c - a, d - b)
            centre = np.array([a[0], 0.0, G + 0.6])
            if np.dot(n, (a + c) / 2 - centre) < 0:
                n = -n
            for (ii, jj) in ((i, j), (i + 1, j), (i + 1, j2), (i, j2)):
                acc[ii, jj] += n
    N = acc / (np.linalg.norm(acc, axis=2, keepdims=True) + 1e-12)

    def material(label, x, y, z, nrm):
        if label in ("well", "floor", "sill"):
            return "black"
        if label == "glass":
            # side glass between the A- and C-pillars; B-pillar blacked out
            if X_COWL - 0.10 > x > X_ROOF_END + 0.06:
                return "black" if -0.12 < x < -0.04 else "glass"
            return "paint"
        if label == "top":
            if X_COWL - 0.03 > x > X_WS_TOP + 0.02 and abs(y) < W_ROOF + 0.02 and abs(y) < upper(x)[0] - 0.035:
                return "glass"      # windshield
            if X_ROOF_END - 0.03 > x > X_DECK + 0.04 and abs(y) < upper(x)[0] - 0.05:
                return "glass"      # rear window
        return "paint"

    def uv_for(p, nrm):
        if abs(nrm[1]) > 0.45:
            return side_uv(p[0], p[2] - G, "left" if p[1] > 0 else "right")
        return top_uv(p[0], p[1])

    for i in range(ns - 1):
        for j in range(nr):
            j2 = (j + 1) % nr
            quad = [(i, j), (i + 1, j), (i + 1, j2), (i, j2)]
            pts = [P[q] for q in quad]
            nrms = [N[q] for q in quad]
            c = np.mean(pts, axis=0)
            fn = np.mean(nrms, axis=0)
            mat = material(labels[j], c[0], c[1], c[2], fn)
            part = PARTS[mat]
            n_face = np.cross(pts[2] - pts[0], pts[3] - pts[1])
            order = [0, 1, 2, 3] if np.dot(n_face, fn) > 0 else [0, 3, 2, 1]
            q = [pts[k] for k in order]
            qn = [nrms[k] for k in order]
            # one projection per face (keeps the livery from smearing across a face)
            if abs(fn[1]) > 0.45:
                side = "left" if c[1] > 0 else "right"
                uvs = [side_uv(v[0], v[2] - G, side) for v in q]
            else:
                uvs = [top_uv(v[0], v[1]) for v in q]
            part.tri(q[0], q[1], q[2], qn[0], qn[1], qn[2], uvs[0], uvs[1], uvs[2])
            part.tri(q[0], q[2], q[3], qn[0], qn[2], qn[3], uvs[0], uvs[2], uvs[3])

    # end caps (bumper faces): fan from the ring centroid
    for i, sgn in ((0, -1.0), (ns - 1, 1.0)):
        ring = P[i]
        centre = ring.mean(axis=0)
        ref = centre - np.array([sgn, 0, 0])
        for j in range(nr):
            a, b = ring[j], ring[(j + 1) % nr]
            PARTS["paint"].flat(centre, a, b, outward_ref=ref, uv=[top_uv(v[0], v[1]) for v in (centre, a, b)])


# --- detail parts ----------------------------------------------------------------------------
def box(part, c, size, rot_z=0.0, uv=None):
    cx, cy, cz = c
    sx, sy, sz = (s / 2 for s in size)
    cr, sr = math.cos(rot_z), math.sin(rot_z)
    corners = []
    for dx in (-sx, sx):
        for dy in (-sy, sy):
            for dz in (-sz, sz):
                corners.append(np.array([cx + dx * cr - dy * sr, cy + dx * sr + dy * cr, cz + dz]))
    centre = np.array(c)
    for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        a, b, cc, d = (corners[k] for k in face)
        part.flat(a, b, cc, outward_ref=centre, uv=uv)
        part.flat(a, cc, d, outward_ref=centre, uv=uv)


def disc(part, centre, normal, radius, depth=0.0, seg=32, dome=0.0, ring=None):
    """Flat or domed disc facing `normal` (optionally a ring between radius and `ring`)."""
    centre, normal = np.asarray(centre, float), np.asarray(normal, float)
    normal /= np.linalg.norm(normal)
    a = np.cross(normal, [0, 0, 1.0])
    if np.linalg.norm(a) < 1e-6:
        a = np.array([1.0, 0, 0])
    a /= np.linalg.norm(a)
    b = np.cross(normal, a)
    ref = centre - normal
    for k in range(seg):
        t0, t1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
        p0 = centre + radius * (math.cos(t0) * a + math.sin(t0) * b)
        p1 = centre + radius * (math.cos(t1) * a + math.sin(t1) * b)
        if ring is not None:
            q0 = centre + ring * (math.cos(t0) * a + math.sin(t0) * b)
            q1 = centre + ring * (math.cos(t1) * a + math.sin(t1) * b)
            part.flat(p0, p1, q1, outward_ref=ref)
            part.flat(p0, q1, q0, outward_ref=ref)
        else:
            tip = centre + normal * dome
            part.flat(tip, p0, p1, outward_ref=ref)


def build_details():
    paint, black = PARTS["paint"], PARTS["black"]
    blue_uv = [top_uv(1.0, 0.9)] * 3        # a plain-blue spot of the livery texture
    # bugeye headlights: round lenses on the front corners, angled forward/outward, black bezels
    for s in (1, -1):
        c = np.array([2.075, s * 0.575, G + 0.625])
        nrm = np.array([0.82, s * 0.45, 0.22])
        nrm = nrm / np.linalg.norm(nrm)
        disc(PARTS["black"], c - 0.01 * nrm, nrm, 0.145, seg=40)                      # housing behind the lens
        disc(PARTS["chrome"], c + 0.006 * nrm, nrm, 0.135, ring=0.112, seg=40)
        disc(PARTS["lens"], c + 0.01 * nrm, nrm, 0.112, dome=0.045, seg=40)
        # amber-ish side marker -> skip; fog light housings in the bumper (black)
        disc(black, (XF - 0.04, s * 0.62, G + 0.34), (1, s * 0.25, 0), 0.06, seg=20)
        # tail lights: wide red blocks on the rear corners, wrapping slightly
        box(PARTS["red"], (XR + 0.115, s * 0.66, G + 0.90), (0.06, 0.30, 0.12), rot_z=-s * 0.18)
        # mirrors (body colour) on the doors
        box(paint, (0.66, s * 0.885, G + 1.0), (0.16, 0.12, 0.10), uv=blue_uv)
        box(black, (0.70, s * 0.81, G + 0.975), (0.08, 0.06, 0.04))   # mirror stalk
        # wing uprights
        box(paint, (-1.98, s * 0.56, G + 1.13), (0.12, 0.03, 0.15), uv=blue_uv)
        # door handles
        for xh in (0.12, -0.70):
            box(black, (xh, s * (W_SHOULDER - 0.005), G + 0.90), (0.12, 0.02, 0.025))
    # grille (black) with a dark oval badge area, lower intake
    box(black, (XF - 0.005, 0.0, G + 0.585), (0.04, 0.70, 0.10))
    box(black, (XF + 0.003, 0.0, G + 0.27), (0.04, 0.95, 0.15))
    box(PARTS["chrome"], (XF + 0.018, 0.0, G + 0.585), (0.012, 0.09, 0.05))
    # hood scoop: wedge with a black opening facing forward
    x0, x1, wy, hz = 1.02, 1.42, 0.30, 0.065
    base = lambda x: G + h_top(x) - 0.004
    pts = {"bl": (x1, wy, base(x1)), "br": (x1, -wy, base(x1)), "tl": (x1 - 0.01, wy, base(x1) + hz), "tr": (x1 - 0.01, -wy, base(x1) + hz),
           "rl": (x0, wy, base(x0)), "rr": (x0, -wy, base(x0))}
    P = {k: np.array(v) for k, v in pts.items()}
    ref = np.array([1.2, 0, base(1.2) - 0.05])
    for tri in (("tl", "tr", "rr"), ("tl", "rr", "rl"), ("bl", "tl", "rl"), ("br", "rr", "tr")):
        paint.flat(*(P[k] for k in tri), outward_ref=ref, uv=blue_uv)
    black.flat(P["bl"], P["br"], P["tr"], outward_ref=ref)
    black.flat(P["bl"], P["tr"], P["tl"], outward_ref=ref)
    # rear wing: plank with a slight angle + end plates
    for k in range(2):
        box(paint, (-2.00, 0.0, G + 1.215 + 0.012 * k), (0.24 - 0.04 * k, 1.42, 0.022), uv=blue_uv)
    for s in (1, -1):
        box(paint, (-2.00, s * 0.715, G + 1.20), (0.26, 0.012, 0.08), uv=blue_uv)
    # skirts / mud flaps hint: black strip under the sills
    for s in (1, -1):
        box(black, (0.0, s * (W_LOW - 0.01), G + 0.215), (2.0, 0.03, 0.05))


# --- wheels ----------------------------------------------------------------------------------
def build_wheels():
    """Tyre 225/45R17 and a gold 10-spoke 17" rim. Outer face toward +y (= the car's left; the
    right wheels are turned 180 degrees in Unreal)."""
    tire, rim, brake = Part(), Part(), Part()
    hw = W_TIRE / 2
    R = R_WHEEL
    r_rim = 0.216
    # tyre: tread + rounded shoulders + sidewalls, as a closed profile (inner sidewall -> tread -> outer)
    prof = [(r_rim, -hw + 0.01), (R - 0.03, -hw), (R - 0.008, -hw + 0.012), (R, -hw + 0.04), (R, hw - 0.04),
            (R - 0.008, hw - 0.012), (R - 0.03, hw), (r_rim, hw - 0.01)]
    seg = 56
    for k in range(seg):
        t0, t1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
        for (r0, y0), (r1, y1) in zip(prof[:-1], prof[1:]):
            quad = [np.array([r * math.cos(t), y, r * math.sin(t)]) for (r, y, t) in ((r0, y0, t0), (r0, y0, t1), (r1, y1, t1), (r1, y1, t0))]
            # orient away from the torus core circle (radius ~0.27 in the wheel plane)
            core = 0.27 * np.array([math.cos((t0 + t1) / 2), 0, math.sin((t0 + t1) / 2)])
            tire.flat(quad[0], quad[1], quad[2], outward_ref=core)
            tire.flat(quad[0], quad[2], quad[3], outward_ref=core)
    # rim: barrel + outer lip ring + 10 spokes (5 pairs) + hub, slightly dished outward (+y)
    lip_y = hw - 0.012
    disc(rim, (0, lip_y, 0), (0, 1, 0), r_rim + 0.012, ring=r_rim - 0.018, seg=seg)
    for k in range(seg):     # barrel (inner face visible through the spokes)
        t0, t1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
        a = [np.array([(r_rim - 0.018) * math.cos(t), y, (r_rim - 0.018) * math.sin(t)]) for (t, y) in ((t0, lip_y), (t1, lip_y), (t1, -hw + 0.02), (t0, -hw + 0.02))]
        # normals face the axis: the barrel is seen from inside, through the spokes
        rim.flat(a[0], a[1], a[2], outward_ref=10 * (a[0] + a[2]) / 2)
        rim.flat(a[0], a[2], a[3], outward_ref=10 * (a[0] + a[2]) / 2)
    hub_y = lip_y - 0.035
    for k in range(10):
        ang = 2 * math.pi * (k // 2) / 5 + (0.13 if k % 2 else -0.13)   # five twin spokes
        mid = (0.055 + r_rim - 0.02) / 2
        c = np.array([mid * math.cos(ang), (hub_y + lip_y) / 2 - 0.005, mid * math.sin(ang)])
        # spoke box in its own frame: long along the radius
        length, width, depth = r_rim - 0.07, 0.042, 0.03
        u = np.array([math.cos(ang), 0, math.sin(ang)])
        v = np.array([-math.sin(ang), 0, math.cos(ang)])
        w = np.array([0, 1.0, 0])
        corners = [c + du * length / 2 * u + dv * width / 2 * v + dw * depth / 2 * w for du in (-1, 1) for dv in (-1, 1) for dw in (-1, 1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            a, b, cc, d = (corners[i] for i in face)
            rim.flat(a, b, cc, outward_ref=c)
            rim.flat(a, cc, d, outward_ref=c)
    disc(rim, (0, hub_y + 0.012, 0), (0, 1, 0), 0.075, dome=0.012, seg=24)
    # brake disc + gold-ish caliper hint behind the spokes
    disc(brake, (0, hub_y - 0.03, 0), (0, 1, 0), 0.165, ring=0.06, seg=40)
    box(brake, (0.0, hub_y - 0.02, 0.15), (0.12, 0.05, 0.05))   # caliper
    return tire, rim, brake


def main():
    draw_livery()
    build_body()
    build_details()
    stats = {}
    for name, part in PARTS.items():
        stats[name] = part.write(OUT / f"sti_{name}.glb", f"sti_{name}")
    tire, rim, brake = build_wheels()
    for name, part in (("tire", tire), ("rim", rim), ("brake", brake)):
        stats[name] = part.write(OUT / f"sti_{name}.glb", f"sti_{name}")
    print({k: v for k, v in stats.items()})


if __name__ == "__main__":
    main()
