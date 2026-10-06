"""Build the procedural street trees: one .glb per variant + trees.json + validation renders.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/build_trees.py
    ... -P tools/blender/build_trees.py -- --only oak_a,oak_b    # subset (trees.json is merged, not replaced)
    ... -P tools/blender/build_trees.py -- --no-render           # skip renders
    ... -P tools/blender/build_trees.py -- --sheet-only          # rebuild all, render only contact sheets

Output: data/processed/common/props/trees/tree_<variant>.glb, trees.json, renders/*.png
Frame: metres, Z up (Blender), trunk base at the origin; the glTF exporter converts to +Y up.
Each glb is one mesh with two material slots, "bark" (slot 0) and "leaves" (slot 1). Leaves are opaque
geometry (no alpha). COLOR_0 (RGBA, linear): leaves RGB = albedo incl. a mild baked crown occlusion,
A = that occlusion term alone; bark RGB = multiplier for the bark texture (occlusion x twig tint), A = occlusion. Textures are not embedded:
trees.json points at the bark maps in data/raw/textures (fetched/baked by tree_textures.py).
"""
import json
import math
import sys
import time
import zlib
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tree_gen  # noqa: E402
import tree_species  # noqa: E402
import tree_textures  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "data/processed/common/props/trees"
RENDERS = OUT / "renders"


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"only": None, "render": True, "sheet_only": False}
    i = 0
    while i < len(a):
        if a[i] == "--only":
            opts["only"] = a[i + 1].split(",")
            i += 1
        elif a[i] == "--no-render":
            opts["render"] = False
        elif a[i] == "--sheet-only":
            opts["sheet_only"] = True
        i += 1
    return opts


