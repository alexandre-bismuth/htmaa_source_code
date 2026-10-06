"""Validation renders for build_trees.py (EEVEE): per-variant street-level + ~40 m views, contact sheets.

Scene: sun + flat sky-blue world, grey ground, a 1.8 m red box (human) next to each tree for scale.
"""
import math

import bpy
from mathutils import Vector


def setup_scene():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 48
    try:
        sc.eevee.use_raytracing = True
        sc.eevee.use_shadows = True
    except AttributeError:
        pass
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds.new("sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.42, 0.58, 0.85, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    sc.world = world
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 4.0
    sun.angle = math.radians(1.5)
    so = bpy.data.objects.new("sun", sun)
    so.rotation_euler = (math.radians(40), 0, math.radians(35))
    sc.collection.objects.link(so)
    # ground
    bpy.ops.mesh.primitive_plane_add(size=2000, location=(0, 0, 0))
    g = bpy.context.active_object
    g.name = "ground"
    gm = bpy.data.materials.new("ground")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.18, 0.18, 1)
    gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    g.data.materials.append(gm)
    cam = bpy.data.cameras.new("cam")
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    return co


_box_mat = None


def human_box(x, y):
    global _box_mat
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.9))
    b = bpy.context.active_object
    b.scale = (0.45, 0.3, 1.8)
    b.name = "human"
    if _box_mat is None:
        _box_mat = bpy.data.materials.new("human")
        _box_mat.use_nodes = True
        _box_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.6, 0.05, 0.03, 1)
    b.data.materials.append(_box_mat)
    return b


def label(text, x, y, size=1.2):
    cu = bpy.data.curves.new("lbl", "FONT")
    cu.body = text
    cu.size = size
    cu.align_x = "CENTER"
    o = bpy.data.objects.new("lbl", cu)
    o.location = (x, y, 0.02)
    bpy.context.scene.collection.objects.link(o)
    if "lblmat" not in bpy.data.materials:
        m = bpy.data.materials.new("lblmat")
        m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 1, 1, 1)
    o.data.materials.append(bpy.data.materials["lblmat"])
    return o


def look_at(cam, eye, target):
    cam.location = eye
    d = Vector(target) - Vector(eye)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def render(path, w, h):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_all(built, variants, outdir, sheet_only=False):
    cam = setup_scene()
    sc = bpy.context.scene
    obs = {n: ob for n, (ob, st) in built.items()}
    if not sheet_only:
        box = human_box(2.2, -1.5)
        for name, (ob, st) in built.items():
            for o in obs.values():
                o.hide_render = o is not ob
            H, R = st["height_m"], st["crown_radius_m"]
            # street level: eye 1.7 m, standing across a sidewalk + lane from the tree
            cam.data.type = "PERSP"
            cam.data.lens = 18
            dist = max(9.0, 0.75 * H + R * 0.5)
            look_at(cam, (dist * 0.35, -dist, 1.7), (0, 0, H * 0.42))
            render(outdir / f"{name}_street.png", 1280, 960)
            # ~40 m away, elevated (aerial / drone)
            cam.data.lens = 50
            look_at(cam, (25.0, -30.0, 14.0 + H * 0.3), (0, 0, H * 0.5))
            render(outdir / f"{name}_far.png", 1280, 960)
            # under the crown, looking up at the branch structure
            cam.data.lens = 16
            look_at(cam, (R * 0.35, -R * 0.45, 1.6), (0, 0.4, H * 0.75))
            render(outdir / f"{name}_under.png", 960, 960)
        bpy.data.objects.remove(box, do_unlink=True)
    # ---- contact sheets: rows of up to 6 variants (eye-level ortho + elevated 3/4), stacked into one image
    for o in obs.values():
        o.hide_render = True
    names = [n for n in variants if n in built]
    rows = [names[i:i + 6] for i in range(0, len(names), 6)]
    row_w = [sum(2 * (max(built[n][1]["crown_radius_m"], 3.5) + 1.0) for n in row) for row in rows]
    side, aerial = [], []
    W = 2400
    for ri, row in enumerate(rows):
        extra = []
        x = 0.0
        for n in row:
            R = max(built[n][1]["crown_radius_m"], 3.5)
            x += R + 1.0
            built[n][0].location = (x, 0, 0)
            built[n][0].hide_render = False
            extra.append(human_box(x + 1.4, -1.6))
            lb = label(n, x, -R - 1.5, 1.3)
            lb.rotation_euler = (math.radians(90), 0, 0)
            lb.location = (x, -R - 1.5, 0.25)
            extra.append(lb)
            x += R + 1.0
        width = max(row_w)
        hmax = 22.0
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = width
        hpx = int(W * (hmax + 1.0) / width)
        look_at(cam, (width / 2, -400, hmax / 2 - 0.5), (width / 2, 0, hmax / 2 - 0.5))
        p = outdir / f"_sheet_row{ri}.png"
        render(p, W, hpx)
        side.append(p)
        cam.data.type = "PERSP"
        cam.data.lens = 30
        look_at(cam, (width / 2, -width * 0.95, width * 0.42), (width / 2, 0, 4.0))
        p = outdir / f"_sheet_aerial_row{ri}.png"
        render(p, W, int(W * 0.38))
        aerial.append(p)
        for n in row:
            built[n][0].location = (0, 0, 0)
            built[n][0].hide_render = True
        for e in extra:
            bpy.data.objects.remove(e, do_unlink=True)
    stack(side, outdir / "contact_sheet.png")
    stack(aerial, outdir / "contact_sheet_aerial.png")
    for o in obs.values():
        o.hide_render = False


def stack(paths, out):
    import numpy as np
    imgs = []
    for p in paths:
        im = bpy.data.images.load(str(p))
        w, h = im.size
        a = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(a)
        imgs.append(a.reshape(h, w, 4))
        bpy.data.images.remove(im)
        p.unlink()
    w = max(i.shape[1] for i in imgs)
    full = np.concatenate([i for i in reversed(imgs)], 0)   # Blender rows are bottom-up
    h = full.shape[0]
    img = bpy.data.images.new(out.stem, w, h, alpha=False)
    img.pixels.foreach_set(full.ravel())
    img.filepath_raw = str(out)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
