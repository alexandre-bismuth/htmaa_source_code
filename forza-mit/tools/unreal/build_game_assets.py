"""Small gameplay assets (headless): time-trial gate / start-marker materials, the racing line and the
race UI sounds.

    tools/unreal/build_game_assets.sh          (run tools/ui/make_ui_sounds.py first for the sounds)

/Game/Cambridge/Game/M_GateBody     lit opaque gate geometry (ATimeTrialGate's procedural mesh): dark
                                    gunmetal; vertex colour R = emissive accent ("Color", HDR),
                                    G = checkered (UV0 in metres, 0.5 m squares; "CheckerGlow")
/Game/Cambridge/Game/M_GateCurtain  unlit additive light curtain between the posts of the next gate:
                                    vertical fade, rising scan bands, bright base line, fades out
                                    near the camera (keeps overdraw low); "Color", "Intensity",
                                    "Checker" (finish), "Flash" (pass pulse)
/Game/Cambridge/Game/M_StartDecal   unlit translucent start box on the asphalt (outline, corner
                                    brackets, chevrons sweeping forward); UV0 in metres around the box
                                    centre; "Color", "HalfLength", "HalfWidth", "Opacity"
/Game/Cambridge/Game/M_GateGlow     unlit opaque, "Color" (legacy, kept for old content)
/Game/Cambridge/Game/M_GateBeam     unlit additive light beam that fades with height, "Color"
/Game/Cambridge/Game/M_RacingLine   Forza-style chevron racing line (vertex colour)
/Game/Cambridge/Game/Audio/ui_*     race UI sounds from data/processed/common/audio/ui
"""
from pathlib import Path

import unreal

DEST = "/Game/Cambridge/Game"
AUDIO = f"{DEST}/Audio"
ROOT = Path(__file__).resolve().parents[2]
UI_SOUNDS = ROOT / "data/processed/common/audio/ui"     # tools/ui/make_ui_sounds.py
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()


def new_material(name, blend, shading=unreal.MaterialShadingModel.MSM_UNLIT, two_sided=False):
    path = f"{DEST}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset(name, DEST, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("shading_model", shading)
    m.set_editor_property("blend_mode", blend)
    m.set_editor_property("two_sided", two_sided)
    return m


def param(m, name, default, x, y):
    if isinstance(default, unreal.LinearColor):
        e = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, x, y)
    else:
        e = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("default_value", default)
    return e


def custom(m, code, inputs, out_type, x, y):
    """Custom HLSL node; inputs = [(name, expression, output pin name or "")]."""
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, x, y)
    c.set_editor_property("code", code)
    c.set_editor_property("output_type", out_type)
    pins = []
    for nm, _, _ in inputs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", nm)
        pins.append(ci)
    c.set_editor_property("inputs", pins)
    for nm, expr, out in inputs:
        MEL.connect_material_expressions(expr, out, c, nm)
    return c


def finish(m):
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)


F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
CHECKER = "float chk = abs(fmod(floor(UV.x * 2.0) + floor(UV.y * 2.0), 2.0));\n"


