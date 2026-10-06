"""Import the STi (tools/blender/build_sti.py -> data/processed/common/car) into /Game/Cambridge/Car.

Run via tools/unreal/import_car.sh (two editor runs: "import", then "post").
Parts and their material specs come from sti_parts.json, tuned by PART_OVERRIDES / PAINT below:
- paint: M_CarPaint, layered clear-coat paint from shaders/carpaint.hlsl (livery base colour, metallic
  flakes from tools/mapgen/make_paint_flakes.py on the base layer's normal, clear coat with the panel normal
  map, non-metallic vinyl decals masked from the livery colours or an optional mask_texture, optional
  ao_texture). Clear-coat pins are wired through MakeMaterialAttributes (see Pins).
- glass / lens: Thin Translucent (tinted transmittance, full-strength reflections), forward shaded.
- everything else: flat constants (+ optional texture / normal_texture / ao_texture per part).
Any "*texture" key in sti_parts.json is imported; unknown ones are treated as linear masks.
Wiring and compile results go to CambridgeRacer/Saved/import_car_materials.txt.
Nanite off (small, partly translucent), no collision (the physics body is the template skeleton's,
refitted by SetChassisBoxes).
AImprezaSTi loads the meshes by path (/Game/Cambridge/Car/sti_<part>/...).
Also imports the synthesised sounds (make_engine_audio.py) into /Game/Cambridge/Car/Audio
(loops set to loop; used by UStiEngineAudio).
"""
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE = sys.argv[-1]
SRC = ROOT / "data/processed/common/car"
DEST = "/Game/Cambridge/Car"
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
import json as _json
SPEC = _json.loads((SRC / "sti_parts.json").read_text())["parts"]
PARTS = tuple(p["part"] for p in SPEC)
AUDIO_SRC = ROOT / "data/processed/common/audio"     # tools/mapgen/make_engine_audio.py
AUDIO = f"{DEST}/Audio"
ONE_SHOTS = {"blowoff", "pop_1", "pop_2", "pop_3", "pop_4", "pop_5"}

def assets_in(folder, cls):
    return [a for a in (unreal.load_asset(p) for p in EAL.list_assets(folder, recursive=True)) if isinstance(a, cls)]


def new_material(name):
    path = f"{DEST}/Materials/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset(name, f"{DEST}/Materials", unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("used_with_nanite", True)
    return m


def constant(m, value, x, y):
    if isinstance(value, (tuple, list)) and len(value) == 4:
        e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant4Vector, x, y)
        e.set_editor_property("constant", unreal.LinearColor(*value))
    elif isinstance(value, (tuple, list)):
        e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, x, y)
        e.set_editor_property("constant", unreal.LinearColor(*value, 1.0))
    else:
        e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, x, y)
        e.set_editor_property("r", value)
    return e


