"""Build the player car: 2002 Subaru Impreza WRX STi (GDB-B "bugeye") in the WRC-style livery.

Run (headless, deterministic, ~10 s):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/build_sti.py
Optional args after "--":  --no-livery  (reuse the existing livery PNGs)   --render  (then run render_sti.py)
Needs `uv` on PATH: the livery is drawn with PIL by tools/blender/sti_livery.py in the tools/mapgen environment.

Pipeline (modules in tools/blender/):
    sti_body.py      quad control cage (stations x rows, left half) -> Mirror -> Subdivision Surface (level 3) with
                     creases; openings cut with exact booleans (arches, bugeye lamps, tail lamps, grille, intake,
                     fog pockets, plate recess) + return flanges; split into paint / glass / trim + window rubbers
    sti_details.py   lamps (domed lenses, reflectors, projectors), honeycomb mesh, badge, fog lamps, lip, scoop,
                     cowl, wipers, mirrors, handles, markers, wing (+ stop lamp), exhaust, liners, under-tray,
                     antenna, 3D STi/WRX badges, intake bar, skirt lips, diffuser strakes, underbody mechanicals
    sti_wheels.py    tyre, gold 5-twin-spoke rim, drilled/slotted disc, Brembo-style caliper (wheel-local)
    sti_interior.py  liner, dash, RHD steering wheel, seats, console
    sti_driver.py    static driver in the RHD seat: suit, gloves, harness, helmet + visor
    sti_uv.py        paint UV0 (planar islands), panel lines, livery generation, smooth-normal transfer
    render_sti.py    validation renders from the exported .glb files

Outputs (data/processed/common/car/):
    sti_<part>.glb       one mesh, one material slot (named sti_<part>), NORMAL + TEXCOORD_0, per part
    sti_parts.json       material spec per part, read by the game's import step
    sti_livery.png       4096^2 sRGB paint colour (UV0 of sti_paint)
    sti_paint_normal.png 4096^2 tangent-space normal map, OpenGL convention (+Y up): panel gaps, handle recesses
    renders/*.png        (render_sti.py) validation renders

Frame: Blender metres, X = car forward, Y = car LEFT, Z = up; glTF export maps it to (x, z, -y), the same as
the old tools/mapgen/gltf.py. Origin = vehicle mesh root; ground at z = -0.086; axles x = 1.2915 / -1.2335.
Wheel parts (tire, rim, brake, caliper) are modelled at the origin, axle along Y, outer face toward +Y.
"""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for m in [k for k in sys.modules if k.startswith("sti_")]:
    del sys.modules[m]
import sti_body  # noqa: E402
import sti_details  # noqa: E402
import sti_driver  # noqa: E402
import sti_interior  # noqa: E402
import sti_uv  # noqa: E402
import sti_wheels  # noqa: E402
from sti_common import G, Parts, evaluated_mesh, new_object, remove, tri_count  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "data/processed/common/car"
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

