"""Sky dome assets: the HDRI texture, MPC_Sky (brightness, tunable at runtime: cr.Graphics.SkyIntensity) and the
unlit "Is Sky" material M_SkyDome. tools/unreal/build_level.py places the dome and aims the sun.

Run via tools/unreal/build_sky.sh (two editor runs):
  phase "import": data/processed/common/sky/sky.exr (tools/blender/make_sky.py) -> /Game/Cambridge/Sky/T_Sky
  phase "build":  texture settings, MPC_Sky, M_SkyDome (shaders/sky.hlsl)
"""
import json
import math
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE = sys.argv[-1]
SKY = json.loads((ROOT / "data/processed/common/sky/sky.json").read_text())
DIR = "/Game/Cambridge/Sky"
SKY_LEVEL = 0.63         # median sky brightness of the dome (as bright as the old atmosphere sky, tuned 2026-10-26)
INTENSITY = SKY_LEVEL / SKY["median_sky"]   # dome brightness (x the photo's linear values); the sky light captures it

MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def sun_offset():
    """u offset so the photo's sun (sun_u) sits at the azimuth the sun light comes from: the direction to the sun is
    the light's yaw + 180 deg, and shaders/sky.hlsl maps azimuth atan2(y, x) to u."""
    az = math.atan2(math.sin(math.radians(SKY["sun_yaw_deg"] + 180.0)), math.cos(math.radians(SKY["sun_yaw_deg"] + 180.0)))
    return SKY["sun_u"] - az / (2.0 * math.pi)


def import_sky():
    t = unreal.AssetImportTask()
    t.filename = str(ROOT / "data/processed/common/sky/sky.exr")
    t.destination_path = DIR
    t.destination_name = "T_Sky"
    t.automated = True
    t.replace_existing = True
    t.save = True
    ASSETS.import_asset_tasks([t])


def build():
    tex = unreal.load_asset(f"{DIR}/T_Sky")
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_HDR_COMPRESSED)
    tex.set_editor_property("srgb", False)
    tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_SKYBOX)
    tex.set_editor_property("address_x", unreal.TextureAddress.TA_WRAP)
    tex.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
    EAL.save_loaded_asset(tex, only_if_is_dirty=False)

    mpc_path = f"{DIR}/MPC_Sky"
    mpc = unreal.load_asset(mpc_path) if EAL.does_asset_exist(mpc_path) else \
        ASSETS.create_asset("MPC_Sky", DIR, unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())
    p = unreal.CollectionScalarParameter()
    p.set_editor_property("parameter_name", "Intensity")
    p.set_editor_property("default_value", INTENSITY)
    mpc.set_editor_property("scalar_parameters", [p])
    EAL.save_loaded_asset(mpc, only_if_is_dirty=False)

    path = f"{DIR}/M_SkyDome"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset("M_SkyDome", DIR, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("is_sky", True)
    m.set_editor_property("two_sided", True)
    t = MEL.create_material_expression(m, unreal.MaterialExpressionTextureObject, -900, 0)
    t.set_editor_property("texture", tex)
    cv = MEL.create_material_expression(m, unreal.MaterialExpressionCameraVectorWS, -900, 200)
    off = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -900, 300)
    off.set_editor_property("r", sun_offset())
    inten = MEL.create_material_expression(m, unreal.MaterialExpressionCollectionParameter, -900, 400)
    inten.set_editor_property("collection", mpc)
    inten.set_editor_property("parameter_name", "Intensity")
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, -400, 0)
    pins = []
    for n in ("Tex", "CV", "Off", "Int"):
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        pins.append(ci)
    c.set_editor_property("inputs", pins)
    c.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    c.set_editor_property("description", "sky.hlsl")
    c.set_editor_property("code", (Path(__file__).parent / "shaders/sky.hlsl").read_text())
    for n, e in (("Tex", t), ("CV", cv), ("Off", off), ("Int", inten)):
        assert MEL.connect_material_expressions(e, "", c, n), n
    assert MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)


{"import": import_sky, "build": build}[PHASE]()