# Material tuning that overrides sti_parts.json (which only has the Blender look-dev values). Car-paint
# numbers are in PAINT; "thin" = Thin Translucent glass (physically based tint + full-strength reflections,
# Opacity is then only the coverage of the base-colour film on top, e.g. dirt).
PART_OVERRIDES = {
    "glass": {"thin": [0.30, 0.335, 0.33], "base_color": [0.01, 0.011, 0.012], "opacity": 0.06, "roughness": 0.02, "specular": 0.5},
    "lens": {"thin": [0.90, 0.91, 0.92], "base_color": [0.9, 0.9, 0.9], "opacity": 0.02, "roughness": 0.015, "specular": 0.5},
    "black": {"base_color": [0.022, 0.022, 0.024], "roughness": 0.62, "specular": 0.45},
    "tire": {"base_color": [0.024, 0.024, 0.025], "roughness": 0.86, "specular": 0.35},
    "chrome": {"base_color": [0.95, 0.95, 0.96], "metallic": 1.0, "roughness": 0.06},
    "rim": {"base_color": [0.80, 0.58, 0.24], "metallic": 1.0, "roughness": 0.3},
    "brake": {"base_color": [0.42, 0.42, 0.43], "metallic": 1.0, "roughness": 0.38},
    "caliper": {"clearcoat": 0.6, "clearcoat_roughness": 0.08, "roughness": 0.4},
    "badge": {"clearcoat": 1.0, "clearcoat_roughness": 0.05},
    "driver_helmet": {"clearcoat": 1.0, "clearcoat_roughness": 0.04, "roughness": 0.3},
    "mesh": {"roughness": 0.5},
}
# M_CarPaint constants (see shaders/carpaint.hlsl for the meaning of each slot)
PAINT = {
    "P1": [50.0, 0.45, 150.0, 1500.0],   # flake tiling per UV (~10 cm tile), strength, fade start / end (cm)
    "P2": [0.6, 0.38, 0.2, 0.5],         # paint metallic, binder roughness, flake roughness, decal roughness
    "P3": [1.0, 0.035, 1.0, 0.08],       # paint coat, coat roughness, decal coat, decal coat roughness
    "P4": [0.3, 1.0, 0.0, 1.0],          # mica flop, coat normal strength, use AO texture, AO strength
    "P5": [0.0, 0.0, 2.0, 0.0],          # use mask texture, decal metallic, paint green gain (hue fix)
}
FLAKES = "paint_flakes_normal.png"      # tools/mapgen/make_paint_flakes.py
SHADERS = Path(__file__).resolve().parent / "shaders"
REPORT = []                             # material wiring / compile results -> Saved/import_car_materials.txt
MP = unreal.MaterialProperty
ATTR_PIN = {"base_color": "BaseColor", "metallic": "Metallic", "specular": "Specular", "roughness": "Roughness",
            "emissive": "EmissiveColor", "opacity": "Opacity", "normal": "Normal", "clearcoat": "ClearCoat",
            "clearcoat_roughness": "ClearCoatRoughness", "ao": "AmbientOcclusion"}
PROP = {"base_color": MP.MP_BASE_COLOR, "metallic": MP.MP_METALLIC, "specular": MP.MP_SPECULAR,
        "roughness": MP.MP_ROUGHNESS, "emissive": MP.MP_EMISSIVE_COLOR, "opacity": MP.MP_OPACITY,
        "normal": MP.MP_NORMAL, "ao": MP.MP_AMBIENT_OCCLUSION}


class Pins:
    """Wires material outputs. Clear-coat materials go through MakeMaterialAttributes -> MaterialAttributes:
    UE 5.8 Python hides MP_CustomData0/1 (the ClearCoat / ClearCoatRoughness pins), but MakeMaterialAttributes
    has ClearCoat / ClearCoatRoughness inputs and MP_MATERIAL_ATTRIBUTES is exposed."""

    def __init__(self, m, attributes):
        self.m, self.name, self.mma = m, m.get_name(), None
        if attributes:
            m.set_editor_property("use_material_attributes", True)
            self.mma = MEL.create_material_expression(m, unreal.MaterialExpressionMakeMaterialAttributes, -200, 0)
            self.check("MaterialAttributes", MEL.connect_material_property(self.mma, "", MP.MP_MATERIAL_ATTRIBUTES))

    def check(self, what, ok):
        REPORT.append(f"{self.name}.{what}: {'ok' if ok else 'FAILED'}")
        if not ok:
            unreal.log_error(f"{self.name}: could not wire {what}")

    def set(self, key, expr, out=""):
        if self.mma is not None:
            self.check(ATTR_PIN[key], MEL.connect_material_expressions(expr, out, self.mma, ATTR_PIN[key]))
        else:
            self.check(key, MEL.connect_material_property(expr, out, PROP[key]))


def tex_object(m, tex, x, y):
    e = MEL.create_material_expression(m, unreal.MaterialExpressionTextureObject, x, y)
    e.set_editor_property("texture", tex)
    return e


