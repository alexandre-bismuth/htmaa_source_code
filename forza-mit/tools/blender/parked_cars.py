"""Parked cars for the streets: 8 generic body types, procedural, one mesh each (Nanite-friendly, opaque).

Run (headless, ~1-2 min with the AO bake):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/parked_cars.py [-- options]
Options:  --types=sedan,suv   only these     --no-ao  skip the Cycles AO bake     --render  validation renders
          --render-only  (re-import the exported glbs and render)   --out-renders=<dir>

Outputs (data/processed/common/props/):
    parked_<type>.glb   one mesh, 3 material slots: parked_paint (0), parked_glass (1), parked_detail (2);
                        COLOR_0 (RGBA, linear, per face corner):
                          paint / glass: RGB = baked ambient occlusion x dirt (multiply into the colour), A = 1
                          detail: RGB = albedo incl. AO, A = surface class (k = round(A * 5)):
                            0 rubber (rough 0.85)  1 black plastic (0.5)  2 dark metal / underbody (0.6, metal 0.3)
                            3 alloy / chrome (0.22, metal 1)  4 lamp lens (0.06, specular 0.6)  5 licence plate (0.4)
                        UV0 = (x, z) metres (unused by the materials).
    parked_cars.json    per type: size, wheel base, collision box (centre / size, cm, mesh space), placement
                        weight, paint "white_bias", material notes.
Frame: X forward, Y left, Z up, ground z = 0, origin at the centre of the footprint (see parked_geom.py).
The body colour is NOT in the mesh: the Unreal paint material picks it per instance (PerInstanceRandom).
"""
import json
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for _m in [k for k in sys.modules if k.startswith("parked_geom")]:
    del sys.modules[_m]
import parked_geom as PG  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "data/processed/common/props"
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OPT = {a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in ARGS}

