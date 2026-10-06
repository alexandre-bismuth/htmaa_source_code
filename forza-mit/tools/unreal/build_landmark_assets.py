"""Landmark sign material (headless). Usage: tools/unreal/build_landmark_assets.sh

/Game/Cambridge/Landmarks/M_LandmarkSign   unlit translucent, two-sided: Emissive = Tex.rgb * Tint * Brightness,
                                           Opacity = Tex.a * Opacity * visibility. Drawn without depth test like a
                                           game POI marker: behind far geometry (buildings) it shows "x-ray" at
                                           Ghost opacity; behind anything closer than ~25-50 m (the car, a tree next
                                           to the camera) it is hidden. ALandmarkActor gives each quad (panel, arrow,
                                           light pillar) a dynamic instance with its runtime texture
                                           (UI/Generated/landmark_*.png, tools/ui/make_landmark_signs.py).
Kept out of build_game_assets.py so rebuilding it never touches the gate / racing-line materials.
"""
import unreal

DEST = "/Game/Cambridge/Landmarks"
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()


def set_if(m, names, value):
    """Set the first editor property that exists (names differ between engine versions); log what happened."""
    for n in names:
        try:
            m.set_editor_property(n, value)
            unreal.log_warning(f"M_LandmarkSign: {n} = {value}")
            return True
        except Exception:
            pass
    unreal.log_warning(f"M_LandmarkSign: none of {names} exists")
    return False


def sign_material():
    name = "M_LandmarkSign"
    path = f"{DEST}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset(name, DEST, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    # a sign in the sky: no fog tint (it must read at 400 m), crisp under TSR
    set_if(m, ["apply_fogging"], False)
    set_if(m, ["use_translucency_vertex_fog"], False)
    set_if(m, ["disable_depth_test"], True)
    set_if(m, ["enable_responsive_aa", "responsive_aa"], True)

    tex = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSampleParameter2D, -900, 0)
    tex.set_editor_property("parameter_name", "Tex")
    default = unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
    if default:
        tex.set_editor_property("texture", default)
    tex.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)

    tint = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -900, 300)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    bright = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -900, 450)
    bright.set_editor_property("parameter_name", "Brightness")
    bright.set_editor_property("default_value", 1.0)
    opacity = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -900, 550)
    opacity.set_editor_property("parameter_name", "Opacity")
    opacity.set_editor_property("default_value", 1.0)

    rgb_tint = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -600, 100)
    MEL.connect_material_expressions(tex, "RGB", rgb_tint, "A")
    MEL.connect_material_expressions(tint, "", rgb_tint, "B")
    emis = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, 100)
    MEL.connect_material_expressions(rgb_tint, "", emis, "A")
    MEL.connect_material_expressions(bright, "", emis, "B")
    ghost = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -900, 650)
    ghost.set_editor_property("parameter_name", "Ghost")
    ghost.set_editor_property("default_value", 0.45)
    sd = MEL.create_material_expression(m, unreal.MaterialExpressionSceneDepth, -900, 750)
    pd = MEL.create_material_expression(m, unreal.MaterialExpressionPixelDepth, -900, 850)
    vis = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, -600, 700)
    vis.set_editor_property("code",
        "float occluded = step(SD + 100.0, PD);\n"
        "float nearHide = saturate((SD - 2500.0) / 2500.0);\n"
        "return lerp(1.0, Ghost * nearHide, occluded) * A * Op;")
    vis.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    pins = []
    for nm in ["SD", "PD", "Ghost", "A", "Op"]:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", nm)
        pins.append(ci)
    vis.set_editor_property("inputs", pins)
    MEL.connect_material_expressions(sd, "", vis, "SD")
    MEL.connect_material_expressions(pd, "", vis, "PD")
    MEL.connect_material_expressions(ghost, "", vis, "Ghost")
    MEL.connect_material_expressions(tex, "A", vis, "A")
    MEL.connect_material_expressions(opacity, "", vis, "Op")
    op = vis
    MEL.connect_material_property(emis, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    unreal.log_warning(f"saved {path}")


sign_material()
