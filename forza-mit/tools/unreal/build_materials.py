"""Textures + master materials + instances for a region, assigned to its mesh tiles.

Run via tools/unreal/build_materials.sh <region> (two editor runs):
  phase "import": import CC0 PBR sets, the region's orthophoto + markings mask, water normal
  phase "build":  texture settings, master materials (HLSL Custom nodes from tools/unreal/shaders),
                  instances from tools/unreal/materials.json, assignment to every mesh tile by class
"""
import json
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE, REGION = sys.argv[-2], sys.argv[-1]
SHADERS = Path(__file__).parent / "shaders"
CFG = json.loads((Path(__file__).parent / "materials.json").read_text())
TEXSETS = json.loads((ROOT / "data/raw/textures/polyhaven/textures.json").read_text())
ORTHO = json.loads((ROOT / f"data/processed/{REGION}/ortho/ortho.json").read_text())
_ctx = ROOT / f"data/processed/{REGION}/ortho/ortho_ctx.json"
ORTHO_CTX = json.loads(_ctx.read_text()) if _ctx.exists() else None

TEX = "/Game/Cambridge/Textures"
RTEX = f"/Game/Cambridge/{REGION}/Textures"
MAT = "/Game/Cambridge/Materials"
MESHES = f"/Game/Cambridge/{REGION}/Meshes"

MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


# ------------------------------------------------------------------ textures
def texture_sources():
    """(destination folder, asset name, source file, kind) for every texture we use."""
    out = []
    for surface, t in TEXSETS.items():
        d = ROOT / t["dir"]
        out += [(TEX, f"T_{surface}_D", d / "diff.jpg", "color"),
                (TEX, f"T_{surface}_N", d / "nor.jpg", "normal"),
                (TEX, f"T_{surface}_ARM", d / "arm.jpg", "mask")]
    rd = ROOT / f"data/processed/{REGION}/ortho"
    if ORTHO_CTX:
        out.append((RTEX, "T_OrthoCtx", rd / "ortho_ctx.jpg", "ortho"))
    out += [(RTEX, "T_Ortho", rd / "ortho.jpg", "ortho"),
            (RTEX, "T_Markings", rd / "markings.png", "rg"),
            (RTEX, "T_GroundMask", rd / "ground_mask.png", "linear"),
            (TEX, "T_WaterN", ROOT / "data/processed/common/water_normal.png", "normal")]
    return out


def import_textures():
    tasks = []
    for folder, name, src, _ in texture_sources():
        t = unreal.AssetImportTask()
        t.filename = str(src)
        t.destination_path = folder
        t.destination_name = name
        t.automated = True
        t.replace_existing = True
        t.save = True
        tasks.append(t)
    ASSETS.import_asset_tasks(tasks)


def find_texture(folder, name):
    for p in EAL.list_assets(folder, recursive=True):
        a = unreal.load_asset(p)
        if isinstance(a, unreal.Texture2D) and a.get_name() == name:
            return a
    raise RuntimeError(f"texture {folder}/{name} not found")


def configure_textures():
    tex = {}
    for folder, name, _, kind in texture_sources():
        t = find_texture(folder, name)
        if kind == "normal":
            t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            t.set_editor_property("srgb", False)
        elif kind == "mask":
            t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
            t.set_editor_property("srgb", False)
        elif kind == "linear":
            # three-channel distance-field mask: BC7, linear (same 1 B/px as BC5)
            t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
            t.set_editor_property("srgb", False)
        elif kind == "rg":
            # two-channel paint mask: BC5 keeps R and G at full quality (it is not a normal map;
            # we only read .rg in the shader)
            t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            t.set_editor_property("srgb", False)
        else:
            t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
            t.set_editor_property("srgb", True)
        t.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
        EAL.save_loaded_asset(t, only_if_is_dirty=False)
        tex[name] = t
    return tex


# ------------------------------------------------------------------ master materials
def new_material(name, two_sided=False):
    path = f"{MAT}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset(name, MAT, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("two_sided", two_sided)
    # usage flags baked into the asset: without them a cooked game falls back to the default
    # material on Nanite meshes (the editor only patches them in memory, every launch)
    for flag in ("used_with_nanite", "used_with_instanced_static_meshes"):
        m.set_editor_property(flag, True)
    return m


def custom_node(m, code_file, inputs, outputs, ret=unreal.CustomMaterialOutputType.CMOT_FLOAT3, x=-300):
    """inputs: [(pin name, expression, expression output pin)]; outputs: [(name, CMOT type)]."""
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, x, 0)
    pins = []
    for n, _, _ in inputs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        pins.append(ci)
    c.set_editor_property("inputs", pins)
    outs = []
    for n, t in outputs:
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    c.set_editor_property("additional_outputs", outs)
    c.set_editor_property("output_type", ret)
    c.set_editor_property("description", code_file)
    c.set_editor_property("code", (SHADERS / code_file).read_text())
    for n, expr, pin in inputs:
        assert MEL.connect_material_expressions(expr, pin, c, n), f"connect {n}"
    return c