# ------------------------------------------------------------------------------------------------ the fleet
# d = distance back from the front end (m). top: lower-body top centre line (bumper top -> hood -> belt -> deck);
# cabin: d_c cowl (windshield base), d_h header, d_re roof end, d_rg rear glass base; roof: [(d, z)] roof line;
# side: side-glass d range; pillars: [(d0, d1, zone)] over the side glass; doors: seam d's (panel gaps).
# weight: share of the parked fleet (Cambridge mix: sedans / small SUVs dominate, few pickups / vans).
FLEET = {
    "sedan": dict(  # mid-size sedan (Camry / Accord class)
        L=4.88, W=1.84, H=1.445, wb=2.82, fo=0.98, R=0.335, tw=0.225, rim_r=0.230, rim="silver5",
        sill=0.30, bump_f=0.21, bump_r=0.30, crown=0.035, tumble=0.05, tuck=0.04,
        top=[(0.0, 0.60), (0.06, 0.70), (0.22, 0.76), (0.6, 0.81), (1.1, 0.87), (1.55, 0.93), (1.75, 0.985),
             (2.8, 0.995), (3.7, 1.015), (4.05, 1.035), (4.55, 1.045), (4.80, 1.03), (4.88, 0.98)],
        cabin=dict(d_c=1.58, d_h=2.32, d_re=3.58, d_rg=4.08, roof=[(2.32, 1.405), (2.85, 1.445), (3.25, 1.43), (3.58, 1.375)],
                   side=(1.76, 3.72), pillars=[(2.70, 2.81, "black"), (3.56, 9.0, "paint")], tumble_deg=24, sweep_f=0.24, sweep_r=0.18),
        doors=[1.70, 2.76, 3.66], weight=0.17, white_bias=0.0, lamps="sleek"),
    "compact": dict(  # compact fastback sedan (Civic / Corolla / Elantra)
        L=4.65, W=1.80, H=1.415, wb=2.70, fo=0.93, R=0.32, tw=0.215, rim_r=0.215, rim="dark6",
        sill=0.29, bump_f=0.20, bump_r=0.30, crown=0.03, tumble=0.05, tuck=0.04,
        top=[(0.0, 0.58), (0.06, 0.68), (0.22, 0.74), (0.6, 0.78), (1.1, 0.85), (1.50, 0.915), (1.68, 0.97),
             (2.7, 0.985), (3.6, 1.015), (3.95, 1.035), (4.42, 1.04), (4.58, 1.02), (4.65, 0.97)],
        cabin=dict(d_c=1.52, d_h=2.28, d_re=3.40, d_rg=4.02, roof=[(2.28, 1.38), (2.75, 1.415), (3.10, 1.40), (3.40, 1.34)],
                   side=(1.70, 3.74), pillars=[(2.62, 2.72, "black"), (3.50, 9.0, "paint")], tumble_deg=26, sweep_f=0.26, sweep_r=0.24),
        doors=[1.64, 2.66, 3.58], weight=0.14, white_bias=0.0, lamps="sleek"),
    "hatch": dict(  # compact hatchback (Golf / Civic hatch / Impreza 5-door)
        L=4.28, W=1.79, H=1.47, wb=2.63, fo=0.87, R=0.315, tw=0.205, rim_r=0.205, rim="silver10",
        sill=0.30, bump_f=0.21, bump_r=0.31, crown=0.03, tumble=0.05, tuck=0.035, end_r=0.22, roll_r=0.07,
        top=[(0.0, 0.60), (0.06, 0.70), (0.22, 0.76), (0.6, 0.81), (1.0, 0.875), (1.36, 0.94), (1.52, 1.00),
             (2.6, 1.015), (3.6, 1.04), (4.05, 1.06), (4.22, 1.05), (4.28, 1.01)],
        cabin=dict(d_c=1.38, d_h=2.12, d_re=3.88, d_rg=4.20, roof=[(2.12, 1.43), (2.55, 1.47), (3.4, 1.46), (3.88, 1.42)],
                   side=(1.56, 3.50), pillars=[(2.50, 2.60, "black"), (3.44, 9.0, "paint")], tumble_deg=25, sweep_f=0.24, sweep_r=0.10),
        doors=[1.50, 2.56, 3.42], weight=0.12, white_bias=0.0, lamps="sleek"),
    "wagon": dict(  # all-road wagon (Outback): black cladding, roof rails, higher
        L=4.87, W=1.86, H=1.675, wb=2.75, fo=0.95, R=0.36, tw=0.225, rim_r=0.225, rim="dark6",
        sill=0.40, bump_f=0.30, bump_r=0.36, crown=0.03, tumble=0.05, tuck=0.035, end_r=0.24, roll_r=0.07,
        clad=0.52, rails=True,
        top=[(0.0, 0.68), (0.06, 0.78), (0.22, 0.84), (0.6, 0.88), (1.1, 0.94), (1.55, 1.00), (1.72, 1.06),
             (2.8, 1.07), (3.9, 1.09), (4.5, 1.10), (4.80, 1.09), (4.87, 1.05)],
        cabin=dict(d_c=1.57, d_h=2.34, d_re=4.55, d_rg=4.80, roof=[(2.34, 1.585), (2.9, 1.62), (4.2, 1.615), (4.55, 1.575)],
                   side=(1.76, 4.48), pillars=[(2.73, 2.84, "black"), (3.74, 3.82, "black"), (4.40, 9.0, "paint")],
                   tumble_deg=22, sweep_f=0.24, sweep_r=0.08),
        doors=[1.70, 2.78, 3.78], weight=0.10, white_bias=0.0, lamps="square"),
    "crossover": dict(  # compact crossover (RAV4 / CR-V / Forester)
        L=4.60, W=1.86, H=1.69, wb=2.69, fo=0.95, R=0.36, tw=0.225, rim_r=0.225, rim="silver6",
        sill=0.42, bump_f=0.32, bump_r=0.38, crown=0.03, tumble=0.05, tuck=0.035, end_r=0.22, roll_r=0.07,
        clad=0.55, rails=True,
        top=[(0.0, 0.74), (0.06, 0.84), (0.22, 0.90), (0.6, 0.94), (1.0, 1.00), (1.40, 1.05), (1.56, 1.11),
             (2.7, 1.125), (3.8, 1.15), (4.35, 1.16), (4.54, 1.15), (4.60, 1.10)],
        cabin=dict(d_c=1.42, d_h=2.16, d_re=4.22, d_rg=4.52, roof=[(2.16, 1.65), (2.65, 1.69), (3.8, 1.68), (4.22, 1.63)],
                   side=(1.60, 4.16), pillars=[(2.56, 2.67, "black"), (3.52, 3.60, "black"), (4.06, 9.0, "paint")],
                   tumble_deg=23, sweep_f=0.24, sweep_r=0.08),
        doors=[1.54, 2.60, 3.56], weight=0.23, white_bias=0.0, lamps="square"),
    "suv": dict(  # mid / full-size 3-row SUV (Highlander / Explorer / Pilot)
        L=5.00, W=1.98, H=1.77, wb=2.87, fo=0.98, R=0.38, tw=0.245, rim_r=0.240, rim="silver6",
        sill=0.46, bump_f=0.36, bump_r=0.42, crown=0.03, tumble=0.05, tuck=0.03, end_r=0.22, roll_r=0.07,
        clad=0.56, rails=True,
        top=[(0.0, 0.80), (0.06, 0.90), (0.22, 0.96), (0.6, 1.00), (1.0, 1.06), (1.45, 1.11), (1.62, 1.17),
             (2.8, 1.185), (4.0, 1.20), (4.75, 1.21), (4.94, 1.20), (5.00, 1.15)],
        cabin=dict(d_c=1.47, d_h=2.22, d_re=4.70, d_rg=4.93, roof=[(2.22, 1.73), (2.7, 1.77), (4.3, 1.765), (4.70, 1.72)],
                   side=(1.66, 4.62), pillars=[(2.64, 2.76, "black"), (3.66, 3.76, "black"), (4.50, 9.0, "paint")],
                   tumble_deg=22, sweep_f=0.22, sweep_r=0.06),
        doors=[1.60, 2.70, 3.70], weight=0.12, white_bias=0.05, lamps="square"),
    "pickup": dict(  # full-size crew-cab pickup with a tonneau cover (F-150 / Silverado / Ram)
        L=5.89, W=2.03, H=1.96, wb=3.68, fo=1.00, R=0.40, tw=0.265, rim_r=0.255, rim="silver6",
        sill=0.55, bump_f=0.42, bump_r=0.50, crown=0.02, tumble=0.035, tuck=0.03, end_f=0.22, end_r=0.10,
        roll_f=0.06, roll_r=0.04, plan_n=3.2, bed=(3.72, 5.82),
        top=[(0.0, 1.02), (0.06, 1.12), (0.22, 1.17), (0.8, 1.22), (1.5, 1.27), (1.70, 1.31), (1.86, 1.37),
             (3.6, 1.385), (3.75, 1.37), (5.0, 1.37), (5.89, 1.36)],
        cabin=dict(d_c=1.72, d_h=2.38, d_re=3.56, d_rg=3.66, roof=[(2.38, 1.92), (2.8, 1.96), (3.3, 1.955), (3.56, 1.93)],
                   side=(1.95, 3.50), pillars=[(2.84, 2.96, "black")], tumble_deg=16, sweep_f=0.18, sweep_r=0.0, ledge=0.07),
        doors=[1.86, 2.90, 3.66, 3.70], weight=0.04, white_bias=0.30, lamps="truck"),
    "minivan": dict(  # minivan (Odyssey / Sienna / Pacifica): sliding doors, long windshield
        L=5.20, W=1.99, H=1.74, wb=3.00, fo=1.00, R=0.345, tw=0.235, rim_r=0.230, rim="silver5",
        sill=0.36, bump_f=0.25, bump_r=0.34, crown=0.03, tumble=0.05, tuck=0.03, end_r=0.20, roll_r=0.07,
        top=[(0.0, 0.64), (0.06, 0.74), (0.22, 0.81), (0.6, 0.90), (0.95, 0.98), (1.16, 1.03), (1.30, 1.06),
             (3.0, 1.075), (4.8, 1.10), (5.13, 1.10), (5.20, 1.05)],
        cabin=dict(d_c=1.18, d_h=2.08, d_re=4.95, d_rg=5.14, roof=[(2.08, 1.70), (2.6, 1.74), (4.5, 1.735), (4.95, 1.69)],
                   side=(1.34, 4.92), pillars=[(2.30, 2.40, "black"), (3.56, 3.64, "black"), (4.62, 9.0, "black")],
                   tumble_deg=22, sweep_f=0.26, sweep_r=0.06),
        doors=[1.28, 2.36, 3.62], weight=0.08, white_bias=0.10, lamps="square"),
}