# Material spec per part (linear colours). The game builds its materials from sti_parts.json.
SPEC = {
    "paint": dict(texture="sti_livery.png", normal_texture="sti_paint_normal.png", ao_texture="sti_paint_ao.png",
                  mask_texture="sti_paint_mask.png", metallic=0.12, roughness=0.14,
                  clearcoat=1.0, clearcoat_roughness=0.015,
                  notes="WR Blue Mica + livery from the texture (UV0). Clear-coated car paint. Normal map is OpenGL "
                        "(+Y/green up, flip green for Unreal) and only carries the subtle vinyl-decal edges (panel "
                        "gaps are geometry). ao_texture: baked ambient occlusion of the whole car on UV0, linear "
                        "grey, 1 = open, multiply into diffuse + specular occlusion. mask_texture: linear grey, "
                        "1 = vinyl decal (yellow swoosh, stars, lettering), 0 = painted body; use it e.g. for a "
                        "slightly rougher, flake-free decal vs the metallic-flake paint."),
    "glass": dict(base_color=[0.006, 0.007, 0.008], metallic=0.0, roughness=0.03, opacity=0.55,
                  notes="Tinted window glass, translucent (two-sided not needed). Interior visible through it."),
    "black": dict(base_color=[0.011, 0.011, 0.012], metallic=0.0, roughness=0.42,
                  notes="Black plastics: window rubber, B-pillar, grille surround, lip, skirts trim, mirror stalks, "
                        "wipers, wheel-well liners, lamp housings."),
    "mesh": dict(base_color=[0.012, 0.012, 0.013], metallic=0.3, roughness=0.45,
                 notes="Honeycomb grille / intake mesh (real geometry, opaque)."),
    "lens": dict(base_color=[0.92, 0.94, 0.96], metallic=0.0, roughness=0.02, opacity=0.12,
                 notes="Clear headlamp / fog-lamp covers. Translucent; the chrome reflectors are behind it."),
    "red": dict(base_color=[0.36, 0.004, 0.006], metallic=0.0, roughness=0.05, emissive=[0.16, 0.0, 0.0],
                notes="Tail-lamp lenses (opaque, deep glossy red; the lens carries raised rings and the reverse "
                      "lamp is a separate clear section). Slight emissive glow; raise it for brake lights."),
    "amber": dict(base_color=[0.85, 0.30, 0.02], metallic=0.0, roughness=0.15, emissive=[0.05, 0.015, 0.0],
                  notes="Side markers / indicators."),
    "chrome": dict(base_color=[0.92, 0.92, 0.94], metallic=1.0, roughness=0.08,
                   notes="Lamp reflectors, exhaust tip, badges, mirror glass."),
    "plate": dict(texture="sti_plate.png", normal_texture="sti_plate_normal.png", metallic=0.1, roughness=0.35,
                  notes="US-size (12x6 in) licence plates, front and rear; fictional artwork. UV0 maps the plate "
                        "face to the whole texture (other faces map inside it too, plain white border). Normal map "
                        "OpenGL: raised characters and stamped rim."),
    "under": dict(base_color=[0.045, 0.045, 0.048], metallic=0.6, roughness=0.62,
                  notes="Underbody metal: sump, gearbox, driveshaft, fuel tank, differential, arms, exhaust pipe, "
                        "silencer (visible from low angles)."),
    "badge": dict(base_color=[0.80, 0.06, 0.22], metallic=0.3, roughness=0.25,
                  notes="Pink STi badges (boot and grille)."),
    "interior": dict(base_color=[0.028, 0.028, 0.032], metallic=0.0, roughness=0.85,
                     notes="Dark interior: dash, seats, door cards, headliner, steering wheel."),
    "driver_suit": dict(base_color=[0.012, 0.075, 0.42], metallic=0.0, roughness=0.80,
                        notes="Driver race suit (Nomex blue) + helmet stripe. Static, sits in the RHD driver seat."),
    "driver_helmet": dict(texture="sti_helmet.png", metallic=0.0, roughness=0.10, clearcoat=1.0,
                          clearcoat_roughness=0.02,
                          notes="Glossy painted helmet shell (white / blue / gold livery from the texture on UV0)."),
    "driver_visor": dict(base_color=[0.012, 0.014, 0.018], metallic=0.0, roughness=0.03, opacity=0.85,
                         notes="Dark-smoked visor: glossy, slightly translucent (the dark padding cavity behind "
                               "the eyeport shows faintly)."),
    "rim": dict(base_color=[0.78, 0.58, 0.26], metallic=1.0, roughness=0.32,
                notes="Gold 17-inch 5-twin-spoke wheel. Wheel part: centred at origin, axle Y, outer face +Y."),
    "tire": dict(base_color=[0.028, 0.028, 0.030], metallic=0.0, roughness=0.88, normal_texture="sti_tire_normal.png",
                 notes="225/45R17 tyre with tread and sidewall detail. Wheel part (spins)."),
    "brake": dict(base_color=[0.36, 0.36, 0.37], metallic=1.0, roughness=0.42,
                  notes="Drilled/slotted disc + hat. Wheel part (spins with the wheel)."),
    "caliper": dict(base_color=[0.80, 0.55, 0.10], metallic=0.0, roughness=0.35,
                    notes="Gold Brembo-style caliper. Wheel-local like the others but must NOT spin: attach to the "
                          "wheel hub/knuckle (steers with the wheel, no rotation about the axle)."),
}
WHEEL_PARTS = ("rim", "tire", "brake", "caliper")


def log(*a):
    print("[build_sti]", *a, flush=True)


def material(part):
    m = bpy.data.materials.get("sti_" + part) or bpy.data.materials.new("sti_" + part)
    s = SPEC[part]
    m.diffuse_color = (*s.get("base_color", [0.05, 0.12, 0.45]), 1.0)
    return m


def export_part(part, me):
    ob = new_object("sti_" + part, me)
    me.materials.clear()
    me.materials.append(material(part))
    for o in bpy.context.scene.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    path = OUT / f"sti_{part}.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=False,
                              export_yup=True, export_normals=True, export_texcoords=True, export_tangents=False,
                              export_materials="EXPORT", export_cameras=False, export_lights=False,
                              export_vertex_color="NONE", export_attributes=False)
    return ob


