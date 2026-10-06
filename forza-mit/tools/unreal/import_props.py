"""Import shared props (CC0 Poly Haven models + generated poles) into /Game/Cambridge/Props.

Run via tools/unreal/import_props.sh (two editor runs: "import", then "post").
post: Nanite on the tree (3.7 M vertices), masked two-sided foliage material for the leaf cards
(the glTF uses BLEND; masked is far cheaper and works with Nanite), OpenGL normal
maps flipped to Unreal's convention, simple painted-metal materials for the generated poles.

Street trees: the 18 procedural variants (data/processed/common/props/trees, tools/blender/
build_trees.py) -> /Game/Cambridge/Props/tree_<variant>. Textures are not in the glbs; the bark sets
listed in trees.json are imported to Props/TreeBark. One bark master + one OPAQUE two-sided-foliage
leaf master (no masked material: masked Nanite foliage cost ~12 ms), instances per bark texture /
leaf parameter set, under Props/Materials/Trees. See setup_trees().
"""
import json
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE = sys.argv[-1]
DEST = "/Game/Cambridge/Props"
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()

SOURCES = {
    "jacaranda_tree": ROOT / "data/raw/models/jacaranda_tree/jacaranda_tree.gltf",
    "street_lamp_02": ROOT / "data/raw/models/street_lamp_02/street_lamp_02.gltf",
    "lamp_post": ROOT / "data/processed/common/props/lamp_post.glb",
    "cobra_pole": ROOT / "data/processed/common/props/cobra_pole.glb",
    # keyed RGBA leaf atlas (tools/mapgen/make_leaf_alpha.py): the glTF's own is a JPEG on black
    "jacaranda_leaves_rgba": ROOT / "data/processed/common/props/jacaranda_leaves_rgba.png",
    # street furniture: Poly Haven CC0 models merged to one mesh (tools/blender/merge_model.py) ...
    "fire_hydrant": ROOT / "data/processed/common/props/fire_hydrant.glb",
    "metal_trash_can": ROOT / "data/processed/common/props/metal_trash_can.glb",
    "painted_wooden_bench": ROOT / "data/processed/common/props/painted_wooden_bench.glb",
    # ... and generated ones (tools/mapgen/props.py write_furniture_meshes)
    "bike_rack": ROOT / "data/processed/common/props/bike_rack.glb",
    "parking_meter": ROOT / "data/processed/common/props/parking_meter.glb",
    "signal_pole": ROOT / "data/processed/common/props/signal_pole.glb",
    "signal_lens": ROOT / "data/processed/common/props/signal_lens.glb",
    "signal_lens_m": ROOT / "data/processed/common/props/signal_lens_m.glb",   # lenses on the other side
    "utility_pole": ROOT / "data/processed/common/props/utility_pole.glb",
    "bus_shelter": ROOT / "data/processed/common/props/bus_shelter.glb",
    "bus_shelter_glass": ROOT / "data/processed/common/props/bus_shelter_glass.glb",
}
TEXTURED_PROPS = {"fire_hydrant": True, "metal_trash_can": True, "painted_wooden_bench": False}   # -> Nanite?

# procedural street trees (meshes in metres, Y-up glTF; slots "bark" (0) and "leaves" (1))
TREES = json.loads((ROOT / "data/processed/common/props/trees/trees.json").read_text())["variants"]
SOURCES.update({f"tree_{v}": ROOT / spec["file"] for v, spec in TREES.items()})
TREE_BARK = f"{DEST}/TreeBark"
TREE_MATS = f"{DEST}/Materials/Trees"
# Nanite distance behaviour of the canopies: "PRESERVE_AREA" (the task's choice; the 5.8 header calls
# it the legacy foliage technique) or "VOXELIZE" (5.8: distant leaves become voxels) to A/B
TREE_SHAPE_PRESERVATION = "PRESERVE_AREA"