DETAIL = {   # zone -> (linear albedo, class)
    "black": ((0.028, 0.028, 0.030), 1), "gap": ((0.008, 0.008, 0.009), 1), "under": ((0.022, 0.022, 0.024), 2),
    "clad": ((0.035, 0.035, 0.037), 1), "grille": ((0.016, 0.016, 0.018), 1), "tyre": ((0.030, 0.030, 0.032), 0),
    "rim": ((0.58, 0.59, 0.61), 3), "rim_dark": ((0.10, 0.10, 0.11), 3), "steel": ((0.03, 0.03, 0.032), 3),
    "disc": ((0.16, 0.16, 0.16), 2), "chrome": ((0.80, 0.80, 0.82), 3),
    "head": ((0.50, 0.52, 0.56), 4), "head_in": ((0.06, 0.065, 0.07), 3), "drl": ((0.90, 0.91, 0.93), 4),
    "tail": ((0.42, 0.012, 0.014), 4), "tail_in": ((0.14, 0.006, 0.008), 4), "amber": ((0.62, 0.22, 0.012), 4),
    "reverse": ((0.75, 0.75, 0.77), 4), "plate": ((0.80, 0.80, 0.78), 5), "plate_txt": ((0.30, 0.025, 0.035), 5),
    "plate_blue": ((0.03, 0.06, 0.25), 5),
}
SLOT = {"paint": 0, "glass": 1}   # everything else -> 2 (detail)