# ------------------------------------------------------------------------------------ materials
def image(path, colorspace):
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def bark_material(name, tex, tint):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uv = nt.nodes.new("ShaderNodeUVMap")
    diff = nt.nodes.new("ShaderNodeTexImage")
    diff.image = image(tex["diff"], "sRGB")
    nor = nt.nodes.new("ShaderNodeTexImage")
    nor.image = image(tex["nor_gl"], "Non-Color")
    rough = nt.nodes.new("ShaderNodeTexImage")
    rough.image = image(tex["rough"], "Non-Color")
    for n in (diff, nor, rough):
        nt.links.new(uv.outputs["UV"], n.inputs["Vector"])
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(diff.outputs["Color"], mul.inputs["A"])
    nt.links.new(attr.outputs["Color"], mul.inputs["B"])
    tintn = nt.nodes.new("ShaderNodeMix")
    tintn.data_type = "RGBA"
    tintn.blend_type = "MULTIPLY"
    tintn.inputs["Factor"].default_value = 1.0
    tintn.inputs["B"].default_value = (*tint, 1.0)
    nt.links.new(mul.outputs["Result"], tintn.inputs["A"])
    nt.links.new(tintn.outputs["Result"], bsdf.inputs["Base Color"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nor.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(rough.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green" if tex["rough_channel"] == "G" else "Red"], bsdf.inputs["Roughness"])
    m.use_backface_culling = False
    return m


def leaf_material(name, roughness, sss):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    # thin-leaf back-lighting: mix a translucent lobe tinted by the leaf colour
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    gain = nt.nodes.new("ShaderNodeMix")
    gain.data_type = "RGBA"
    gain.blend_type = "MULTIPLY"
    gain.inputs["Factor"].default_value = 1.0
    gain.inputs["B"].default_value = (1.6, 1.9, 0.9, 1.0)
    nt.links.new(attr.outputs["Color"], gain.inputs["A"])
    nt.links.new(gain.outputs["Result"], tr.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = sss
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    m.use_backface_culling = False
    return m


# ------------------------------------------------------------------------------------ mesh
def build_object(name, bark, leaves, mats):
    nb = len(bark["verts"])
    V = np.concatenate([bark["verts"], leaves["verts"]]).astype(np.float32)
    F = np.concatenate([bark["tris"], leaves["tris"] + nb]).astype(np.int32)
    UV = np.concatenate([bark["uv"], leaves["uv"]]).astype(np.float32)
    N = np.concatenate([bark["normals"], leaves["normals"]]).astype(np.float32)
    col = np.ones((len(V), 4), np.float32)
    col[:nb, :3] = bark["tint"]
    col[:nb, 3] = bark["ao"]
    col[nb:, :3] = leaves["color"] * leaves["ao"][:, None] ** 0.6
    col[nb:, 3] = leaves["ao"]
    matidx = np.concatenate([np.zeros(len(bark["tris"]), np.int32), np.ones(len(leaves["tris"]), np.int32)])

    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V))
    me.vertices.foreach_set("co", V.ravel())
    me.loops.add(F.size)
    me.loops.foreach_set("vertex_index", F.ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set("loop_start", np.arange(0, F.size, 3, dtype=np.int32))
    me.polygons.foreach_set("material_index", matidx)
    me.update(calc_edges=True)
    uvl = me.uv_layers.new(name="UVMap")
    uvl.data.foreach_set("uv", UV[F.ravel()].ravel())
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    ca.data.foreach_set("color", col.ravel())
    me.color_attributes.active_color = ca
    me.polygons.foreach_set("use_smooth", np.ones(len(F), bool))
    me.normals_split_custom_set_from_vertices(N)
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def stats(ob, bark, leaves, gen):
    V = np.concatenate([bark["verts"], leaves["verts"]])
    H = float(V[:, 2].max())
    rho = np.hypot(leaves["verts"][:, 0], leaves["verts"][:, 1])
    crown_r = float(np.percentile(rho, 99.5)) if len(rho) else 0.0
    # trunk radius at 1 m: trunk stem vertices between 0.9 and 1.1 m
    tv = bark["verts"]
    band = tv[(tv[:, 2] > 0.9) & (tv[:, 2] < 1.1)]
    stems = [b for b in gen.branches if b.stem]
    rs = []
    for b in stems:
        p, _, _ = b.at(min(1.0, (1.0 + 0.15) / max(b.length, 1e-3)))
        sel = band[np.linalg.norm(band[:, :2] - p[:2], axis=1) < 0.8]
        if len(sel):
            rs.append(float(np.max(np.linalg.norm(sel[:, :2] - p[:2], axis=1))))
    # multi-stem: radius of the circle enclosing all stems at 1 m
    if len(stems) > 1 and len(band):
        c = band[:, :2].mean(0)
        trunk_r = float(np.max(np.linalg.norm(band[:, :2] - c, axis=1)))
    else:
        trunk_r = rs[0] if rs else 0.1
    lz = leaves["verts"][:, 2]
    return {"height_m": round(H, 2), "crown_radius_m": round(crown_r, 2), "trunk_radius_m": round(trunk_r, 3),
            "crown_base_m": round(float(np.percentile(lz, 0.5)), 2),
            "triangles": int(len(bark["tris"]) + len(leaves["tris"])),
            "bark_triangles": int(len(bark["tris"])), "leaf_triangles": int(len(leaves["tris"])),
            "leaves": int(leaves["count"])}


def export(ob, path):
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=False,
                              export_yup=True, export_normals=True, export_texcoords=True,
                              export_tangents=False, export_materials="EXPORT", export_image_format="NONE",
                              export_cameras=False, export_lights=False, export_vertex_color="ACTIVE",
                              export_all_vertex_colors=False, export_attributes=False)


def verify_glb(path):
    """Parse the exported glb's JSON chunk: two materials (bark, leaves), COLOR_0 + NORMAL + TEXCOORD_0 on
    both primitives, +Y up with the trunk base at the origin. Returns a short report string."""
    import struct
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    g = json.loads(data[20:20 + n])
    mats = [m["name"] for m in g["materials"]]
    assert mats == ["bark", "leaves"], mats
    prims = g["meshes"][0]["primitives"]
    assert len(prims) == 2
    for pr in prims:
        for a in ("POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"):
            assert a in pr["attributes"], (path, a)
    assert all(g["materials"][i].get("doubleSided") for i in range(2))
    pos = [g["accessors"][pr["attributes"]["POSITION"]] for pr in prims]
    ymin = min(a["min"][1] for a in pos)
    ymax = max(a["max"][1] for a in pos)
    assert -0.3 < ymin <= 0.0 and ymax > 3.0, (ymin, ymax)
    return f"glb ok: materials {mats}, COLOR_0 on both primitives, y {ymin:.2f}..{ymax:.2f}"


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT))


