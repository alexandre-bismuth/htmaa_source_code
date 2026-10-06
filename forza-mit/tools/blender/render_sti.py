"""Validation renders of the exported STi: imports the .glb parts exactly as the game gets them, builds the
materials from sti_parts.json, places the wheels (right side mirrored), renders with EEVEE.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/render_sti.py [-- names]
names: comma list of shots (default all): f34, r34, side, front, rear, wheel, nose, tail, top, low, studio
Writes data/processed/common/car/renders/<shot>.png (1600x900).
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
CAR = ROOT / "data/processed/common/car"
OUTD = CAR / "renders"
HDRI = ROOT / "data/raw/hdri"
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WANT = set(ARGS[0].split(",")) if ARGS and not ARGS[0].startswith("-") else None
G = -0.086
WHEELS = [(1.2915, 0.7425), (-1.2335, 0.745)]
WHEEL_Z = 0.231


def principled(name, spec):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    if "texture" in spec:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(CAR / spec["texture"]))
        col = t.outputs["Color"]
        if "ao_texture" in spec and (CAR / spec["ao_texture"]).exists():
            a = nt.nodes.new("ShaderNodeTexImage")
            a.image = bpy.data.images.load(str(CAR / spec["ao_texture"]))
            a.image.colorspace_settings.name = "Non-Color"
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            nt.links.new(col, mix.inputs["A"])
            nt.links.new(a.outputs["Color"], mix.inputs["B"])
            col = mix.outputs["Result"]
        nt.links.new(col, p.inputs["Base Color"])
    else:
        p.inputs["Base Color"].default_value = (*spec["base_color"], 1)
    if "normal_texture" in spec:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(CAR / spec["normal_texture"]))
        t.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    p.inputs["Metallic"].default_value = spec.get("metallic", 0)
    p.inputs["Roughness"].default_value = spec.get("roughness", 0.5)
    if spec.get("clearcoat"):
        p.inputs["Coat Weight"].default_value = spec["clearcoat"]
        p.inputs["Coat Roughness"].default_value = spec.get("clearcoat_roughness", 0.03)
    if "emissive" in spec:
        p.inputs["Emission Color"].default_value = (*spec["emissive"], 1)
        p.inputs["Emission Strength"].default_value = 1.0
    if "opacity" in spec:
        p.inputs["Alpha"].default_value = spec["opacity"]
        m.surface_render_method = "BLENDED"
        m.use_backface_culling = False
    return m


def import_part(part):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(CAR / f"sti_{part}.glb"))
    obs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    return obs[0]


def look(cam, loc, tgt, lens):
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    spec = json.loads((CAR / "sti_parts.json").read_text())
    clay = "--clay" in ARGS
    for s in spec["parts"]:
        if "noglass" in ARGS and s["part"] == "glass":
            continue
        if clay and s["part"] == "paint":
            s = dict(base_color=[0.5, 0.5, 0.52], metallic=0.0, roughness=0.25, clearcoat=1.0, part="paint")
        mat = principled("M_" + s["part"], s)
        ob = import_part(s["part"])
        ob.data.materials.clear()
        ob.data.materials.append(mat)
        if s.get("wheel"):
            for xa, ty in WHEELS:
                for side in (1, -1):
                    o = ob.copy()
                    sc.collection.objects.link(o)
                    if s["part"] == "tire" and side < 0:      # rotate (not mirror) so sidewall text reads
                        o.matrix_world = Matrix.Translation((xa, side * ty, WHEEL_Z)) @ Matrix.Rotation(math.pi, 4, "Z")
                    else:
                        o.matrix_world = Matrix.Translation((xa, side * ty, WHEEL_Z)) @ Matrix.Diagonal((1, side, 1, 1))
            bpy.data.objects.remove(ob)
    # ground + world
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, G))
    gm = bpy.data.materials.new("ground")
    gm.use_nodes = True
    gp = gm.node_tree.nodes["Principled BSDF"]
    gp.inputs["Base Color"].default_value = (0.20, 0.20, 0.205, 1)
    gp.inputs["Roughness"].default_value = 0.7
    bpy.context.object.data.materials.append(gm)
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    if "--sky" in ARGS:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(str(HDRI / "kloofendal_48d_partly_cloudy_puresky_2k.hdr"))
        mapping = nt.nodes.new("ShaderNodeMapping")
        coord = nt.nodes.new("ShaderNodeTexCoord")
        mapping.inputs["Rotation"].default_value = (0, 0, math.radians(135))
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], nt.nodes["Background"].inputs["Color"])
    else:
        # neutral studio: smooth grey gradient dome (no patterned softboxes) + three large soft area lights
        coord = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.10, 0.10, 0.105, 1)
        ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[1].color = (0.85, 0.86, 0.88, 1)
        nt.links.new(ramp.outputs["Color"], nt.nodes["Background"].inputs["Color"])
        for name, loc, size, power in (("key", (2.5, 3.0, 4.5), (5.0, 2.5), 1500), ("fill", (-3.5, -3.0, 3.5), (5.0, 2.5), 700),
                                       ("top", (0.0, 0.0, 5.0), (6.0, 3.0), 900)):
            ld = bpy.data.lights.new(name, "AREA")
            ld.shape = "RECTANGLE"
            ld.size, ld.size_y = size
            ld.energy = power
            lo = bpy.data.objects.new(name, ld)
            sc.collection.objects.link(lo)
            lo.location = loc
            lo.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    nt.nodes["Background"].inputs["Strength"].default_value = 1.0

    sc.render.engine = "BLENDER_EEVEE"
    if "cyc" in ARGS:
        sc.render.engine = "CYCLES"
        try:
            pr = bpy.context.preferences.addons["cycles"].preferences
            pr.compute_device_type = "METAL"
            pr.get_devices()
            for d in pr.devices:
                d.use = True
            sc.cycles.device = "GPU"
        except Exception:
            pass
        sc.cycles.samples = 64
        sc.cycles.use_denoising = True
    ee = sc.eevee
    ee.taa_render_samples = 64
    for attr, val in (("use_raytracing", True), ("use_shadows", True), ("use_gtao", True)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.render.resolution_x, sc.render.resolution_y = 1600, 900
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    shots = {
        "f34": ((5.4, 4.3, 1.25), (0.1, 0, 0.42), 50),
        "r34": ((-5.4, 4.3, 1.45), (-0.1, 0, 0.45), 50),
        "side": ((0.0, 8.5, 0.62), (0.0, 0, 0.5), 50),
        "front": ((6.8, 0.0, 0.75), (0, 0, 0.45), 55),
        "rear": ((-6.8, 0.0, 0.95), (0, 0, 0.5), 55),
        "wheel": ((2.45, 1.85, 0.45), (1.29, 0.74, 0.22), 50),
        "nose": ((3.6, 1.8, 1.0), (1.9, 0.25, 0.55), 45),
        "tail": ((-3.7, 2.0, 1.2), (-1.9, 0.2, 0.75), 45),
        "top": ((2.5, 3.2, 3.6), (0, 0, 0.6), 40),
        "low": ((3.2, 3.0, 0.25), (0.6, 0, 0.45), 30),
        "studio": ((5.0, 4.6, 1.6), (0.0, 0, 0.4), 50),
        "ref": ((5.2, 4.1, 0.95), (0.05, -0.1, 0.45), 42),
        "side_r": ((0.0, -8.5, 0.62), (0.0, 0, 0.5), 50),
        "r34_r": ((-5.4, -4.3, 1.45), (-0.1, 0, 0.45), 50),
        "f34_r": ((5.4, -4.3, 1.25), (0.1, 0, 0.42), 50),
        "fender": ((2.6, 2.2, 1.5), (0.9, 0.6, 0.85), 40),
        "swoosh": ((-0.5, 3.6, 0.9), (-0.7, 0.8, 0.75), 35),
        "swoosh_r": ((-0.5, -3.6, 0.9), (-0.7, -0.8, 0.75), 35),
        "driver": ((0.1, -2.6, 1.25), (0.05, -0.35, 0.95), 40),
        "quarter": ((-1.4, 2.6, 1.1), (-1.6, 0.8, 0.85), 40),
        "helmet": ((0.55, -1.25, 1.25), (-0.06, -0.37, 1.13), 50),
        "helmet_f": ((1.6, -0.75, 1.20), (-0.06, -0.37, 1.12), 45),
        "under": ((2.8, 3.4, 0.12), (0.0, 0.0, 0.25), 28),
        "driver_f": ((3.2, -1.2, 1.35), (0.2, -0.35, 1.0), 38),
        "rwheel_r": ((-2.2, -2.3, 0.45), (-1.23, -0.74, 0.22), 50),
        "chase": ((-6.2, 0.0, 2.1), (0.5, 0, 0.55), 35),
        "rarch": ((-2.2, 2.4, 0.55), (-1.25, 0.8, 0.3), 45),
        "farch": ((2.3, 2.4, 0.5), (1.3, 0.8, 0.3), 45),
        "cpillar": ((-2.6, 2.6, 1.9), (-1.1, 0.6, 1.1), 40),
        "apillar": ((1.5, 1.6, 1.6), (0.6, 0.65, 1.05), 40),
    }
    OUTD.mkdir(parents=True, exist_ok=True)
    for name, (loc, tgt, lens) in shots.items():
        if WANT and name not in WANT:
            continue
        look(cam, loc, tgt, lens)
        sc.render.filepath = str(OUTD / (f"clay_{name}.png" if clay else f"{name}.png"))
        bpy.ops.render.render(write_still=True)


main()