def gate_body():
    m = new_material("M_GateBody", unreal.BlendMode.BLEND_OPAQUE, unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -900, 0)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 200)
    colour = param(m, "Color", unreal.LinearColor(6.0, 3.6, 0.15, 1.0), -900, 400)
    glow = param(m, "CheckerGlow", 0.35, -900, 600)
    ins = [("VC", vc, ""), ("UV", uv, "")]
    base = custom(m, CHECKER +
                  "float3 body = float3(0.020, 0.022, 0.026);\n"
                  "float3 flag = lerp(float3(0.015, 0.015, 0.017), float3(0.80, 0.80, 0.78), chk);\n"
                  "return lerp(lerp(body, flag, VC.g), float3(0.04, 0.04, 0.04), VC.r);", ins, F3, -450, 0)
    emis = custom(m, CHECKER + "return Color * VC.r + VC.g * chk * Glow * float3(1, 1, 1);",
                  ins + [("Color", colour, ""), ("Glow", glow, "")], F3, -450, 250)
    metal = custom(m, "return 0.75 * (1 - VC.g) * (1 - VC.r);", [("VC", vc, "")], F1, -450, 450)
    rough = custom(m, "return 0.30 + 0.35 * VC.g;", [("VC", vc, "")], F1, -450, 550)
    MEL.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(emis, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    finish(m)


def gate_curtain():
    m = new_material("M_GateCurtain", unreal.BlendMode.BLEND_ADDITIVE, two_sided=True)
    uv0 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 0)
    uv1 = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 150)
    uv1.set_editor_property("coordinate_index", 1)
    time = MEL.create_material_expression(m, unreal.MaterialExpressionTime, -900, 300)
    depth = MEL.create_material_expression(m, unreal.MaterialExpressionPixelDepth, -900, 400)
    ins = [("UV", uv0, ""), ("M", uv1, ""), ("T", time, ""), ("Depth", depth, ""),
           ("Color", param(m, "Color", unreal.LinearColor(0.8, 0.45, 0.02, 1.0), -900, 500), ""),
           ("Intensity", param(m, "Intensity", 1.0, -900, 700), ""),
           ("Checker", param(m, "Checker", 0.0, -900, 800), ""),
           ("Flash", param(m, "Flash", 0.0, -900, 900), "")]
    code = (
        "float u = UV.x, v = UV.y;\n"
        "float edge = smoothstep(0.0, 0.03, u) * smoothstep(1.0, 0.97, u);\n"
        "float vert = pow(saturate(1.0 - v), 1.8);\n"
        "float base = smoothstep(0.05, 0.0, v);\n"
        "float scan = 0.6 + 0.4 * smoothstep(0.6, 1.0, frac(M.y * 1.4 - T * 0.8));\n"
        "float chk = abs(fmod(floor(M.x * 1.25) + floor(M.y * 1.25), 2.0));\n"
        "float pattern = lerp(1.0, 0.25 + 0.75 * chk, Checker);\n"
        "float nearFade = saturate((Depth - 600.0) / 1400.0);\n"
        "float glow = (vert * 0.5 * scan * pattern + base * 1.4) * edge * nearFade;\n"
        "return Color * glow * Intensity + Flash * vert * edge * nearFade * float3(1.0, 1.0, 1.0);")
    out = custom(m, code, ins, F3, -450, 300)
    MEL.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(m)


def start_decal():
    m = new_material("M_StartDecal", unreal.BlendMode.BLEND_TRANSLUCENT, two_sided=False)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 0)
    time = MEL.create_material_expression(m, unreal.MaterialExpressionTime, -900, 150)
    ins = [("P", uv, ""), ("T", time, ""),
           ("HL", param(m, "HalfLength", 3.2, -900, 250), ""),
           ("HW", param(m, "HalfWidth", 1.6, -900, 350), "")]
    # one mask for both pins: emissive = Color * mask, opacity = mask * Opacity
    mask_code = (
        "float2 h = float2(HL, HW);\n"
        "float2 d = abs(P) - h;\n"
        "float sd = length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);\n"
        "float aa = max(fwidth(sd), 0.004) * 1.2;\n"
        "float corner = step(h.x - 0.9, abs(P.x)) * step(h.y - 0.7, abs(P.y));\n"
        "float lw = lerp(0.07, 0.16, corner);\n"
        "float frame = 1.0 - smoothstep(lw - aa, lw + aa, abs(sd + lw));\n"
        "frame *= lerp(0.55, 1.0, corner);\n"
        "float fill = (sd < 0.0) ? 0.07 * saturate(1.0 + sd / 0.9) + 0.025 : 0.0;\n"
        "float x = P.x - h.x - 0.8;\n"
        "float f = frac((x - abs(P.y) * 0.75) / 1.25);\n"
        "float fa = max(fwidth(f), 0.01);\n"
        "float chev = smoothstep(0.0, fa, f) * (1.0 - smoothstep(0.32, 0.32 + fa, f));\n"
        "chev *= step(0.0, x) * step(x, 3.6) * (1.0 - smoothstep(h.y * 0.75 - 0.05, h.y * 0.75, abs(P.y)));\n"
        "float sweep = frac(T * 0.55 - x / 5.0);\n"
        "chev *= 0.35 + 0.65 * smoothstep(0.55, 1.0, sweep);\n"
        "return saturate(frame + fill + chev * 0.9);")
    mask = custom(m, mask_code, ins, F1, -450, 100)
    colour = param(m, "Color", unreal.LinearColor(0.35, 1.3, 4.0, 1.0), -450, 350)
    emis = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -150, 250)
    MEL.connect_material_expressions(colour, "", emis, "A")
    MEL.connect_material_expressions(mask, "", emis, "B")
    op = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -150, 450)
    MEL.connect_material_expressions(mask, "", op, "A")
    MEL.connect_material_expressions(param(m, "Opacity", 0.85, -450, 500), "", op, "B")
    MEL.connect_material_property(emis, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    finish(m)


def material(name, blend):
    m = new_material(name, blend)
    m.set_editor_property("used_with_nanite", True)
    colour = param(m, "Color", unreal.LinearColor(4.0, 3.0, 0.2, 1.0), -400, 0)
    MEL.connect_material_property(colour, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if blend == unreal.BlendMode.BLEND_ADDITIVE:
        m.set_editor_property("two_sided", True)
        # the beam fades out with height (local Z of the cylinder, -50..50 cm before scaling)
        uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -700, 300)
        mask = MEL.create_material_expression(m, unreal.MaterialExpressionComponentMask, -550, 300)
        mask.set_editor_property("g", True)
        mask.set_editor_property("r", False)
        MEL.connect_material_expressions(uv, "", mask, "")
        op = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, 300)
        MEL.connect_material_expressions(mask, "", op, "A")
        op.set_editor_property("const_b", 0.6)
        MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    finish(m)