def finish(m):
    errors = MEL.recompile_material(m)
    REPORT.append(f"{m.get_name()} compile: {'ok' if not errors else errors}")
    for e in errors or []:
        unreal.log_error(f"{m.get_name()}: {e}")
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def paint_material(spec, textures):
    """Layered car paint (M_CarPaint): livery base colour, metallic flakes on the base layer's normal
    (ClearCoatBottomNormal), clear coat on top with the panel normal map; vinyl decals non-metallic."""
    m = new_material("M_Car" + spec["part"].capitalize())
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    pins = Pins(m, attributes=True)
    livery = textures[spec["texture"]]
    have = lambda k: k in spec and spec[k] in textures
    p = {k: list(v) for k, v in PAINT.items()}
    p["P4"][2] = 1.0 if have("ao_texture") else 0.0
    p["P5"][0] = 1.0 if have("mask_texture") else 0.0
    if FLAKES not in textures:
        p["P1"][1] = 0.0
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, -200)
    ins = [("UV", uv, ""),
           ("L", tex_object(m, livery, -900, 0), ""),
           ("PN", tex_object(m, textures[spec["normal_texture"]] if have("normal_texture") else livery, -900, 100), ""),
           ("FK", tex_object(m, textures.get(FLAKES, livery), -900, 200), ""),
           ("AOT", tex_object(m, textures[spec["ao_texture"]] if have("ao_texture") else livery, -900, 300), ""),
           ("MK", tex_object(m, textures[spec["mask_texture"]] if have("mask_texture") else livery, -900, 400), ""),
           ("D", MEL.create_material_expression(m, unreal.MaterialExpressionPixelDepth, -900, 500), ""),
           ("VN", MEL.create_material_expression(m, unreal.MaterialExpressionVertexNormalWS, -900, 600), ""),
           ("CV", MEL.create_material_expression(m, unreal.MaterialExpressionCameraVectorWS, -900, 700), "")]
    if not have("normal_texture"):
        p["P4"][1] = 0.0
    ins += [(k, constant(m, v, -900, 800 + 60 * i), "") for i, (k, v) in enumerate(sorted(p.items()))]
    F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, -500, 0)
    pinlist = []
    for n, _, _ in ins:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        pinlist.append(ci)
    c.set_editor_property("inputs", pinlist)
    outs = []
    for n, t in (("Metal", F1), ("Rough", F1), ("CC", F1), ("CCR", F1), ("AO", F1), ("Nrm", F3), ("BotNrm", F3)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    c.set_editor_property("additional_outputs", outs)
    c.set_editor_property("output_type", F3)
    c.set_editor_property("description", "carpaint.hlsl")
    c.set_editor_property("code", (SHADERS / "carpaint.hlsl").read_text())
    for n, expr, pin in ins:
        pins.check(f"in.{n}", MEL.connect_material_expressions(expr, pin, c, n))
    for key, out in (("base_color", "return"), ("metallic", "Metal"), ("roughness", "Rough"), ("clearcoat", "CC"),
                     ("clearcoat_roughness", "CCR"), ("ao", "AO"), ("normal", "Nrm")):
        pins.set(key, c, out)
    bottom = MEL.create_material_expression(m, unreal.MaterialExpressionClearCoatNormalCustomOutput, -200, 400)
    pins.check("ClearCoatBottomNormal", MEL.connect_material_expressions(c, "BotNrm", bottom, ""))
    return finish(m)


def part_material(spec, textures):
    """Material for one part from its sti_parts.json entry (+ PART_OVERRIDES)."""
    spec = {**spec, **PART_OVERRIDES.get(spec["part"], {})}
    if spec["part"] == "paint" and spec.get("texture") in textures:
        return paint_material(spec, textures)
    name = "M_Car" + spec["part"].capitalize()
    m = new_material(name)
    coat = spec.get("clearcoat")
    thin = spec.get("thin")
    opacity = spec.get("opacity")
    if coat:
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    elif thin:
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT)
    pins = Pins(m, attributes=bool(coat))
    if opacity is not None or thin:
        m.set_editor_property("used_with_nanite", False)
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        # Surface ForwardShading: per-pixel specular + reflections (required by Thin Translucent)
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        pins.set("opacity", constant(m, float(opacity if opacity is not None else 0.0), -400, 450))
    if thin:
        t = MEL.create_material_expression(m, unreal.MaterialExpressionThinTranslucentMaterialOutput, -200, 500)
        pins.check("TransmittanceColor", MEL.connect_material_expressions(constant(m, tuple(thin), -400, 500), "", t, "TransmittanceColor"))
    base = None
    if spec.get("texture") in textures:
        base = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -700, 0)
        base.set_editor_property("texture", textures[spec["texture"]])
        base_out = "RGB"
    else:
        base, base_out = constant(m, tuple(spec.get("base_color", (0.5, 0.5, 0.5))), -700, 0), ""
    if spec.get("ao_texture") in textures:
        # baked AO / cavity: AO pin (indirect light) and half-strength into the base colour (direct light)
        uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 150)
        uv.set_editor_property("coordinate_index", int(spec.get("ao_uv", 0)))
        ao = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -700, 150)
        ao.set_editor_property("texture", textures[spec["ao_texture"]])
        ao.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        MEL.connect_material_expressions(uv, "", ao, "UVs")
        pins.set("ao", ao, "R")
        half = MEL.create_material_expression(m, unreal.MaterialExpressionLinearInterpolate, -500, 100)
        MEL.connect_material_expressions(constant(m, 1.0, -700, 300), "", half, "A")
        MEL.connect_material_expressions(ao, "R", half, "B")
        MEL.connect_material_expressions(constant(m, 0.5, -700, 350), "", half, "Alpha")
        mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -400, 0)
        MEL.connect_material_expressions(base, base_out, mul, "A")
        MEL.connect_material_expressions(half, "", mul, "B")
        base, base_out = mul, ""
    pins.set("base_color", base, base_out)
    if spec.get("normal_texture") in textures:
        n = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -700, 250)
        n.set_editor_property("texture", textures[spec["normal_texture"]])
        n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
        pins.set("normal", n, "RGB")
    pins.set("metallic", constant(m, float(spec.get("metallic", 0.0)), -400, 150))
    pins.set("roughness", constant(m, float(spec.get("roughness", 0.5)), -400, 250))
    if "specular" in spec:
        pins.set("specular", constant(m, float(spec["specular"]), -400, 200))
    if spec.get("emissive"):
        pins.set("emissive", constant(m, tuple(spec["emissive"]), -400, 350))
    if coat:
        pins.set("clearcoat", constant(m, float(coat), -400, 500))
        pins.set("clearcoat_roughness", constant(m, float(spec.get("clearcoat_roughness", 0.05)), -400, 550))
    return finish(m)