def self_check():
    """Print (do not assert) the constraints the game relies on."""
    for ob in sorted((o for o in bpy.context.scene.objects if o.name.startswith("sti_") and o.type == "MESH"),
                     key=lambda o: o.name):
        part = ob.name[4:].split(".")[0]
        if part not in SPEC:
            continue
        me = ob.data
        if not me.vertices:
            continue
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        zs = [v.co.z for v in me.vertices]
        mats = len(me.materials)
        uv = len(me.uv_layers)
        if part in WHEEL_PARTS:
            cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
            ok = (abs(cx) < 0.005 and abs(cz) < 0.005) or part == "caliper"
            log(f"check {part:9s} wheel-local: centre x {cx:+.4f} z {cz:+.4f}, y {min(ys):+.3f}..{max(ys):+.3f} "
                f"(outer face +Y) mats={mats} uv={uv} {'OK' if ok and mats == 1 else 'CHECK'}")
        else:
            h = min(zs) - G
            ok = h >= 0.169
            log(f"check {part:9s} lowest point {h:.3f} m above ground, x {min(xs):+.3f}..{max(xs):+.3f} "
                f"y {min(ys):+.3f}..{max(ys):+.3f} z top {max(zs) - G:.3f} mats={mats} uv={uv} "
                f"{'OK' if ok and mats == 1 else 'CHECK'}")


