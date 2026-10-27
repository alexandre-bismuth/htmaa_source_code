"""Validation renders of the parked-car glbs (tools/blender/parked_cars.py), imported exactly as the game gets them.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/parked_render.py -- \
        [--types=sedan,suv] [--out=<dir>] [--views=f34,r34,side,close,lineup] [--cycles]
Materials mirror the Unreal ones (tools/unreal/import_props.py setup_parked): paint colour per car (a palette pick),
glass dark and glossy, detail = COLOR_0 albedo with the class in alpha. Back faces are culled (an inverted or open
shell shows up as a hole). Writes <out>/parked_<view>[_<type>].png.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
PROPS = ROOT / "data/processed/common/props"
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OPT = {a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in ARGS}
OUTD = Path(OPT.get("--out", str(ROOT / "data/processed/common/props/parked_renders")))
META = json.loads((PROPS / "parked_cars.json").read_text())
TYPES = [t for t in META["types"] if not OPT.get("--types") or t in OPT["--types"].split(",")]
VIEWS = OPT.get("--views", "f34,r34,side,close,lineup").split(",")
COL = "Col"
PAINTS = [(0.80, 0.80, 0.78), (0.012, 0.012, 0.013), (0.30, 0.31, 0.32), (0.55, 0.56, 0.57), (0.03, 0.08, 0.25),
          (0.40, 0.02, 0.02), (0.08, 0.09, 0.10), (0.85, 0.85, 0.83)]


def mat_paint(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = COL
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    mul.inputs[6].default_value = (*rgb, 1)      # RGBA A / B are inputs 6 / 7 (A / B names are shared)
    nt.links.new(vc.outputs["Color"], mul.inputs[7])
    nt.links.new(mul.outputs[2], p.inputs["Base Color"])
    p.inputs["Metallic"].default_value = 0.3
    p.inputs["Roughness"].default_value = 0.35
    p.inputs["Coat Weight"].default_value = 1.0
    p.inputs["Coat Roughness"].default_value = 0.04
    m.use_backface_culling = True
    return m


def mat_glass():
    m = bpy.data.materials.new("glass")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.012, 0.014, 0.016, 1)
    p.inputs["Roughness"].default_value = 0.04
    p.inputs["Specular IOR Level"].default_value = 0.6
    m.use_backface_culling = True
    return m


def mat_detail():
    m = bpy.data.materials.new("detail")
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = COL
    nt.links.new(vc.outputs["Color"], p.inputs["Base Color"])
    # class k = round(a * 5) -> roughness / metallic (a map range curve is enough for a look-dev render)
    rr = nt.nodes.new("ShaderNodeFloatCurve")
    c = rr.mapping.curves[0]
    pts = [(0.0, 0.85), (0.2, 0.5), (0.4, 0.6), (0.6, 0.22), (0.8, 0.06), (1.0, 0.4)]
    for i, (x, y) in enumerate(pts):
        if i < len(c.points):
            c.points[i].location = (x, y)
        else:
            c.points.new(x, y)
    for pt in c.points:
        pt.handle_type = "VECTOR"
    nt.links.new(vc.outputs["Alpha"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Value"], p.inputs["Roughness"])
    mt = nt.nodes.new("ShaderNodeFloatCurve")
    c = mt.mapping.curves[0]
    pts = [(0.0, 0.0), (0.3, 0.0), (0.4, 0.3), (0.5, 0.0), (0.55, 1.0), (0.7, 1.0), (0.75, 0.0), (1.0, 0.0)]
    for i, (x, y) in enumerate(pts):
        if i < len(c.points):
            c.points[i].location = (x, y)
        else:
            c.points.new(x, y)
    for pt in c.points:
        pt.handle_type = "VECTOR"
    nt.links.new(vc.outputs["Alpha"], mt.inputs["Value"])
    nt.links.new(mt.outputs["Value"], p.inputs["Metallic"])
    m.use_backface_culling = True
    return m


def load(t, k):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(PROPS / f"parked_{t}.glb"))
    obs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    ob = obs[0]
    global COL
    COL = ob.data.color_attributes[0].name if ob.data.color_attributes else "Col"
    paint, glass, det = mat_paint(f"paint_{t}", PAINTS[k % len(PAINTS)]), mat_glass(), mat_detail()
    for i, slot in enumerate(ob.material_slots):
        n = slot.material.name if slot.material else ""
        slot.material = paint if "paint" in n else glass if "glass" in n else det
    return ob


def scene():
    sc = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc.render.engine = "CYCLES" if OPT.get("--cycles") else "BLENDER_EEVEE"
    if OPT.get("--cycles"):
        sc.cycles.samples = 64
    sc.render.resolution_x, sc.render.resolution_y = 1600, 900
    sc.view_settings.view_transform = "AgX"
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    sky = w.node_tree.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "MULTIPLE_SCATTERING"
    except Exception:
        pass
    w.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.35
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(55), 0, math.radians(-40))
    sc.collection.objects.link(sun)
    gm = bpy.data.meshes.new("ground")
    gm.from_pydata([(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)], [], [(0, 1, 2, 3)])
    g = bpy.data.objects.new("ground", gm)
    gmat = bpy.data.materials.new("asphalt")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.06, 0.06, 0.065, 1)
    gmat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.85
    gm.materials.append(gmat)
    sc.collection.objects.link(g)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam


def look(cam, eye, target, lens=50):
    cam.location = Vector(eye)
    d = Vector(target) - Vector(eye)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens


def shot(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    OUTD.mkdir(parents=True, exist_ok=True)
    cam = scene()
    if "lineup" in VIEWS:
        x = 0.0
        obs = []
        for k, t in enumerate(TYPES):
            ob = load(t, k)
            L = META["types"][t]["length_m"]
            ob.location = (0, x, 0)
            ob.rotation_euler = (0, 0, 0)
            obs.append(ob)
            x -= 2.4
        mid = x / 2 + 1.2
        look(cam, (9.5, mid + 6.5, 3.2), (0, mid + 0.6, 0.7), 32)
        shot(OUTD / "parked_lineup.png")
        look(cam, (-9.5, mid - 6.5, 3.0), (0, mid - 0.6, 0.7), 32)
        shot(OUTD / "parked_lineup_rear.png")
        for o in obs:
            bpy.data.objects.remove(o)
    for k, t in enumerate(TYPES):
        ob = load(t, k)
        L = META["types"][t]["length_m"]
        H = META["types"][t]["height_m"]
        for v in VIEWS:
            if v == "f34":
                look(cam, (L * 0.9 + 2.2, 3.6, 1.35), (0.3, 0, H * 0.45), 40)
            elif v == "r34":
                look(cam, (-L * 0.9 - 2.2, -3.6, 1.5), (-0.3, 0, H * 0.45), 40)
            elif v == "side":
                look(cam, (0, 7.5, 1.0), (0, 0, H * 0.45), 40)
            elif v == "close":   # chase-camera distance, low
                look(cam, (L * 0.5 + 1.6, 2.2, 1.15), (L * 0.2, 0.3, 0.75), 28)
            else:
                continue
            shot(OUTD / f"parked_{v}_{t}.png")
        bpy.data.objects.remove(ob)


main()