def material_spec(sp, tex, leaves):
    lin = leaves["color"].mean(0)
    return {
        "bark": {"texture": rel(tex["diff"]), "normal": rel(tex["nor_dx"]), "normal_gl": rel(tex["nor_gl"]),
                 "roughness": rel(tex["rough"]), "roughness_channel": tex["rough_channel"],
                 "texture_size_m": tex["size_m"], "tint": sp.get("bark_tint", [1, 1, 1]),
                 "uv": "UV0: u around (integer repeats per branch), v along the branch, 1 unit = texture_size_m",
                 "vertex_color": "COLOR_0 rgb = multiplier on the bark texture (crown occlusion x darker/browner "
                                 "young twigs); a = occlusion only",
                 "source": f"{sp['bark']} ({tex['source']}, {tex['license']})"},
        "leaves": {"base_color": [round(float(x), 4) for x in lin], "base_color_space": "linear (mean of COLOR_0)",
                   "uses_vertex_color": True,
                   "vertex_color": "COLOR_0 rgb = final albedo incl. baked occlusion (use as BaseColor); a = occlusion only",
                   "two_sided": True, "opacity": "opaque (no mask)",
                   "subsurface": sp.get("leaf_sss", {"color": [0.45, 0.6, 0.12], "strength": 0.5}),
                   "roughness": sp.get("leaf_roughness", 0.55), "specular": 0.35,
                   "texture": None},
    }


def main():
    o = args()
    t_all = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    RENDERS.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    barks = tree_textures.bark_sets()
    variants = tree_species.variants()
    names = [n for n in variants if o["only"] is None or n in o["only"]]
    jpath = OUT / "trees.json"
    meta = json.loads(jpath.read_text()) if jpath.exists() else {}
    meta.setdefault("variants", {})
    built = {}
    for name in names:
        t0 = time.time()
        sp = variants[name]
        tex = barks[sp["bark"]]
        seed = zlib.crc32(name.encode()) + sp.get("seed", 0)
        gen, bark, leaves = tree_gen.generate(sp, seed, tex["size_m"])
        mats = [bark_material("bark", tex, sp.get("bark_tint", (1, 1, 1))),
                leaf_material("leaves", sp.get("leaf_roughness", 0.55), sp.get("leaf_translucency", 0.3))]
        ob = build_object(f"tree_{name}", bark, leaves, mats)
        st = stats(ob, bark, leaves, gen)
        path = OUT / f"tree_{name}.glb"
        export(ob, path)
        print("[tree]   " + verify_glb(path))
        for m in mats:                      # free the names "bark"/"leaves" for the next variant
            m.name = f"{m.name}_{name}"
        st["leaf_unit"] = "leaflet" if sp["leaf"]["shape"] == "pinnate" else "leaf"
        st["leaf_triangles_each"] = int(len(leaves["tris"]) // max(leaves["count"], 1))
        entry = {"file": rel(path), "species": sp["species"], "genera": sp["genera"], **st,
                 "trunk_capsule_height_m": round(min(sp["first_branch"] + 0.5, st["height_m"] * 0.4), 2),
                 "seed": int(seed), "materials": material_spec(sp, tex, leaves),
                 "file_size_mb": round(path.stat().st_size / 1e6, 1)}
        meta["variants"][name] = entry
        built[name] = (ob, st)
        print(f"[tree] {name:16s} H={st['height_m']:5.1f} R={st['crown_radius_m']:4.1f} r1m={st['trunk_radius_m']:.2f} "
              f"tris={st['triangles']:7d} (bark {st['bark_triangles']}, leaves {st['leaves']}) "
              f"{time.time() - t0:.1f}s")
    meta["variants"] = {k: meta["variants"][k] for k in variants if k in meta["variants"]}
    meta["frame"] = ("metres; Blender Z-up, exported glTF +Y-up (default exporter conversion); "
                     "trunk base at the origin (trunk mesh starts 0.15 m below to sink into the curb)")
    meta["genus_map"] = tree_species.GENUS_MAP
    meta["unmapped_genera"] = tree_species.UNMAPPED_GENERA
    meta["notes"] = {
        "leaves": "count of leaf polygons groups: whole leaves, except honeylocust where it counts leaflets "
                  "(10 leaflets per compound leaf); see leaf_unit",
        "trunk_radius_m": "max trunk radius at 1 m above ground (multi-stem: radius of the circle enclosing all "
                          "stems at 1 m), for the collision capsule",
        "trunk_capsule_height_m": "suggested capsule height (clear trunk below the first limbs)",
        "COLOR_0": "exported as normalized uint16 RGBA, linear (glTF convention); whether UE's glTF import "
                   "stores it sRGB- or linear-encoded in its 8-bit FColor is unverified",
    }
    meta["generator"] = "tools/blender/build_trees.py (tree_gen.py, tree_species.py, tree_textures.py)"
    jpath.write_text(json.dumps(meta, indent=2))
    if o["render"]:
        import tree_render
        tree_render.render_all(built, variants, RENDERS, sheet_only=o["sheet_only"])
    print(f"[tree] done in {time.time() - t_all:.0f}s")


main()