def bake_ao(res=2048, samples=96):
    """Bake ambient occlusion of the whole car (all exported parts + the four wheel sets) into the paint UV0.
    Writes sti_paint_ao.png (linear grey, 1 = open). Cycles, fixed seed: deterministic per device."""
    import numpy as np
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = "GPU"
    except Exception:
        sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.seed = 7
    if sc.world is None:
        sc.world = bpy.data.worlds.new("w")
    sc.world.light_settings.distance = 0.35
    paint = bpy.data.objects.get("sti_paint")
    # wheel instances as occluders
    for part in WHEEL_PARTS:
        ob = bpy.data.objects.get("sti_" + part)
        if ob is None:
            continue
        for xa, ty in ((1.2915, 0.7425), (-1.2335, 0.745)):
            for side in (1, -1):
                o = ob.copy()
                sc.collection.objects.link(o)
                o.matrix_world = Matrix.Translation((xa, side * ty, 0.231)) @ Matrix.Diagonal((1, side, 1, 1))
        ob.hide_render = True
    img = bpy.data.images.new("sti_paint_ao", res, res, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    mat = bpy.data.materials.new("bake_ao")
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    paint.data.materials.clear()
    paint.data.materials.append(mat)
    for o in sc.objects:
        o.select_set(False)
    paint.select_set(True)
    bpy.context.view_layer.objects.active = paint
    t = time.time()
    bpy.ops.object.bake(type="AO", margin=6, use_clear=True)
    px = np.array(img.pixels[:], np.float32).reshape(res, res, 4)[..., 0]
    # soften the shadows a little (it is multiplied into a glossy car paint) and keep the hidden patch white
    px = 0.25 + 0.75 * np.clip(px, 0, 1)
    k = res / sti_uv.TEX
    px[: int(48 * k), -int(48 * k):] = 1.0       # (rows are bottom-up in Blender images: bottom-right corner)
    rgba = np.dstack([px, px, px, np.ones_like(px)]).ravel()
    out = bpy.data.images.new("ao_out", res, res, alpha=False)
    out.colorspace_settings.name = "Non-Color"
    out.pixels[:] = rgba
    out.filepath_raw = str(OUT / "sti_paint_ao.png")
    out.file_format = "PNG"
    out.save()
    log("AO baked", round(time.time() - t, 1), "s")


def gap_cutters(bvh):
    """Real panel gaps: a thin tube along every shut line (the boolean keeps the tube wall as the dark gap
    interior), and ellipsoid dishes for the door-handle recesses."""
    import math
    from sti_driver import tube
    grooves = []
    for line in sti_uv.panel_lines(bvh):
        pts = [Vector(p) - Vector(n) * 0.0006 for p, n in line["pts"]]
        res = [pts[0]]
        for p in pts[1:]:
            if (p - res[-1]).length >= 0.016:
                res.append(p)
        if (pts[-1] - res[-1]).length > 0.003:
            res.append(pts[-1])
        if len(res) >= 2:
            grooves.append(tube(res, [0.0026] * len(res), 6))
    recesses = []
    for side in (1, -1):
        for hx, hh in sti_uv.handles():
            loc, n, i, d = bvh.ray_cast(Vector((hx, side * 3.0, hh + G)), Vector((0, -side, 0)))
            if loc is None:
                continue
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
            nn = Vector((0, n.y, 0)).normalized()
            M = Matrix.Translation(loc - nn * 0.009) @ Matrix.Diagonal((0.075, 0.022, 0.028, 1.0))
            bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
            recesses.append(bm)
    return grooves, recesses


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = Parts()

    # --- body shell ------------------------------------------------------------------------------
    skin = sti_body.body_skin()
    src_me = skin.data.copy()
    src_bm = bmesh.new()
    src_bm.from_mesh(src_me)
    src_bvh = BVHTree.FromBMesh(src_bm)
    grooves, recesses = gap_cutters(src_bvh)
    skin, flanges, patches = sti_body.cut_body(skin, grooves, recesses)
    split = sti_body.split_skin(skin, src_bvh)
    remove(skin)
    log("body cut", round(time.time() - t0, 1), "s")

    # paint = skin + paint flanges; mark skin verts for the normal transfer
    paint = split["paint"]
    sl = paint.verts.layers.int.new("skin")
    pz = paint.faces.layers.int.get("zone")
    for v in paint.verts:
        v[sl] = 0 if any(f[pz] == 3 for f in v.link_faces) else 1   # recess dishes keep their own normals
    pl = paint.faces.layers.int.new("proj")                         # body-skin faces get projected UVs
    for f in paint.faces:
        f[pl] = 1
    fz = flanges.faces.layers.int.get("zone")
    fl_paint = flanges.copy()
    bmesh.ops.delete(fl_paint, geom=[f for f in fl_paint.faces if f[fl_paint.faces.layers.int.get("zone")] != 0], context="FACES")
    fl_black = flanges.copy()
    bmesh.ops.delete(fl_black, geom=[f for f in fl_black.faces if f[fl_black.faces.layers.int.get("zone")] == 0], context="FACES")
    flanges.free()
    parts.add("paint", paint)
    parts.add("paint", fl_paint, smooth=50)
    parts.add("glass", split["glass"], smooth=180)
    parts.add("black", split["black"], smooth=180)
    parts.add("black", split["rubber"], smooth=60)
    parts.add("black", split["frit"], smooth=60)
    parts.add("black", fl_black, smooth=50)

    # --- details, lamps, wheels -----------------------------------------------------------------
    sti_details.build(parts, src_bvh, patches)
    sti_wheels.build(parts)
    lo = sti_body.body_skin(levels=1)
    lo_bm = bmesh.new()
    lo_bm.from_mesh(lo.data)
    remove(lo)
    sti_interior.build(parts, lo_bm)
    sti_driver.build(parts)
    lo_bm.free()
    log("details", round(time.time() - t0, 1), "s")

    # --- export ------------------------------------------------------------------------------------
    subprocess.run(["uv", "run", "--project", str(ROOT / "tools/mapgen"), "python", str(HERE / "sti_textures.py"),
                    str(OUT)], check=True)
    report = {}
    for part in list(parts.bm):
        me = parts.mesh(part)
        if part == "paint":
            me = sti_uv.finish_paint(me, src_me, OUT, ARGS)
        elif part == "tire":
            sti_wheels.tire_uv(me)
        elif part in ("plate", "driver_helmet"):
            sti_uv.keep_uv0(me)
        else:
            sti_uv.box_uv(me)
        ob = export_part(part, me)
        report[part] = tri_count(me)
        log(f"sti_{part}.glb", report[part], "tris")
    spec = []
    for part in parts.bm:
        s = dict(part=part, file=f"sti_{part}.glb", **SPEC[part])
        if part in WHEEL_PARTS:
            s["wheel"] = True
            s["spins"] = part != "caliper"
        spec.append(s)
    (OUT / "sti_parts.json").write_text(json.dumps(dict(
        frame="Blender: X forward, Y left, Z up, metres; glTF default export (x, z, -y). Ground z=-0.086.",
        axles=dict(front_x=1.2915, rear_x=-1.2335, wheel_y_front=0.7425, wheel_y_rear=0.745, wheel_z=0.231),
        uv="UV0 only. sti_paint UV0 maps sti_livery.png / sti_paint_normal.png (planar projection islands; the "
           "normal map is OpenGL +Y, flip green for Unreal). Paint pieces that are not body skin (wing, mirrors, "
           "scoop, handles, flanges) map to a small plain-blue patch of the atlas. Other parts: box-projected UV0, "
           "no textures.",
        triangles=report, total_triangles=sum(report.values()), parts=spec), indent=1))
    log("total", sum(report.values()), "tris (each part once);", round(time.time() - t0, 1), "s")
    wheel = sum(report.get(p, 0) for p in WHEEL_PARTS)
    log("in game (4 wheel sets):", sum(report.values()) + 3 * wheel, "tris")
    if "--no-ao" not in ARGS:
        bake_ao()
    self_check()
    if "--render" in ARGS:
        subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "-P", str(HERE / "render_sti.py")], check=True)


main()