def tex_param(m, name, default, y):
    e = MEL.create_material_expression(m, unreal.MaterialExpressionTextureObjectParameter, -900, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("texture", default)
    return (name, e, "")


def vec_param(m, name, value, y, pin="RGBA"):
    e = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -900, y)
    e.set_editor_property("parameter_name", name)
    v = list(value) + [0.0] * (4 - len(value))
    e.set_editor_property("default_value", unreal.LinearColor(*v))
    return (name, e, pin)


def world_pos(m, y):
    return ("WP", MEL.create_material_expression(m, unreal.MaterialExpressionWorldPosition, -900, y), "XYZ")


F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
MP = unreal.MaterialProperty


def wire(m, c, mapping):
    for pin, prop in mapping:
        assert MEL.connect_material_property(c, pin, prop), f"property {pin}"
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)


def ortho_xform(meta=None):
    meta = meta or ORTHO
    return [meta["ue_x0_cm"], meta["ue_y0_cm"], meta["ue_side_cm"], 0.0]


def build_masters(tex):
    d = tex["T_road_D"]; n = tex["T_road_N"]; a = tex["T_road_ARM"]
    masters = {}

    m = new_material("M_Ground")
    vn = MEL.create_material_expression(m, unreal.MaterialExpressionVertexNormalWS, -900, 100)
    ins = [world_pos(m, 0), ("VN", vn, ""), tex_param(m, "D", d, 200), tex_param(m, "N", n, 400), tex_param(m, "ARM", a, 600),
           tex_param(m, "Ortho", tex["T_Ortho"], 800), tex_param(m, "Marks", tex["T_Markings"], 1000),
           vec_param(m, "P1", [3, 0.3, 0, 0], 1200), vec_param(m, "P2", [1, 1, 0.15, 0], 1400),
           vec_param(m, "OX", ortho_xform(), 1600), vec_param(m, "Tint", [1, 1, 1], 1800, "RGB"),
           vec_param(m, "P3", [0, 0, 0, 0], 2000), tex_param(m, "Mask", tex["T_GroundMask"], 2200),
           tex_param(m, "D2", tex["T_sidewalk_brick_D"], 2400), tex_param(m, "N2", tex["T_sidewalk_brick_N"], 2500),
           tex_param(m, "ARM2", tex["T_sidewalk_brick_ARM"], 2600), vec_param(m, "P4", [2, 0, 60, 0], 2700)]
    c = custom_node(m, "ground.hlsl", ins, [("Nrm", F3), ("Rough", F1), ("AO", F1)])
    wire(m, c, [("return", MP.MP_BASE_COLOR), ("Nrm", MP.MP_NORMAL), ("Rough", MP.MP_ROUGHNESS), ("AO", MP.MP_AMBIENT_OCCLUSION)])
    masters["ground"] = m

    m = new_material("M_Paint")
    ins = [world_pos(m, 0), vec_param(m, "Col", [0.85, 0.85, 0.82], 200, "RGB"), vec_param(m, "P", [0.5, 0.55, 0, 0], 400)]
    c = custom_node(m, "paint.hlsl", ins, [("Rough", F1)])
    wire(m, c, [("return", MP.MP_BASE_COLOR), ("Rough", MP.MP_ROUGHNESS)])
    masters["paint"] = m

    m = new_material("M_Facade", two_sided=True)
    uv0 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 0)
    uv1 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 100)
    uv1.set_editor_property("coordinate_index", 1)
    uv2 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 150)
    uv2.set_editor_property("coordinate_index", 2)
    ins = [("UV", uv0, ""), ("UV1", uv1, ""), ("UV2", uv2, ""), tex_param(m, "D", d, 200), tex_param(m, "N", n, 400), tex_param(m, "ARM", a, 600),
           world_pos(m, 700),
           ("CV", MEL.create_material_expression(m, unreal.MaterialExpressionCameraVectorWS, -900, 720), ""),
           ("VN", MEL.create_material_expression(m, unreal.MaterialExpressionVertexNormalWS, -900, 740), ""),
           vec_param(m, "P4", [0.0, 3.5, 0.0, 0.0], 760),
           vec_param(m, "P1", [1.4, 3.4, 2.6, 4.0], 800), vec_param(m, "P2", [0.55, 0.55, 0.28, 0], 1000),
           vec_param(m, "P3", [0.1, 0.06, 0.06, 0.4], 1200), vec_param(m, "WallTint", [1, 1, 1], 1400, "RGB"),
           vec_param(m, "GlassColor", [0.05, 0.06, 0.08], 1600, "RGB"), vec_param(m, "FrameColor", [0.8, 0.8, 0.8], 1800, "RGB")]
    c = custom_node(m, "facade.hlsl", ins, [("Nrm", F3), ("Rough", F1), ("Metal", F1), ("AO", F1), ("Emit", F3)])
    wire(m, c, [("return", MP.MP_BASE_COLOR), ("Nrm", MP.MP_NORMAL), ("Rough", MP.MP_ROUGHNESS),
                ("Metal", MP.MP_METALLIC), ("AO", MP.MP_AMBIENT_OCCLUSION), ("Emit", MP.MP_EMISSIVE_COLOR)])
    masters["facade"] = m

    m = new_material("M_Roof", two_sided=True)
    ruv1 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 50)
    ruv1.set_editor_property("coordinate_index", 1)
    ins = [world_pos(m, 0), ("VN", MEL.create_material_expression(m, unreal.MaterialExpressionVertexNormalWS, -900, 30), ""),
           ("UV1", ruv1, ""), tex_param(m, "Ortho", tex["T_Ortho"], 200),
           tex_param(m, "D", tex["T_parking_D"], 250), tex_param(m, "N", tex["T_parking_N"], 300), tex_param(m, "ARM", tex["T_parking_ARM"], 350),
           vec_param(m, "OX", ortho_xform(), 400), vec_param(m, "P1", [1, 0.8, 3.0, 0.6], 600)]
    c = custom_node(m, "roof.hlsl", ins, [("Nrm", F3), ("Rough", F1)])
    wire(m, c, [("return", MP.MP_BASE_COLOR), ("Nrm", MP.MP_NORMAL), ("Rough", MP.MP_ROUGHNESS)])
    masters["roof"] = m

    m = new_material("M_Water")
    t = MEL.create_material_expression(m, unreal.MaterialExpressionTime, -900, 100)
    ins = [world_pos(m, 0), ("T", t, ""), tex_param(m, "WN", tex["T_WaterN"], 200), vec_param(m, "Col", [0.02, 0.045, 0.05], 400, "RGB")]
    c = custom_node(m, "water.hlsl", ins, [("Nrm", F3), ("Rough", F1)])
    wire(m, c, [("return", MP.MP_BASE_COLOR), ("Nrm", MP.MP_NORMAL), ("Rough", MP.MP_ROUGHNESS)])
    masters["water"] = m
    return masters