def texture_kind(key, tex):
    """Compression for a texture by the sti_parts.json key that references it."""
    if tex == FLAKES:
        return "flakes"
    if key == "normal_texture":
        return "normal"
    if key == "texture" or key.endswith("color_texture") or key.endswith("emissive_texture"):
        return "color"
    return "mask"        # ao_texture, mask_texture, roughness_texture, ...: linear data


def texture_refs():
    """{file: kind} for every *texture key in sti_parts.json (plus the generated flake normal)."""
    refs = {}
    for p in SPEC:
        for k, v in p.items():
            if k.endswith("texture") and isinstance(v, str) and (SRC / v).exists():
                refs.setdefault(v, texture_kind(k, v))
            elif k.endswith("texture"):
                unreal.log_warning(f"sti_parts.json {p['part']}.{k}: {v} not found, ignored")
    if (SRC / FLAKES).exists():
        refs[FLAKES] = "flakes"
    return refs


# STi chassis collision (mesh space, cm; ground at z = -8.6): the lower body box starts 20 cm above the
# ground so 15 cm kerbs reach the tyres, not the box; a narrower box for the cabin
CHASSIS_BOXES = [((-0.6, 0.0, 52.0), (436.0, 168.0, 80.0)), ((-45.0, 0.0, 112.0), (175.0, 120.0, 40.0))]
PHYSICS_ASSET = "/Game/Vehicles/SportsCar/PA_SportsCar"