def bark_sets():
    """{set name: {"D", "N", "R": source path}} for the bark textures trees.json uses (the set name is
    the texture folder, e.g. Bark001, bark_brown_02, birch_white). Normal = DirectX ("nor")."""
    out = {}
    for spec in TREES.values():
        b = spec["materials"]["bark"]
        out.setdefault(Path(b["texture"]).parent.name, {"D": ROOT / b["texture"], "N": ROOT / b["normal"],
                                                        "R": ROOT / b["roughness"]})
    return out


def assets_in(folder, cls):
    return [a for a in (unreal.load_asset(p) for p in EAL.list_assets(folder, recursive=True)) if isinstance(a, cls)]


def new_material(name):
    """Fresh material asset with the usage flags the props need (Nanite trees, instanced props):
    without them a cooked game falls back to the default material."""
    path = f"{DEST}/Materials/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    m = ASSETS.create_asset(name, f"{DEST}/Materials", unreal.Material, unreal.MaterialFactoryNew())
    for flag in ("used_with_nanite", "used_with_instanced_static_meshes"):
        m.set_editor_property(flag, True)
    return m


def textured_material(name, diff, nor, rough, tint=(1.0, 1.0, 1.0)):
    """Opaque two-sided PBR material from colour / normal / roughness maps (tree bark).
    Replaces the glTF importer's instances: their parents live in read-only engine content (no
    usage flags can be saved) and multiply the base colour by the model's vertex colours."""
    m = new_material(name)
    m.set_editor_property("two_sided", True)
    d = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 0)
    d.set_editor_property("texture", diff)
    k = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -400, 150)
    k.set_editor_property("constant", unreal.LinearColor(*tint, 1.0))
    mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -200, 0)
    MEL.connect_material_expressions(d, "RGB", mul, "A")
    MEL.connect_material_expressions(k, "", mul, "B")
    n = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 250)
    n.set_editor_property("texture", nor)
    n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    r = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 500)
    r.set_editor_property("texture", rough)
    r.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    MEL.connect_material_property(mul, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(n, "RGB", unreal.MaterialProperty.MP_NORMAL)
    MEL.connect_material_property(r, "R", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def importer_instances(folder):
    """{slot / glTF material name: the glTF importer's MaterialInstance} under a prop's import folder.
    These stay in the folder after post, so post can be re-run on its own (see material_from_instance)."""
    return {mi.get_name(): mi for mi in assets_in(folder, unreal.MaterialInstance)}


# Colour grade of the Poly Haven furniture (sRGB-ish albedo x value after desaturating by `desat`).
# The source textures are red paint (fire_hydrant_diff mean sRGB 135/72/57, painted_wooden_bench 86/52/42).
# Cambridge's hydrants are colour-coded by flow (most are blue, cambridgema.gov CFD 2025-07) and its park
# benches are dark / weathered, so the red is toned down to dark painted iron and neutral weathered wood.
# (0.0, 1.0) = the asset's authored colours (no desaturation, value x1).
PROP_GRADE = {"fire_hydrant": (0.75, 0.60), "painted_wooden_bench": (0.85, 0.80)}


def material_from_instance(name, mi, grade=None):
    """Own opaque material from a glTF-imported instance's textures (base colour, normal, metallic-
    roughness packed as Poly Haven ARM: G roughness, B metal). The importer's instances have read-only
    engine parents, so they can't carry the Nanite / instancing usage flags.
    `mi` must be the importer's instance (NOT the slot's current material: after a first post run the slot
    holds our own M_<prop>_<i>, which has no texture parameters; reading it gave an empty, black material
    when post was re-run on its own). grade = (desaturate 0..1, value multiplier) or None."""
    if not isinstance(mi, unreal.MaterialInstance):
        raise RuntimeError(f"{name}: expected the glTF importer's MaterialInstance, got {mi}")
    tex = {str(t.get_editor_property("parameter_info").get_editor_property("name")): t.get_editor_property("parameter_value")
           for t in mi.get_editor_property("texture_parameter_values")}
    missing = [k for k in ("BaseColorTexture", "NormalTexture", "MetallicRoughnessTexture") if not tex.get(k)]
    if missing:
        raise RuntimeError(f"{name}: importer instance {mi.get_path_name()} has no {missing}")
    m = new_material(name)
    col = tex.get("BaseColorTexture")
    if col:
        d = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 0)
        d.set_editor_property("texture", col)
        out, pin = d, "RGB"
        if grade and grade != (0.0, 1.0):
            desat = MEL.create_material_expression(m, unreal.MaterialExpressionDesaturation, -330, 0)
            assert MEL.connect_material_expressions(d, "RGB", desat, "")
            k = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -480, 120)
            k.set_editor_property("r", float(grade[0]))
            assert MEL.connect_material_expressions(k, "", desat, "Fraction")
            mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -180, 0)
            assert MEL.connect_material_expressions(desat, "", mul, "A")
            mul.set_editor_property("const_b", float(grade[1]))
            out, pin = mul, ""
        assert MEL.connect_material_property(out, pin, unreal.MaterialProperty.MP_BASE_COLOR)
    nrm = tex.get("NormalTexture")
    if nrm:
        n = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 250)
        n.set_editor_property("texture", nrm)
        n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
        MEL.connect_material_property(n, "RGB", unreal.MaterialProperty.MP_NORMAL)
    arm = tex.get("MetallicRoughnessTexture")
    if arm:
        a = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 500)
        a.set_editor_property("texture", arm)
        a.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        MEL.connect_material_property(a, "G", unreal.MaterialProperty.MP_ROUGHNESS)
        MEL.connect_material_property(a, "B", unreal.MaterialProperty.MP_METALLIC)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def simple_material(name, color, rough, metal):
    """Opaque constant material (poles)."""
    m = new_material(name)
    for prop, val, y in [(unreal.MaterialProperty.MP_BASE_COLOR, color, 0), (unreal.MaterialProperty.MP_ROUGHNESS, rough, 200),
                         (unreal.MaterialProperty.MP_METALLIC, metal, 300)]:
        if isinstance(val, (list, tuple)):
            e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -400, y)
            e.set_editor_property("constant", unreal.LinearColor(*val, 1.0))
        else:
            e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -400, y)
            e.set_editor_property("r", val)
        MEL.connect_material_property(e, "", prop)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def foliage_material(diff, nor, rough):
    m = new_material("M_TreeLeaves")
    m.set_editor_property("two_sided", True)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)      # leaf cards: alpha in the diffuse
    m.set_editor_property("opacity_mask_clip_value", 0.4)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    d = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 0)
    d.set_editor_property("texture", diff)
    n = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 250)
    n.set_editor_property("texture", nor)
    n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    a = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSample, -500, 500)
    a.set_editor_property("texture", rough)
    a.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tint = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -200, 0)
    MEL.connect_material_expressions(d, "RGB", tint, "A")
    k = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -400, 120)
    k.set_editor_property("constant", unreal.LinearColor(0.85, 0.95, 0.75, 1.0))   # a bit greener / less saturated
    MEL.connect_material_expressions(k, "", tint, "B")
    ss = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -200, 700)
    MEL.connect_material_expressions(d, "RGB", ss, "A")
    k2 = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -400, 760)
    k2.set_editor_property("r", 0.6)
    MEL.connect_material_expressions(k2, "", ss, "B")
    MEL.connect_material_property(tint, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(n, "RGB", unreal.MaterialProperty.MP_NORMAL)
    MEL.connect_material_property(a, "R", unreal.MaterialProperty.MP_ROUGHNESS)
    # far leaves: the averaged alpha of coarse mips drops below the clip value and canopies go bare,
    # so the mask is boosted with distance (x1 near, up to x3 beyond LEAF_FAR_CM)
    depth = MEL.create_material_expression(m, unreal.MaterialExpressionPixelDepth, -700, 900)
    far = MEL.create_material_expression(m, unreal.MaterialExpressionDivide, -550, 900)
    MEL.connect_material_expressions(depth, "", far, "A")
    far.set_editor_property("const_b", LEAF_FAR_CM)
    sat = MEL.create_material_expression(m, unreal.MaterialExpressionSaturate, -420, 900)
    MEL.connect_material_expressions(far, "", sat, "")
    boost = MEL.create_material_expression(m, unreal.MaterialExpressionLinearInterpolate, -300, 900)
    boost.set_editor_property("const_a", 1.0)
    boost.set_editor_property("const_b", 3.0)
    MEL.connect_material_expressions(sat, "", boost, "Alpha")
    mask = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -150, 850)
    MEL.connect_material_expressions(d, "A", mask, "A")
    MEL.connect_material_expressions(boost, "", mask, "B")
    MEL.connect_material_property(mask, "", unreal.MaterialProperty.MP_OPACITY_MASK)
    MEL.connect_material_property(ss, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


LEAF_FAR_CM = 15000.0   # leaf opacity boost reaches x3 at this camera distance

# upright collision capsule per prop (radius, height) in cm, mesh space
TRUNK_CM = {"jacaranda_tree": (25.0, 400.0), "lamp_post": (14.0, 375.0), "cobra_pole": (11.0, 860.0),
            "fire_hydrant": (18.0, 80.0), "metal_trash_can": (30.0, 95.0), "parking_meter": (8.0, 145.0),
            "signal_pole": (15.0, 620.0), "utility_pole": (16.0, 1050.0)}


def main():
    if PHASE == "import":
        tasks = []
        for name, src in SOURCES.items():
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
        if EAL.does_directory_exist(TREE_BARK):
            EAL.delete_directory(TREE_BARK)
        for name, maps in bark_sets().items():
            for kind, src in maps.items():
                t = unreal.AssetImportTask()
                t.filename = str(src)
                t.destination_path = f"{TREE_BARK}/{name}"
                t.destination_name = f"T_Bark_{name}_{kind}"
                t.automated = True
                t.replace_existing = True
                t.save = True
                tasks.append(t)
        ASSETS.import_asset_tasks(tasks)
        return

    # normal maps: OpenGL -> Unreal (flip green)
    for name in ("jacaranda_tree", "street_lamp_02"):
        for t in assets_in(f"{DEST}/{name}", unreal.Texture2D):
            if "nor" in t.get_name().lower():
                t.set_editor_property("flip_green_channel", True)
                t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
                t.set_editor_property("srgb", False)
                EAL.save_loaded_asset(t, only_if_is_dirty=False)

    tree = assets_in(f"{DEST}/jacaranda_tree", unreal.StaticMesh)[0]
    texs = {t.get_name().lower(): t for t in assets_in(f"{DEST}/jacaranda_tree", unreal.Texture2D)}
    pick = lambda key: next(v for k, v in texs.items() if "leaves" in k and key in k)
    leaf_diff = assets_in(f"{DEST}/jacaranda_leaves_rgba", unreal.Texture2D)[0]
    leaf_diff.set_editor_property("srgb", True)
    leaf_diff.set_editor_property("compression_no_alpha", False)
    leaf_diff.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
    try:   # keep the leaf coverage constant down the mip chain (otherwise canopies thin out with distance)
        leaf_diff.set_editor_property("do_scale_mips_for_alpha_coverage", True)
        leaf_diff.set_editor_property("alpha_coverage_thresholds", unreal.Vector4(0.0, 0.0, 0.0, 0.4))
    except Exception as e:
        unreal.log_warning(f"alpha coverage mips: {e}")
    EAL.save_loaded_asset(leaf_diff, only_if_is_dirty=False)
    leaves = foliage_material(leaf_diff, pick("nor"), pick("rough"))
    pick_part = lambda part, key: next(v for k, v in texs.items() if part in k and key in k)
    bark = {part: textured_material(f"M_Tree{part.capitalize()}", pick_part(part, "diff"), pick_part(part, "nor"),
                                    pick_part(part, "rough"))
            for part in ("trunk", "branches")}
    for i, sm in enumerate(tree.get_editor_property("static_materials")):
        slot = str(sm.get_editor_property("material_slot_name")).lower()
        if "leaves" in slot:
            tree.set_material(i, leaves)
        else:
            tree.set_material(i, bark["trunk" if "trunk" in slot else "branches"])
    ns = tree.get_editor_property("nanite_settings")
    ns.enabled = True
    set_shape_preservation(ns, "PRESERVE_AREA", "jacaranda_tree")   # keeps foliage from thinning out at distance
    tree.set_editor_property("nanite_settings", ns)
    # the car hits the trunk only (the canopy is well above roof height); scaled per instance
    unreal.CambridgeWorldTools.set_trunk_collision(tree, *TRUNK_CM["jacaranda_tree"])
    EAL.save_loaded_asset(tree, only_if_is_dirty=False)

    black = simple_material("M_PaintedBlack", (0.015, 0.015, 0.015), 0.45, 0.6)
    galv = simple_material("M_Galvanised", (0.45, 0.46, 0.47), 0.4, 1.0)
    glass = simple_material("M_LampGlass", (0.05, 0.05, 0.045), 0.08, 0.0)
    # small props: no Nanite. The lantern's imported materials (read-only engine parents, translucent
    # glass) can't carry the instancing usage flag, so it gets painted metal + opaque glass instead
    for mesh in assets_in(f"{DEST}/street_lamp_02", unreal.StaticMesh):
        for i, sm in enumerate(mesh.get_editor_property("static_materials")):
            slot = str(sm.get_editor_property("material_slot_name")).lower()
            mesh.set_material(i, glass if ("glass" in slot or "bulb" in slot) else black)
        ns = mesh.get_editor_property("nanite_settings")
        ns.enabled = False
        mesh.set_editor_property("nanite_settings", ns)
        EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    # street furniture: own materials for the Poly Haven models, flat ones for the generated parts
    for name, nanite in TEXTURED_PROPS.items():
        src = importer_instances(f"{DEST}/{name}")
        for mesh in assets_in(f"{DEST}/{name}", unreal.StaticMesh):
            for i, sm in enumerate(mesh.get_editor_property("static_materials")):
                slot = str(sm.get_editor_property("material_slot_name"))
                cur = sm.get_editor_property("material_interface")
                mi = src.get(slot) or (cur if isinstance(cur, unreal.MaterialInstance) else None)
                if mi is None:
                    raise RuntimeError(f"{name} slot {i} '{slot}': no glTF importer instance in {sorted(src)}")
                mesh.set_material(i, material_from_instance(f"M_{name}_{i}", mi, PROP_GRADE.get(name)))
            if name in TRUNK_CM:
                unreal.CambridgeWorldTools.set_trunk_collision(mesh, *TRUNK_CM[name])
            ns = mesh.get_editor_property("nanite_settings")
            ns.enabled = nanite
            mesh.set_editor_property("nanite_settings", ns)
            EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    wood = simple_material("M_Wood", (0.16, 0.11, 0.07), 0.85, 0.0)
    shelter_glass = simple_material("M_ShelterGlass", (0.22, 0.27, 0.28), 0.06, 0.0)
    for name, mat in (("bike_rack", galv), ("parking_meter", galv), ("signal_pole", black), ("signal_lens", glass), ("signal_lens_m", glass),
                      ("utility_pole", wood), ("bus_shelter", galv), ("bus_shelter_glass", shelter_glass)):
        for mesh in assets_in(f"{DEST}/{name}", unreal.StaticMesh):
            mesh.set_material(0, mat)
            if name in TRUNK_CM:
                unreal.CambridgeWorldTools.set_trunk_collision(mesh, *TRUNK_CM[name])
            ns = mesh.get_editor_property("nanite_settings")
            ns.enabled = False
            mesh.set_editor_property("nanite_settings", ns)
            EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    for name, mat in (("lamp_post", black), ("cobra_pole", galv)):
        for mesh in assets_in(f"{DEST}/{name}", unreal.StaticMesh):
            mesh.set_material(0, mat)
            unreal.CambridgeWorldTools.set_trunk_collision(mesh, *TRUNK_CM[name])
            ns = mesh.get_editor_property("nanite_settings")
            ns.enabled = False
            mesh.set_editor_property("nanite_settings", ns)
            EAL.save_loaded_asset(mesh, only_if_is_dirty=False)

    setup_trees()


# ------------------------------------------------------------------ procedural street trees
def set_shape_preservation(ns, mode, label):
    """FMeshNaniteSettings.ShapePreservation (5.8: None / PreserveArea / Voxelize)."""
    try:
        ns.set_editor_property("shape_preservation", getattr(unreal.NaniteShapePreservation, mode))
    except Exception as e:
        unreal.log_warning(f"{label}: nanite shape_preservation {mode}: {e}")


def param(m, cls, name, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    e.set_editor_property("parameter_name", name)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, a_pin, b, b_pin):
    assert MEL.connect_material_expressions(a, a_pin, b, b_pin), f"{a.get_name()}.{a_pin} -> {b.get_name()}.{b_pin}"


def prop_link(e, pin, prop):
    assert MEL.connect_material_property(e, pin, prop), f"{e.get_name()}.{pin} -> {prop}"


def tree_bark_textures():
    """Configure the imported bark textures; -> {set: {"D", "N", "R": Texture2D}}."""
    out = {}
    for name in bark_sets():
        tex = {}
        for t in assets_in(f"{TREE_BARK}/{name}", unreal.Texture2D):
            kind = t.get_name().rsplit("_", 1)[-1]
            if kind == "N":     # DirectX normal map: Unreal's convention, no green flip
                t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
                t.set_editor_property("srgb", False)
                t.set_editor_property("flip_green_channel", False)
            elif kind == "R":   # roughness (R) or Poly Haven ARM (G = roughness)
                t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
                t.set_editor_property("srgb", False)
            else:
                t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
                t.set_editor_property("srgb", True)
            t.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
            EAL.save_loaded_asset(t, only_if_is_dirty=False)
            tex[kind] = t
        assert set(tex) == {"D", "N", "R"}, f"bark textures {name}: {sorted(tex)}"
        out[name] = tex
    return out


def tree_material(name):
    m = ASSETS.create_asset(name, TREE_MATS, unreal.Material, unreal.MaterialFactoryNew())
    for flag in ("used_with_nanite", "used_with_instanced_static_meshes"):
        m.set_editor_property(flag, True)
    return m


def bark_master(default_tex):
    """Opaque bark: BaseColor = texture x Tint x vertex colour RGB (the glb's COLOR_0: crown occlusion x
    darker young twigs; Interchange stores glTF COLOR_0 so the shader reads it linear, as authored).
    UV0 is already in texture repeats (tree_gen.py divides by texture_size_m), so UVScale stays 1.
    Roughness = R or G channel of the roughness map (RoughnessFromG = 0 / 1)."""
    m = tree_material("M_TreeBark_Master")
    m.set_editor_property("two_sided", True)      # glb: doubleSided (thin twigs / open branch ends)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -1300, 0)
    su = param(m, unreal.MaterialExpressionScalarParameter, "UVScaleU", -1300, 120, default_value=1.0)
    sv = param(m, unreal.MaterialExpressionScalarParameter, "UVScaleV", -1300, 200, default_value=1.0)
    app = MEL.create_material_expression(m, unreal.MaterialExpressionAppendVector, -1150, 150)
    link(su, "", app, "A")
    link(sv, "", app, "B")
    uvs = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -1000, 50)
    link(uv, "", uvs, "A")
    link(app, "", uvs, "B")
    S = unreal.MaterialSamplerType
    d = param(m, unreal.MaterialExpressionTextureSampleParameter2D, "BaseColorTex", -800, 0,
              texture=default_tex["D"], sampler_type=S.SAMPLERTYPE_COLOR)
    n = param(m, unreal.MaterialExpressionTextureSampleParameter2D, "NormalTex", -800, 300,
              texture=default_tex["N"], sampler_type=S.SAMPLERTYPE_NORMAL)
    r = param(m, unreal.MaterialExpressionTextureSampleParameter2D, "RoughnessTex", -800, 600,
              texture=default_tex["R"], sampler_type=S.SAMPLERTYPE_MASKS)
    for t in (d, n, r):
        link(uvs, "", t, "UVs")
    tint = param(m, unreal.MaterialExpressionVectorParameter, "Tint", -800, -200,
                 default_value=unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -800, -350)
    m1 = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -500, -100)
    link(d, "RGB", m1, "A")
    link(tint, "RGB", m1, "B")
    m2 = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, -150)
    link(m1, "", m2, "A")
    link(vc, "", m2, "B")      # first output = RGB
    g = param(m, unreal.MaterialExpressionScalarParameter, "RoughnessFromG", -600, 750, default_value=0.0)
    rl = MEL.create_material_expression(m, unreal.MaterialExpressionLinearInterpolate, -450, 620)
    link(r, "R", rl, "A")
    link(r, "G", rl, "B")
    link(g, "", rl, "Alpha")
    prop_link(m2, "", unreal.MaterialProperty.MP_BASE_COLOR)
    prop_link(n, "RGB", unreal.MaterialProperty.MP_NORMAL)
    prop_link(rl, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def leaf_master():
    """Opaque two-sided foliage leaves (real leaf geometry, no alpha): BaseColor = vertex colour RGB
    (final albedo incl. baked occlusion) x Tint; transmission = SubsurfaceColor x Strength x vertex
    alpha (occlusion: inner leaves glow less); constant roughness / specular per instance."""
    m = tree_material("M_TreeLeaves_Opaque")
    m.set_editor_property("two_sided", True)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -800, 0)
    tint = param(m, unreal.MaterialExpressionVectorParameter, "Tint", -800, 150,
                 default_value=unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    base = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -500, 50)
    link(vc, "", base, "A")    # first output = RGB
    link(tint, "RGB", base, "B")
    rough = param(m, unreal.MaterialExpressionScalarParameter, "Roughness", -500, 250, default_value=0.55)
    spec = param(m, unreal.MaterialExpressionScalarParameter, "Specular", -500, 330, default_value=0.35)
    ssc = param(m, unreal.MaterialExpressionVectorParameter, "SubsurfaceColor", -800, 450,
                default_value=unreal.LinearColor(0.45, 0.6, 0.12, 1.0))
    sss = param(m, unreal.MaterialExpressionScalarParameter, "SubsurfaceStrength", -800, 600, default_value=0.5)
    s1 = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -500, 500)
    link(ssc, "RGB", s1, "A")
    link(sss, "", s1, "B")
    s2 = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, 550)
    link(s1, "", s2, "A")
    # VertexColor's default ("") output is RGB only (float3): masking A off it fails to compile and
    # UE silently renders the grey Default Material on every leaf. Use the dedicated "A" output.
    link(vc, "A", s2, "B")
    prop_link(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    prop_link(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    prop_link(spec, "", unreal.MaterialProperty.MP_SPECULAR)
    prop_link(s2, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def tree_instance(name, parent, scalars=(), vectors=(), textures=()):
    mi = ASSETS.create_asset(name, TREE_MATS, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    for k, v in scalars:
        MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    for k, v in vectors:
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*[float(x) for x in v], 1.0))
    for k, v in textures:
        MEL.set_material_instance_texture_parameter_value(mi, k, v)
    EAL.save_loaded_asset(mi, only_if_is_dirty=False)
    return mi


def setup_trees():
    """Materials, Nanite and trunk capsules for the procedural tree variants (writes a small report
    next to trees.json: unreal.log is not visible headless)."""
    if EAL.does_directory_exist(TREE_MATS):
        EAL.delete_directory(TREE_MATS)
    tex = tree_bark_textures()
    bark_m = bark_master(next(iter(tex.values())))
    leaf_m = leaf_master()
    bark_mi, leaf_mi, report = {}, {}, {}
    for v, spec in TREES.items():
        b, l = spec["materials"]["bark"], spec["materials"]["leaves"]
        bset = Path(b["texture"]).parent.name
        bkey = (bset, tuple(b["tint"]), b["roughness_channel"])
        if bkey not in bark_mi:
            n = sum(1 for k in bark_mi if k[0] == bset)
            bark_mi[bkey] = tree_instance(f"MI_TreeBark_{bset}" + (f"_{n + 1}" if n else ""), bark_m,
                                          scalars=[("UVScaleU", 1.0), ("UVScaleV", 1.0),
                                                   ("RoughnessFromG", 1.0 if b["roughness_channel"] == "G" else 0.0)],
                                          vectors=[("Tint", b["tint"])],
                                          textures=[("BaseColorTex", tex[bset]["D"]), ("NormalTex", tex[bset]["N"]),
                                                    ("RoughnessTex", tex[bset]["R"])])
        ss = l.get("subsurface") or {"color": [0.45, 0.6, 0.12], "strength": 0.5}
        lkey = (l["roughness"], l["specular"], tuple(ss["color"]), ss["strength"])
        if lkey not in leaf_mi:
            leaf_mi[lkey] = tree_instance(f"MI_TreeLeaves_{len(leaf_mi) + 1}", leaf_m,
                                          scalars=[("Roughness", l["roughness"]), ("Specular", l["specular"]),
                                                   ("SubsurfaceStrength", ss["strength"])],
                                          vectors=[("SubsurfaceColor", ss["color"])])
        meshes = assets_in(f"{DEST}/tree_{v}", unreal.StaticMesh)
        if not meshes:
            report[v] = "error: no mesh imported"
            continue
        mesh = meshes[0]
        slots = []
        for i, sm in enumerate(mesh.get_editor_property("static_materials")):
            slot = str(sm.get_editor_property("material_slot_name")).lower()
            leaf = "lea" in slot if slot not in ("", "none") else i == 1
            mesh.set_material(i, leaf_mi[lkey] if leaf else bark_mi[bkey])
            slots.append(f"{slot}:{'leaves' if leaf else 'bark'}")
        ns = mesh.get_editor_property("nanite_settings")
        ns.enabled = True
        set_shape_preservation(ns, TREE_SHAPE_PRESERVATION, v)
        mesh.set_editor_property("nanite_settings", ns)
        # the car hits the trunk only; capsule from the trunk radius at 1 m and the clear trunk height
        ok = unreal.CambridgeWorldTools.set_trunk_collision(mesh, spec["trunk_radius_m"] * 100.0,
                                                            spec["trunk_capsule_height_m"] * 100.0)
        EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
        report[v] = {"mesh": mesh.get_path_name(), "slots": slots, "trunk_collision": bool(ok)}
        try:
            ns = mesh.get_editor_property("nanite_settings")
            ext = mesh.get_bounds().box_extent        # expect ~ (crown r, crown r, height / 2) x 100
            report[v].update(nanite=bool(ns.enabled), shape_preservation=str(ns.get_editor_property("shape_preservation")),
                             size_cm=[round(2 * ext.x), round(2 * ext.y), round(2 * ext.z)])
        except Exception as e:
            report[v]["report_error"] = str(e)
    (ROOT / "data/processed/common/props/ue_trees_report.json").write_text(json.dumps(
        {"bark_instances": [mi.get_name() for mi in bark_mi.values()],
         "leaf_instances": [mi.get_name() for mi in leaf_mi.values()], "variants": report}, indent=2))


main()