# ------------------------------------------------------------------ instances + assignment
def make_instance(name, parent, params, tex, context=False):
    path = f"{MAT}/Instances/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    mi = ASSETS.create_asset(name, f"{MAT}/Instances", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    surface = params.get("tex")
    if surface:
        for suffix in ("D", "N", "ARM"):
            MEL.set_material_instance_texture_parameter_value(mi, suffix, tex[f"T_{surface}_{suffix}"])
    params = dict(params)
    if context:
        # backdrop ring: the wide (0.42 m) orthophoto, no road-marking mask
        MEL.set_material_instance_texture_parameter_value(mi, "Ortho", tex["T_OrthoCtx"])
        params["OX"] = ortho_xform(ORTHO_CTX)
        if "P1" in params and len(params["P1"]) == 4 and "tex" in params and "Tint" in params:   # ground only
            params["P1"] = params["P1"][:3] + [0.0]
        if "P3" in params and "Tint" in params:
            params["P3"] = params["P3"][:3] + [0.0]     # the edge mask only covers the playable ortho
    for k, v in params.items():
        if k == "tex" or not isinstance(v, list):
            continue
        vv = list(v) + [0.0] * (4 - len(v))
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*vv))
    EAL.save_loaded_asset(mi, only_if_is_dirty=False)
    return mi


def main():
    if PHASE == "import":
        import_textures()
        return
    tex = configure_textures()
    masters = build_masters(tex)
    instances = {}
    for group, entries in CFG.items():
        if group.startswith("_"):
            continue
        for cls, params in entries.items():
            instances[cls] = make_instance(f"MI_{cls}", masters[group], params, tex)
            if ORTHO_CTX and cls != "curbs" and group != "paint":
                instances[f"ctx_{cls}"] = make_instance(f"MI_ctx_{cls}", masters[group], params, tex, context=True)
    assigned, missing = 0, set()
    for p in EAL.list_assets(MESHES, recursive=True):
        mesh = unreal.load_asset(p)
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        cls = mesh.get_name().split("__")[0]
        mi = instances.get(cls)
        if mi is None:
            missing.add(cls)
            continue
        for i in range(len(mesh.get_editor_property("static_materials"))):
            mesh.set_material(i, mi)
        EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
        assigned += 1
    report = {"assigned_meshes": assigned, "classes_without_material": sorted(missing), "instances": sorted(instances)}
    (ROOT / f"data/processed/{REGION}/meshes/ue_materials_report.json").write_text(json.dumps(report, indent=2))


main()