def log(*a):
    print("[parked]", *a, flush=True)


# ------------------------------------------------------------------------------------------------ zoning
def body_zone_fn(s, body, cabin):
    xf = body.xf
    seams = [xf - d for d in s.get("doors", [])]
    hood_seam = cabin.xc + 0.07
    boot_seam = cabin.xrg - 0.03 if s["cabin"]["d_rg"] < s["L"] - 0.3 else None
    clad = s.get("clad")
    bed = s.get("bed")
    j_clad = 99
    if clad:
        half = body.half_section(0.0)
        side = [(k, z) for k, (y, z, kd) in enumerate(half) if kd == "side"]
        j_clad = next((k for k, z in side if z < clad), 99)

    def fn(x, kind, j, side, z):
        if kind == "under":
            return "under"
        a = body.arch(x)
        in_arch = a is not None and a > body.zbot_base(x) + 1e-4
        if kind == "sill":
            return "clad" if clad else ("under" if in_arch else "paint")
        if kind in ("side", "shoulder"):
            if clad and kind == "side" and j >= j_clad:      # follows the side rows (bends up round the arches)
                return "clad"
            if kind == "side" and z > body.s["sill"] - 0.01 and any(abs(x - sx) < 0.001 for sx in seams):
                zb = body.ztop(x) - 0.06
                if z < zb:
                    return "gap"
        if kind == "top":
            if j == 6 and (x > cabin.xc + 0.05 or (boot_seam and x < boot_seam)):
                return "gap"
            if abs(x - hood_seam) < 0.001 or (boot_seam and abs(x - boot_seam) < 0.001):
                return "gap"
            if bed and xf - bed[1] < x < xf - bed[0] and j < 9:
                return "black"       # tonneau cover
        return "paint"
    return fn, seams + [hood_seam] + ([boot_seam] if boot_seam else [])


def cabin_zone_fn(s, cabin):
    c = s["cabin"]
    xf = cabin.body.xf
    sg_f, sg_r = xf - c["side"][0], xf - c["side"][1]
    pillars = [(xf - d1, xf - d0, zn) for d0, d1, zn in c.get("pillars", [])]

    def fn(x, kind, z):
        if kind == "top":
            if cabin.xre < x < cabin.xh:
                return "paint"
            return "glass"
        if kind == "edge":
            return "paint"
        if kind == "side_frame" or kind == "side_seal":
            return "black"
        if kind == "side_glass":
            if x > sg_f:
                return "black"
            if x < sg_r:
                return "paint"
            for a, b, zn in pillars:
                if a < x < b:
                    return zn
            return "glass"
        return "black"
    extra = [sg_f, sg_r] + [v for a, b, _ in pillars for v in (a, b) if abs(v) < 4]
    return fn, extra


# ------------------------------------------------------------------------------------------------ details
def bvh_of(mesh):
    tris = []
    for f in mesh.f:
        tris.append(f[:3])
        if len(f) == 4:
            tris.append((f[0], f[2], f[3]))
    return BVHTree.FromPolygons(mesh.v, tris)