def racing_line():
    """Racing line (Forza-style): flat chevron arrow tips painted along a ribbon on the road.
    Unlit translucent; colour and alpha come from the vertex colour (the game recolours it every
    frame); UV.x runs along the route (one unit per arrow), UV.y across it (0..1)."""
    m = new_material("M_RacingLine", unreal.BlendMode.BLEND_TRANSLUCENT, two_sided=True)
    m.set_editor_property("used_with_nanite", True)
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -800, 0)
    gain = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -500, 0)
    MEL.connect_material_expressions(vc, "", gain, "A")
    gain.set_editor_property("const_b", 1.5)   # bright but still saturated (2.5 bloomed to white)
    MEL.connect_material_property(gain, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    # opacity = alpha * edge(v) * dash(u)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -800, 250)
    code = (
        # a: 0 on the centre line, 1 at the edges; the edges lag behind the centre -> a ^ arrow tip
        "float a = abs(UV.y * 2 - 1);\n"
        "float f = frac(UV.x + 0.55 * a);\n"
        "float aa = fwidth(UV.x) * 1.5 + 0.01;\n"
        "float chevron = smoothstep(0.0, aa, f) * (1 - smoothstep(0.34, 0.34 + aa, f));\n"
        "float edge = 1 - smoothstep(0.82, 1.0, a);\n"
        "return A * chevron * edge;")
    custom_node = custom(m, code, [("UV", uv, ""), ("A", vc, "A")], F1, -450, 250)
    MEL.connect_material_property(custom_node, "", unreal.MaterialProperty.MP_OPACITY)
    finish(m)


def ui_sounds():
    if not UI_SOUNDS.is_dir():
        unreal.log_warning(f"no UI sounds in {UI_SOUNDS}: run tools/ui/make_ui_sounds.py")
        return
    tasks = []
    for wav in sorted(UI_SOUNDS.glob("ui_*.wav")):
        t = unreal.AssetImportTask()
        t.filename = str(wav)
        t.destination_path = AUDIO
        t.destination_name = wav.stem
        t.automated = True
        t.replace_existing = True
        t.save = True
        tasks.append(t)
    ASSETS.import_asset_tasks(tasks)
    for t in tasks:
        wave = unreal.load_asset(f"{AUDIO}/{Path(t.filename).stem}")
        if wave:
            wave.set_editor_property("looping", False)
            EAL.save_loaded_asset(wave, only_if_is_dirty=False)
    unreal.log_warning(f"imported {len(tasks)} UI sounds into {AUDIO}")


def dump_vehicle_input():
    """Log the template's key mappings (which gamepad buttons the car already uses)."""
    imc = unreal.load_asset("/Game/VehicleTemplate/Input/IMC_Vehicle_Default")
    if not imc:
        return
    try:
        maps = imc.get_editor_property("default_key_mappings").get_editor_property("mappings")
    except Exception:
        maps = imc.get_editor_property("mappings")
    for mp in maps:
        action = mp.get_editor_property("action")
        key = mp.get_editor_property("key")
        unreal.log_warning(f"IMC_Vehicle_Default: {action.get_name() if action else None} <- {key.get_editor_property('key_name')}")


gate_body()
gate_curtain()
start_decal()
material("M_GateGlow", unreal.BlendMode.BLEND_OPAQUE)
racing_line()
material("M_GateBeam", unreal.BlendMode.BLEND_ADDITIVE)
ui_sounds()
try:
    dump_vehicle_input()
except Exception as e:      # the IMC property layout changed across engine versions; the dump is informational
    unreal.log_warning(f"IMC dump: {e}")
