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
# parked cars (tools/blender/parked_cars.py): one mesh per body type, slots parked_paint / parked_glass / parked_detail,
# COLOR_0 = baked AO (paint, glass) or albedo + surface class (detail). See setup_parked(). Street life agent.
PARKED_JSON = ROOT / "data/processed/common/props/parked_cars.json"
PARKED = json.loads(PARKED_JSON.read_text())["types"] if PARKED_JSON.exists() else {}
SOURCES.update({f"parked_{t}": ROOT / spec["file"] for t, spec in PARKED.items()})
PARKED_MATS = f"{DEST}/Materials/Parked"
TREE_BARK = f"{DEST}/TreeBark"
TREE_MATS = f"{DEST}/Materials/Trees"
# Nanite distance behaviour of the canopies: "PRESERVE_AREA" (the task's choice; the 5.8 header calls
# it the legacy foliage technique) or "VOXELIZE" (5.8: distant leaves become voxels) to A/B
TREE_SHAPE_PRESERVATION = "PRESERVE_AREA"
# Nanite "Lerp UVs" on the tree meshes: the leaves' UV0 is not a texture mapping (x = autumn rank per leaf), so its
# interpolation error should not hold back the simplification; bark UVs only matter up close
TREE_LERP_UVS = True
# Nanite data kept resident per tree mesh (KB; 0 = engine minimum, one root page). While a canopy's finer pages stream
# in, the root page's coarse LOD can be what the (cached, static) virtual shadow map captures
TREE_MIN_RESIDENCY_KB = 0


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
    if PHASE in ("parked_import", "parked_post"):     # parked cars only (no tree / furniture re-import)
        return parked_only(PHASE)
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
    setup_parked()


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


LEAF_HLSL = """
// per-tree variation + late-October colour (import_props.leaf_master). Rnd = PerInstanceRandom (one per tree),
// Rank = UV0.x (tree_gen.autumn_rank: the order in which the leaves turn, 0 first).
float r2 = frac(Rnd * 7.31 + 0.17);
float3 base = VC * Tint * lerp(float3(1.05, 1.03, 0.92), float3(0.95, 0.97, 1.05), r2);
float amount = AutumnMax * Rnd * Rnd;                 // most trees barely turned, a few well on
float w = saturate((amount - Rank.x) * 12.0);
float lum = dot(VC, float3(0.2126, 0.7152, 0.0722)) / max(MeanLum, 1e-3);
float3 aut = lerp(AutumnA, AutumnB, frac(Rank.x * 13.7)) * lum;
Sub = lerp(SSC, aut * 1.3, w) * SSS * VA;
return lerp(base, aut, w);
"""