def details(s, body, cabin, shell):
    """Lamps, grille, plates, handles, mirrors, wipers, rails, exhaust, chassis + liners, wheels."""
    m = PG.Mesh()
    bvh = bvh_of(shell)
    B, xf, xr = body.B, body.xf, body.xr
    zhood = body.ztop(xf - 0.25)
    style = s.get("lamps", "sleek")
    FRONT = ((0, 1, 0), (0, 0, 1), (-1, 0, 0))    # U = +Y (left), V = Z, project along -X
    REAR = ((0, -1, 0), (0, 0, 1), (1, 0, 0))

    def ring_zone(inner, outer, n_in=2):
        return lambda ri, r, k: inner if ri < n_in else outer

    # headlamps (left, mirrored)
    if style == "truck":
        hw, hh, hz = 0.30, 0.20, zhood - 0.14
    elif style == "square":
        hw, hh, hz = 0.34, 0.14, zhood - 0.10
    else:
        hw, hh, hz = 0.40, 0.12, zhood - 0.09
    hy = B - 0.06 - hw / 2
    out = PG.rrect(hw, hh, 0.035, skew=0.05 if style == "sleek" else 0.0, taper=0.15 if style == "sleek" else 0.0)
    m.extend(PG.patch(bvh, (0, hy, hz), FRONT, out, 0.004, zone_fn=ring_zone("head_in", "head", 3), mirror_y=True))
    # DRL strip under / along the lamp
    m.extend(PG.patch(bvh, (0, hy - 0.02, hz - hh / 2 - 0.02), FRONT, PG.rrect(hw * 0.8, 0.018, 0.008), 0.004,
                      rings=(0.0, 0.6, 1.0), zone_fn=lambda ri, r, k: "drl", mirror_y=True))
    # grille + lower intake + badge
    gw = 2 * (hy - hw / 2) - 0.06
    gz = hz - (0.02 if style != "truck" else 0.10)
    gh = 0.12 if style != "truck" else 0.30
    m.extend(PG.patch(bvh, (0, 0, gz), FRONT, PG.rrect(gw, gh, 0.03), 0.005, zone_fn=lambda ri, r, k: "grille"))
    m.extend(PG.patch(bvh, (0, 0, gz + 0.004), FRONT, PG.ellipse(0.05, 0.03), 0.009, rings=(0.0, 0.5, 1.0),
                      zone_fn=lambda ri, r, k: "chrome"))
    iz = s["bump_f"] + 0.13
    m.extend(PG.patch(bvh, (0, 0, iz), FRONT, PG.rrect(2 * B * 0.62, 0.12, 0.04, taper=0.06), 0.005,
                      zone_fn=lambda ri, r, k: "grille"))
    # tail lamps
    dz_deck = body.ztop(xr + 0.25)
    if style in ("square", "truck") and s["cabin"]["d_rg"] > s["L"] - 0.35:
        tw_, th_, tz = 0.13, 0.30, dz_deck - 0.18            # tall lamps beside the hatch / tailgate
        ty = B - 0.03 - tw_ / 2
    else:
        tw_, th_, tz = 0.38, 0.13, dz_deck - 0.10
        ty = B - 0.05 - tw_ / 2
    m.extend(PG.patch(bvh, (0, -ty, tz), REAR, PG.rrect(tw_, th_, 0.025), 0.004,
                      zone_fn=lambda ri, r, k: "tail_in" if ri < 2 else ("reverse" if (ri == 2 and k % 7 < 2) else "tail"),
                      mirror_y=True))
    # rear bumper: dark lower valance + reflectors
    m.extend(PG.patch(bvh, (0, 0, s["bump_r"] + 0.07), REAR, PG.rrect(2 * B * 0.55, 0.09, 0.03), 0.005,
                      zone_fn=lambda ri, r, k: "black"))
    # plates (US 12 x 6 in), front on the bumper, rear on the boot / tailgate
    def plate(x_sign, z):
        D = (-x_sign, 0, 0)
        hit = bvh.ray_cast((x_sign * 4.0, 1.7e-4, z), D, 6.0)
        if hit[0] is None:
            return
        p, n = hit[0], hit[1]
        n = n.normalized()
        nx = n.x if abs(n.x) > 0.3 else x_sign
        V, F, Z = [], [], []
        w, h, nu, nv = 0.305, 0.152, 30, 14
        cx = p.x + x_sign * 0.009
        for i in range(nv + 1):
            for j in range(nu + 1):
                V.append((cx, x_sign * (-w / 2 + w * j / nu), p.z - h / 2 + h * i / nv))
        # 6 made-up glyphs (3 x 5 cells, no real characters), a thin red header line, white field
        glyphs = [0b111101101101111, 0b010110010010111, 0b111001111100111, 0b111001011001111, 0b101101111001001,
                  0b111100111001111, 0b111100111101111, 0b111001010010010]
        for i in range(nv):
            for j in range(nu):
                f = (i * (nu + 1) + j, i * (nu + 1) + j + 1, (i + 1) * (nu + 1) + j + 1, (i + 1) * (nu + 1) + j)
                F.append(f)
                zn = "plate"
                gi, gj = 9 - i, j - 3                 # glyph rows 9..5 (top down), columns from 3
                if 0 <= gi < 5 and 0 <= gj < 24 and gj % 4 != 3:
                    g = glyphs[(gj // 4 * 3 + int(abs(p.z) * 100)) % len(glyphs)]
                    bit = 14 - (gi * 3 + gj % 4)
                    if (g >> bit) & 1:
                        zn = "plate_txt"
                if i == nv - 2 and 9 <= j <= 20:
                    zn = "plate_txt"
                if i == 1 and 11 <= j <= 18:
                    zn = "plate_blue"
                Z.append(zn)
        pm = PG.Mesh()
        pm.add(V, F, Z)
        # back + rim (thin box behind the face)
        m.extend(pm)
        m.extend(PG.box((p.x + x_sign * 0.003, 0, p.z), (0.010, w + 0.006, h + 0.006), "black"))
    plate(1, s["bump_f"] + 0.24)
    plate(-1, (dz_deck - 0.24) if s["cabin"]["d_rg"] > s["L"] - 0.35 or s.get("bed") else s["bump_r"] + 0.28)
    # door handles (left, mirrored)
    SIDE = ((1, 0, 0), (0, 0, 1), (0, -1, 0))
    for dseam in s.get("doors", [])[1:3]:
        hx = xf - dseam + 0.16
        hz_ = body.ztop(hx) - 0.09
        m.extend(PG.patch(bvh, (hx, 0, hz_), SIDE, PG.rrect(0.15, 0.028, 0.012), 0.006, rings=(0.0, 0.5, 1.0),
                          zone_fn=lambda ri, r, k: "black", mirror_y=True))
    # side mirrors (housing painted, stalk black)
    mx = cabin.xc - 0.16
    zb_ = body.ztop(mx) - s.get("crown", 0.035)
    mz = zb_ + 0.075
    yb = body.plan(mx) - s.get("tumble", 0.045)
    for sg in (1, -1):
        m.extend(PG.rounded_box((mx, sg * (yb + 0.10), mz), (0.13, 0.17, 0.115), 0.03, "paint"))
        m.extend(PG.box((mx + 0.015, sg * (yb - 0.03), zb_ + 0.03), (0.09, 0.20, 0.06), "black"))
        m.extend(PG.box((mx - 0.064, sg * (yb + 0.10), mz), (0.004, 0.14, 0.085), "chrome"))
    # wipers on the windshield base
    for yy in (0.32, -0.28):
        x0 = cabin.xc - 0.10
        m.extend(PG.box((x0, yy, cabin.zroof(x0) + 0.012), (0.035, 0.60, 0.012), "black", rot_z=0.08))
    # roof rails
    if s.get("rails"):
        x0, x1 = cabin.xh - 0.25, cabin.xre + 0.15
        yr = cabin.width_base(0.5 * (x0 + x1)) - (cabin.zroof(0.5 * (x0 + x1)) - cabin.zbase(0.5 * (x0 + x1))) * cabin.tumble - 0.12
        for sg in (1, -1):
            zr = max(cabin.zroof(x) for x in (x0, x1, 0.5 * (x0 + x1))) + 0.035
            m.extend(PG.box((0.5 * (x0 + x1), sg * yr, zr), (x0 - x1, 0.035, 0.03), "black"))
            for xx in (x0 - 0.05, x1 + 0.05):
                m.extend(PG.box((xx, sg * yr, zr - 0.025), (0.08, 0.04, 0.05), "black"))
    # exhaust tip
    ex = PG.lathe([(0.03, 0.0), (0.03, 0.12), (0.024, 0.12)], 16, lambda j, k: "chrome")
    ex.v = [(xr + 0.06 - y, -B * 0.45 + x, s["bump_r"] - 0.02 + z) for x, y, z in ex.v]
    m.extend(ex)
    # chassis block (hides the arch tunnels from below / through the arches) and wheel-well liners
    ya = B - 0.34
    x0, x1 = body.axles[1] - body.Ra - 0.05, body.axles[0] + body.Ra + 0.05
    zc0 = s["sill"] - 0.035
    m.extend(PG.box((0.5 * (x0 + x1), 0, 0.5 * (zc0 + body.zw + body.Ra - 0.06)), (x1 - x0, 2 * ya, body.zw + body.Ra - 0.06 - zc0), "under"))
    track = s.get("track", 2 * B - s["tw"] - 0.05)
    for xa in body.axles:
        for sg in (1, -1):
            m.extend(PG.liner(xa, body.zw, body.Ra, B + 0.01, ya, sg))
            m.extend(PG.wheel(s, (xa, sg * track / 2, body.zw), sg))
    return m


# ------------------------------------------------------------------------------------------------ assembly
def build_car(name, s):
    t0 = time.time()
    body = PG.Body(s)
    cabin = PG.Cabin(s, body)
    bfn, bextra = body_zone_fn(s, body, cabin)
    seam_st = [v for x in bextra for v in (x - 0.003, x + 0.003)]
    lower, _ = body.build(bfn, extra_stations=[cabin.xc, cabin.xrg], guarded=seam_st)
    cfn, cextra = cabin_zone_fn(s, cabin)
    upper, _ = cabin.build(cfn, extra=cextra)
    shell = PG.Mesh()
    shell.extend(lower)
    shell.extend(upper)
    det = details(s, body, cabin, shell)
    car = PG.Mesh()
    car.extend(shell)
    car.extend(det)
    ob = to_blender(name, car)
    log(f"{name}: {len(car.v)} verts, {len(car.f)} faces, built in {time.time() - t0:.1f} s")
    return ob, body, cabin


def materials():
    mats = []
    for nm, col in (("parked_paint", (0.5, 0.5, 0.5)), ("parked_glass", (0.01, 0.012, 0.014)), ("parked_detail", (0.1, 0.1, 0.1))):
        m = bpy.data.materials.get(nm) or bpy.data.materials.new(nm)
        m.diffuse_color = (*col, 1.0)
        mats.append(m)
    return mats


def to_blender(name, car):
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in car.v]
    bm.verts.ensure_lookup_table()
    zl = bm.faces.layers.int.new("zone")
    znames = sorted(set(car.z))
    zid = {z: i for i, z in enumerate(znames)}
    for fc, zn in zip(car.f, car.z):
        try:
            f = bm.faces.new([vs[i] for i in fc])
        except ValueError:
            continue
        f[zl] = zid[zn]
        f.material_index = SLOT.get(zn, 2)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in materials():
        me.materials.append(m)
    # corner colours: zone albedo / class (detail) or white (paint, glass)
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
    zattr = me.attributes["zone"].data
    cols = []
    for p in me.polygons:
        zn = znames[zattr[p.index].value]
        if zn in DETAIL:
            rgb, k = DETAIL[zn]
            c = (*rgb, k / 5.0)
        else:
            c = (1.0, 1.0, 1.0, 1.0)
        cols += [c] * p.loop_total
    flat = [v for c in cols for v in c]
    ca.data.foreach_set("color", flat)
    me.color_attributes.active_color = ca
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    for p in me.polygons:
        p.use_smooth = True
    me.set_sharp_from_angle(angle=math.radians(38))
    uv = me.uv_layers.new(name="UVMap")
    co = [0.0] * (len(me.loops) * 2)
    for l in me.loops:
        v = me.vertices[l.vertex_index].co
        co[2 * l.index], co[2 * l.index + 1] = v.x, v.z
    uv.data.foreach_set("uv", co)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def bake_ao(ob, samples=48):
    """Cycles AO -> a corner colour attribute, multiplied into Col (paint/glass: RGB = AO; detail: albedo x AO)."""
    me = ob.data
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.device = "CPU"
    ground = bpy.data.objects.get("ao_ground")
    if ground is None:
        gm = bpy.data.meshes.new("ao_ground")
        gm.from_pydata([(-8, -8, 0), (8, -8, 0), (8, 8, 0), (-8, 8, 0)], [], [(0, 1, 2, 3)])
        ground = bpy.data.objects.new("ao_ground", gm)
    if ground.name not in sc.collection.objects:
        sc.collection.objects.link(ground)
    ao = me.color_attributes.new("AO", "FLOAT_COLOR", "CORNER")
    me.color_attributes.active_color = ao
    for m in me.materials:      # bake target: active colour attribute (no image needed)
        m.use_nodes = True
    for o in sc.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    sc.render.bake.target = "VERTEX_COLORS"
    sc.render.bake.use_selected_to_active = False
    sc.world = sc.world or bpy.data.worlds.new("w")
    sc.world.light_settings.distance = 1.5
    bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
    n = len(me.loops)
    a = [0.0] * (n * 4)
    ao.data.foreach_get("color", a)
    col = me.color_attributes["Col"]
    c = [0.0] * (n * 4)
    col.data.foreach_get("color", c)
    mi = [0] * n
    for p in me.polygons:
        for li in p.loop_indices:
            mi[li] = p.material_index
    for i in range(n):
        occ = a[4 * i]
        occ = 0.18 + 0.82 * occ                      # never fully black (Lumen adds its own occlusion)
        if mi[i] == 2:
            occ = 0.35 + 0.65 * occ
        for k in range(3):
            c[4 * i + k] *= occ
    col.data.foreach_set("color", c)
    aa = a[0::4]
    log(f"AO: min {min(aa):.2f} mean {sum(aa) / len(aa):.2f} over {n} corners")
    me.color_attributes.remove(ao)
    me.color_attributes.active_color = me.color_attributes["Col"]
    sc.collection.objects.unlink(ground)


def export(ob, path):
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=False,
                              export_yup=True, export_normals=True, export_texcoords=True, export_tangents=False,
                              export_materials="EXPORT", export_image_format="NONE", export_cameras=False,
                              export_lights=False, export_vertex_color="ACTIVE", export_all_vertex_colors=False,
                              export_attributes=False)