def main():
    if PHASE == "import":
        tasks = []
        sources = [(f"sti_{p['part']}", SRC / p["file"]) for p in SPEC]
        for tex in sorted(texture_refs()):
            sources.append(("T_" + Path(tex).stem, SRC / tex))
        if EAL.does_directory_exist(AUDIO):
            EAL.delete_directory(AUDIO)
        for wav in sorted(AUDIO_SRC.glob("*.wav")):
            if " " in wav.name:   # iCloud conflict copies ("pop_4 2.wav") would import as pop_4_2
                continue
            t = unreal.AssetImportTask()
            t.filename = str(wav)
            t.destination_path = AUDIO
            t.destination_name = wav.stem
            t.automated = True
            t.replace_existing = True
            t.save = True
            tasks.append(t)
        for name, src in sources:
            if EAL.does_directory_exist(f"{DEST}/{name}"):
                EAL.delete_directory(f"{DEST}/{name}")
            t = unreal.AssetImportTask()
            t.filename = str(src)
            t.destination_path = f"{DEST}/{name}"
            t.destination_name = name
            t.automated = True
            t.replace_existing = True
            t.save = True
            tasks.append(t)
        ASSETS.import_asset_tasks(tasks)
        return

    for wave in assets_in(AUDIO, unreal.SoundWave):
        wave.set_editor_property("looping", wave.get_name() not in ONE_SHOTS)
        if wave.get_name().startswith("engine_"):
            # silent loops keep playing (crank-locked crossfades, see StiEngineAudio) at up to 10x speed:
            # uncompressed PCM decodes that for free (~6.5 MB in total)
            for prop, val in (("sound_asset_compression_type", unreal.SoundAssetCompressionType.PCM),
                              ("virtualization_mode", unreal.VirtualizationMode.PLAY_WHEN_SILENT)):
                try:
                    wave.set_editor_property(prop, val)
                except Exception as e:
                    unreal.log_warning(f"{wave.get_name()} {prop}: {e}")
        EAL.save_loaded_asset(wave, only_if_is_dirty=False)
    pa = unreal.load_asset(PHYSICS_ASSET)
    report = unreal.CambridgeWorldTools.set_chassis_boxes(pa, [unreal.Vector(*c) for c, _ in CHASSIS_BOXES],
                                                          [unreal.Vector(*s) for _, s in CHASSIS_BOXES])
    EAL.save_loaded_asset(pa, only_if_is_dirty=False)
    (SRC / "chassis_report.txt").write_text(report)
    textures = {}
    TCS = unreal.TextureCompressionSettings
    for tex, kind in sorted(texture_refs().items()):
        found = assets_in(f"{DEST}/T_{Path(tex).stem}", unreal.Texture2D)
        if not found:
            unreal.log_warning(f"texture {tex} was not imported, ignored")
            continue
        t = found[0]
        t.set_editor_property("srgb", kind == "color")
        t.set_editor_property("compression_settings", {"normal": TCS.TC_NORMALMAP, "flakes": TCS.TC_NORMALMAP,
                                                       "color": TCS.TC_DEFAULT, "mask": TCS.TC_MASKS}[kind])
        t.set_editor_property("flip_green_channel", kind == "normal")      # OpenGL -> Unreal (Blender maps)
        EAL.save_loaded_asset(t, only_if_is_dirty=False)
        textures[tex] = t
    mats = {p["part"]: part_material(p, textures) for p in SPEC}
    (ROOT / "CambridgeRacer/Saved/import_car_materials.txt").write_text("\n".join(REPORT) + "\n")
    for part in PARTS:
        for mesh in assets_in(f"{DEST}/sti_{part}", unreal.StaticMesh):
            for i in range(len(mesh.get_editor_property("static_materials"))):
                mesh.set_material(i, mats[part])
            ns = mesh.get_editor_property("nanite_settings")
            ns.enabled = False
            mesh.set_editor_property("nanite_settings", ns)
            EAL.save_loaded_asset(mesh, only_if_is_dirty=False)


main()