def leaf_master():
    """Opaque two-sided foliage leaves (real leaf geometry, no alpha): BaseColor = vertex colour RGB (final albedo
    incl. baked occlusion) x Tint x a subtle per-tree tint (PerInstanceRandom), with a per-tree random share of the
    leaves (UV0.x rank < AutumnMax x random^2) turned to the species' autumn colours (AutumnA/B, scaled by the
    vertex colour's luminance / MeanLum so the baked occlusion stays); transmission = SubsurfaceColor (or the
    autumn colour) x Strength x vertex alpha (occlusion: inner leaves glow less); constant roughness / specular."""
    m = tree_material("M_TreeLeaves_Opaque")
    m.set_editor_property("two_sided", True)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -900, 0)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -900, 100)
    rnd = MEL.create_material_expression(m, unreal.MaterialExpressionPerInstanceRandom, -900, 180)
    V = lambda name, val, y: param(m, unreal.MaterialExpressionVectorParameter, name, -900, y,
                                   default_value=unreal.LinearColor(*val, 1.0))
    S = lambda name, val, y: param(m, unreal.MaterialExpressionScalarParameter, name, -900, y, default_value=val)
    # (VertexColor's "" output is RGB only: alpha comes in through its "A" output)
    ins = [("VC", vc, ""), ("VA", vc, "A"), ("Rank", uv, ""), ("Rnd", rnd, ""), ("Tint", V("Tint", (1.0, 1.0, 1.0), 260), "RGB"),
           ("AutumnA", V("AutumnA", (0.45, 0.3, 0.05), 340), "RGB"), ("AutumnB", V("AutumnB", (0.35, 0.25, 0.05), 420), "RGB"),
           ("AutumnMax", S("AutumnMax", 0.0, 500), ""), ("MeanLum", S("MeanLum", 0.05, 560), ""),
           ("SSC", V("SubsurfaceColor", (0.45, 0.6, 0.12), 620), "RGB"), ("SSS", S("SubsurfaceStrength", 0.5, 700), "")]
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, -400, 0)
    pins = []
    for n, _, _ in ins:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        pins.append(ci)
    c.set_editor_property("inputs", pins)
    co = unreal.CustomOutput()
    co.set_editor_property("output_name", "Sub")
    co.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    c.set_editor_property("additional_outputs", [co])
    c.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    c.set_editor_property("description", "tree leaves")
    c.set_editor_property("code", LEAF_HLSL)
    for n, e, pin in ins:
        link(e, pin, c, n)
    rough = param(m, unreal.MaterialExpressionScalarParameter, "Roughness", -500, 800, default_value=0.55)
    spec = param(m, unreal.MaterialExpressionScalarParameter, "Specular", -500, 880, default_value=0.35)
    prop_link(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    prop_link(c, "Sub", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
    prop_link(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    prop_link(spec, "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def srgb_lin(c):
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


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
        au = l.get("autumn") or {"max": 0.0, "colors_srgb": [[0.5, 0.4, 0.1]] * 2, "mean_luminance": 0.05}
        lkey = (l["roughness"], l["specular"], tuple(ss["color"]), ss["strength"], au["max"],
                tuple(map(tuple, au["colors_srgb"])), au["mean_luminance"])
        if lkey not in leaf_mi:
            leaf_mi[lkey] = tree_instance(f"MI_TreeLeaves_{len(leaf_mi) + 1}", leaf_m,
                                          scalars=[("Roughness", l["roughness"]), ("Specular", l["specular"]),
                                                   ("SubsurfaceStrength", ss["strength"]), ("AutumnMax", au["max"]),
                                                   ("MeanLum", au["mean_luminance"])],
                                          vectors=[("SubsurfaceColor", ss["color"]),
                                                   ("AutumnA", srgb_lin(au["colors_srgb"][0])),
                                                   ("AutumnB", srgb_lin(au["colors_srgb"][-1]))])
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
        try:
            ns.set_editor_property("lerp_u_vs", TREE_LERP_UVS)
        except Exception as e:
            unreal.log_warning(f"{v}: nanite lerp_u_vs: {e}")
        try:
            ns.set_editor_property("target_minimum_residency_in_kb", int(TREE_MIN_RESIDENCY_KB))
        except Exception as e:
            unreal.log_warning(f"{v}: nanite target_minimum_residency_in_kb: {e}")
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
                             lerp_uvs=bool(ns.get_editor_property("lerp_u_vs")),
                             min_residency_kb=int(ns.get_editor_property("target_minimum_residency_in_kb")),
                             size_cm=[round(2 * ext.x), round(2 * ext.y), round(2 * ext.z)])
        except Exception as e:
            report[v]["report_error"] = str(e)
    (ROOT / "data/processed/common/props/ue_trees_report.json").write_text(json.dumps(
        {"bark_instances": [mi.get_name() for mi in bark_mi.values()],
         "leaf_instances": [mi.get_name() for mi in leaf_mi.values()], "variants": report}, indent=2))


# ------------------------------------------------------------------ parked cars (street life)
# Paint colour per instance from PerInstanceRandom (place_props adds no custom data): a weighted Cambridge palette
# (white / black / greys / silver dominate, some blue / red, a few greens / beiges / browns), metallic or solid per
# colour, clear coat with a little per-car roughness (dirt). WhiteBias (per body type, parked_cars.json white_bias)
# adds white fleet vehicles (pickups, vans). COLOR_0.r = baked AO (direct light x (0.45 + 0.55 AO), indirect x AO).
PARKED_PAINT_HLSL = """
float r = frac(Rnd);
float r2 = frac(Rnd * 13.731 + 0.377);
float r3 = frac(Rnd * 41.17 + 0.71);
float u = r < WB ? 0.0 : (r - WB) / max(1.0 - WB, 0.001);
float3 C[13] = { float3(0.78, 0.78, 0.76), float3(0.70, 0.70, 0.68), float3(0.012, 0.012, 0.013), float3(0.07, 0.075, 0.08),
                 float3(0.18, 0.19, 0.20), float3(0.45, 0.46, 0.47), float3(0.02, 0.05, 0.16), float3(0.05, 0.13, 0.36),
                 float3(0.36, 0.02, 0.02), float3(0.12, 0.012, 0.015), float3(0.03, 0.07, 0.04), float3(0.35, 0.30, 0.22),
                 float3(0.10, 0.06, 0.035) };
float Mt[13] = { 0.0, 0.35, 0.3, 0.7, 0.7, 0.85, 0.6, 0.6, 0.25, 0.6, 0.5, 0.7, 0.5 };
float W[13] = { 18, 6, 21, 9, 8, 13, 6, 4, 7, 2, 2, 2, 2 };
int k = 0;
float acc = 0.0;
for (int i = 0; i < 12; i++) { acc += W[i] * 0.01; k += (u >= acc) ? 1 : 0; }
Metal = Mt[k];
Rough = 0.30 + 0.14 * r3;
CCR = 0.03 + 0.10 * r3 * r3;
return C[k] * (0.92 + 0.16 * r2);
"""
PARKED_DETAIL_HLSL = """
int i = (int)round(saturate(A) * 5.0);
float R[6] = { 0.85, 0.5, 0.6, 0.22, 0.06, 0.4 };
float M[6] = { 0.0, 0.0, 0.3, 1.0, 0.0, 0.0 };
float S[6] = { 0.3, 0.45, 0.5, 0.5, 0.6, 0.5 };
Metal = M[i];
Spec = S[i];
return R[i];
"""


def parked_material(name, shading=None, attributes=False):
    m = ASSETS.create_asset(name, PARKED_MATS, unreal.Material, unreal.MaterialFactoryNew())
    for flag in ("used_with_nanite", "used_with_instanced_static_meshes"):
        m.set_editor_property(flag, True)
    if shading is not None:
        m.set_editor_property("shading_model", shading)
    if attributes:
        m.set_editor_property("use_material_attributes", True)
    return m


def custom_node(m, code, ins, outs, main_type, x, y, desc):
    F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
    c = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, x, y)
    pins = []
    for n, _, _ in ins:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        pins.append(ci)
    c.set_editor_property("inputs", pins)
    ao = []
    for n in outs:
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", F1)
        ao.append(co)
    c.set_editor_property("additional_outputs", ao)
    c.set_editor_property("output_type", F3 if main_type == 3 else F1)
    c.set_editor_property("description", desc)
    c.set_editor_property("code", code)
    for n, e, pin in ins:
        link(e, pin, c, n)
    return c


def parked_paint_master():
    m = parked_material("M_ParkedPaint", unreal.MaterialShadingModel.MSM_CLEAR_COAT, attributes=True)
    mma = MEL.create_material_expression(m, unreal.MaterialExpressionMakeMaterialAttributes, -200, 0)
    prop_link(mma, "", unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    rnd = MEL.create_material_expression(m, unreal.MaterialExpressionPerInstanceRandom, -900, 0)
    wb = param(m, unreal.MaterialExpressionScalarParameter, "WhiteBias", -900, 100, default_value=0.0)
    c = custom_node(m, PARKED_PAINT_HLSL, [("Rnd", rnd, ""), ("WB", wb, "")], ["Metal", "Rough", "CCR"], 3, -650, 0,
                    "parked car palette")
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -900, 300)
    shade = MEL.create_material_expression(m, unreal.MaterialExpressionLinearInterpolate, -650, 300)
    shade.set_editor_property("const_a", 0.45)
    shade.set_editor_property("const_b", 1.0)
    link(vc, "R", shade, "Alpha")
    base = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -420, 100)
    link(c, "return", base, "A")
    link(shade, "", base, "B")
    one = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -420, 400)
    one.set_editor_property("r", 1.0)
    link(base, "", mma, "BaseColor")
    link(c, "Metal", mma, "Metallic")
    link(c, "Rough", mma, "Roughness")
    link(one, "", mma, "ClearCoat")
    link(c, "CCR", mma, "ClearCoatRoughness")
    link(vc, "R", mma, "AmbientOcclusion")
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def parked_glass():
    """Opaque dark glass (Nanite draws no translucency): near-black tint, glossy, AO from COLOR_0."""
    m = parked_material("M_ParkedGlass")
    k = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -600, 0)
    k.set_editor_property("constant", unreal.LinearColor(0.012, 0.014, 0.016, 1.0))
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -600, 150)
    mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, 0)
    link(k, "", mul, "A")
    link(vc, "R", mul, "B")
    prop_link(mul, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for prop, v, y in ((unreal.MaterialProperty.MP_ROUGHNESS, 0.05, 250), (unreal.MaterialProperty.MP_SPECULAR, 0.55, 330),
                       (unreal.MaterialProperty.MP_METALLIC, 0.0, 410)):
        e = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -350, y)
        e.set_editor_property("r", v)
        prop_link(e, "", prop)
    prop_link(vc, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def parked_detail():
    """Trim / tyres / rims / lamps / plates: BaseColor = COLOR_0.rgb (AO baked in), surface class in COLOR_0.a."""
    m = parked_material("M_ParkedDetail")
    vc = MEL.create_material_expression(m, unreal.MaterialExpressionVertexColor, -800, 0)
    c = custom_node(m, PARKED_DETAIL_HLSL, [("A", vc, "A")], ["Metal", "Spec"], 1, -500, 200, "parked car surface class")
    prop_link(vc, "", unreal.MaterialProperty.MP_BASE_COLOR)
    prop_link(c, "return", unreal.MaterialProperty.MP_ROUGHNESS)
    prop_link(c, "Metal", unreal.MaterialProperty.MP_METALLIC)
    prop_link(c, "Spec", unreal.MaterialProperty.MP_SPECULAR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def parked_box_collision(mesh, spec):
    """One simple box (parked_cars.json collision, cm, mesh space), used as complex too. -> report dict."""
    out = {}
    bs = mesh.get_editor_property("body_setup")
    if bs is None:
        return {"error": "no body setup"}
    agg = bs.get_editor_property("agg_geom")
    out["before"] = {k: len(agg.get_editor_property(k)) for k in ("box_elems", "convex_elems", "sphyl_elems", "sphere_elems")}
    col = spec["collision"]
    box = unreal.KBoxElem()
    box.set_editor_property("center", unreal.Vector(*col["centre_cm"]))
    for k, v in zip(("x", "y", "z"), col["size_cm"]):
        box.set_editor_property(k, float(v))
    agg.set_editor_property("box_elems", [box])
    for k in ("convex_elems", "sphyl_elems", "sphere_elems"):
        agg.set_editor_property(k, [])
    bs.set_editor_property("agg_geom", agg)
    bs.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_SIMPLE_AS_COMPLEX)
    mesh.set_editor_property("body_setup", bs)
    agg2 = mesh.get_editor_property("body_setup").get_editor_property("agg_geom")
    out["after"] = {k: len(agg2.get_editor_property(k)) for k in ("box_elems", "convex_elems")}
    b = agg2.get_editor_property("box_elems")
    if b:
        out["box"] = [round(b[0].get_editor_property(k), 1) for k in ("x", "y", "z")]
    return out


def setup_parked():
    """Materials (palette paint master + per-type instance, glass, detail), Nanite, box collision for the parked cars.
    Writes data/processed/common/props/ue_parked_report.json."""
    if not PARKED:
        return
    if EAL.does_directory_exist(PARKED_MATS):
        EAL.delete_directory(PARKED_MATS)
    paint_m, glass_m, det_m = parked_paint_master(), parked_glass(), parked_detail()
    report = {}
    for t, spec in PARKED.items():
        meshes = assets_in(f"{DEST}/parked_{t}", unreal.StaticMesh)
        if not meshes:
            report[t] = "error: no mesh imported"
            continue
        mesh = meshes[0]
        mi = ASSETS.create_asset(f"MI_ParkedPaint_{t}", PARKED_MATS, unreal.MaterialInstanceConstant,
                                 unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, paint_m)
        MEL.set_material_instance_scalar_parameter_value(mi, "WhiteBias", float(spec.get("white_bias", 0.0)))
        EAL.save_loaded_asset(mi, only_if_is_dirty=False)
        slots = []
        for i, sm in enumerate(mesh.get_editor_property("static_materials")):
            slot = str(sm.get_editor_property("material_slot_name")).lower()
            mat = mi if "paint" in slot else glass_m if "glass" in slot else det_m
            mesh.set_material(i, mat)
            slots.append(f"{slot}:{mat.get_name()}")
        ns = mesh.get_editor_property("nanite_settings")
        ns.enabled = True
        mesh.set_editor_property("nanite_settings", ns)
        try:
            col = parked_box_collision(mesh, spec)
        except Exception as e:
            col = {"error": str(e)}
        EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
        ext = mesh.get_bounds().box_extent
        report[t] = {"mesh": mesh.get_path_name(), "slots": slots, "collision": col,
                     "nanite": bool(mesh.get_editor_property("nanite_settings").enabled),
                     "size_cm": [round(2 * ext.x), round(2 * ext.y), round(2 * ext.z)]}
    (ROOT / "data/processed/common/props/ue_parked_report.json").write_text(json.dumps(report, indent=2))


def parked_only(phase):
    if phase == "parked_import":
        tasks = []
        for t, spec in PARKED.items():
            name = f"parked_{t}"
            if EAL.does_directory_exist(f"{DEST}/{name}"):
                EAL.delete_directory(f"{DEST}/{name}")
            k = unreal.AssetImportTask()
            k.filename = str(ROOT / spec["file"])
            k.destination_path = f"{DEST}/{name}"
            k.destination_name = name
            k.automated = True
            k.replace_existing = True
            k.save = True
            tasks.append(k)
        ASSETS.import_asset_tasks(tasks)
    else:
        setup_parked()


main()