def collision_box(s):
    """Simple box (cm, mesh space): body length x width, from 8 cm above the ground to the roof."""
    L, W, H = s["L"], s["W"], s["H"] - (0.05 if s.get("rails") else 0.0)
    z0 = 0.08
    return {"centre_cm": [0.0, 0.0, round(100 * (z0 + H) / 2, 1)],
            "size_cm": [round(100 * (L - 0.04), 1), round(100 * (W - 0.02), 1), round(100 * (H - z0), 1)]}


def main():
    t0 = time.time()
    want = OPT.get("--types")
    names = [n for n in FLEET if not want or n in want.split(",")]
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    meta = {"generator": "tools/blender/parked_cars.py (parked_geom.py)", "frame": "X forward, Y left, Z up, ground z=0, "
            "origin at the footprint centre (glTF +Y up; Unreal +X forward)", "slots": ["parked_paint", "parked_glass", "parked_detail"],
            "detail_classes": "k = round(COLOR_0.a * 5): 0 rubber, 1 black plastic, 2 dark metal, 3 alloy/chrome, 4 lamp lens, 5 plate",
            "types": {}}
    jp = OUT / "parked_cars.json"
    if jp.exists() and want:
        meta["types"] = json.loads(jp.read_text()).get("types", {})
    for name in names:
        s = FLEET[name]
        ob, body, cabin = build_car(f"parked_{name}", s)
        if not OPT.get("--no-ao"):
            t1 = time.time()
            bake_ao(ob)
            log(f"{name}: AO baked in {time.time() - t1:.0f} s")
        path = OUT / f"parked_{name}.glb"
        export(ob, path)
        me = ob.data
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        zs = [v.co.z for v in me.vertices]
        meta["types"][name] = {"file": str(path.relative_to(ROOT)), "length_m": s["L"], "width_m": s["W"], "height_m": s["H"],
                               "wheelbase_m": s["wb"], "bounds_m": [[round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
                                                                    [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)]],
                               "triangles": sum(len(p.vertices) - 2 for p in me.polygons),
                               "collision": collision_box(s), "weight": s["weight"], "white_bias": s["white_bias"]}
        log(f"{name}: {meta['types'][name]['triangles']} tris, bounds {meta['types'][name]['bounds_m']} -> {path.name}")
        if not OPT.get("--keep"):
            bpy.data.objects.remove(ob)
    jp.write_text(json.dumps(meta, indent=2))
    log(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
