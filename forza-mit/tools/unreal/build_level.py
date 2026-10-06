"""Assemble the playable level for a region from imported meshes (run after import_region.sh).

  tools/unreal/build_level.sh mit_core

Creates /Game/Cambridge/Maps/<Region> from the engine's default lit template, places the
region meshes at the manifest pivot, hides the boundary wall in game, and puts the
PlayerStart at the manifest spawn. Materials come from build_materials.sh (assigned on the meshes).

Phases (build_level.sh runs them in order, each in its own editor process):
  build      assemble the plain (non World Partition) level and save it
  (the engine's WorldPartitionConvertCommandlet then converts it in place)
  streaming  set the World Partition grid (STREAM_CELL_CM / STREAM_RANGE_CM) and save

World Partition: region tiles, props and the boundary stream by cell; the ctx_ backdrop ring,
lighting, post-process and PlayerStart are always loaded (is_spatially_loaded = False).
"""
import json
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE, REGION = sys.argv[-2], sys.argv[-1]
SRC = ROOT / "data/processed" / REGION / "meshes"
MESHES = f"/Game/Cambridge/{REGION}/Meshes"
MATS = "/Game/Cambridge/Materials/Placeholder"
MAP = f"/Game/Cambridge/Maps/{REGION}"
GAME_MODE = "/Script/CambridgeRacer.CambridgeGameMode"

COLORS = {"boundary": (1.0, 0.0, 1.0)}  # editor-only placeholder for the invisible wall

actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assets = unreal.AssetToolsHelpers.get_asset_tools()


def placeholder_material(name, rgb):
    path = f"{MATS}/MI_{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mi = unreal.load_asset(path)
    else:
        mi = assets.create_asset(f"MI_{name}", MATS, unreal.MaterialInstanceConstant,
                                 unreal.MaterialInstanceConstantFactoryNew())
    mi.set_editor_property("parent", unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial"))
    unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
        mi, "Color", unreal.LinearColor(*rgb, 1.0))
    unreal.EditorAssetLibrary.save_loaded_asset(mi, only_if_is_dirty=False)
    return mi


STREAM_CELL_CM = 25600     # = the mesh tile size, so one tile maps onto one cell
STREAM_RANGE_CM = 76800    # ~3 cells around the camera; MIT core (~1 km) stays mostly resident
PROP_TILE_CM = 25600       # props are batched per (mesh, tile) so they still stream by cell
PROP_CULL_CM = {"jacaranda_tree": 40000, "lamp_post": 25000, "street_lamp_02": 20000, "cobra_pole": 30000,
                "fire_hydrant": 15000, "metal_trash_can": 15000, "painted_wooden_bench": 15000, "bike_rack": 12000,
                "parking_meter": 12000, "signal_pole": 30000, "signal_lens": 30000, "signal_lens_m": 30000, "utility_pole": 30000,
                "bus_shelter": 20000, "bus_shelter_glass": 20000}
PROP_PARTS = {"tree": [("jacaranda_tree", 0.0)], "lamp": [("lamp_post", 0.0), ("street_lamp_02", 360.0)],
              "cobra": [("cobra_pole", 0.0)], "hydrant": [("fire_hydrant", 0.0)], "litter": [("metal_trash_can", 0.0)],
              "bench": [("painted_wooden_bench", 0.0)], "bikerack": [("bike_rack", 0.0)], "meter": [("parking_meter", 0.0)],
              "signal": [("signal_pole", 0.0), ("signal_lens", 0.0)], "signal_m": [("signal_pole", 0.0), ("signal_lens_m", 0.0)],
              "upole": [("utility_pole", 0.0)],
              "shelter": [("bus_shelter", 0.0), ("bus_shelter_glass", 0.0)]}
# procedural street trees (props.py type "tree_<variant>" -> mesh Props/tree_<variant>); like the old
# jacaranda ("tree", kept for old props.json files). The game re-applies the player's tree draw
# distance at BeginPlay (UCambridgeGameUserSettings::ApplyTreeDistance: mesh name contains "tree")
TREE_VARIANTS = json.loads((ROOT / "data/processed/common/props/trees/trees.json").read_text())["variants"]
PROP_CULL_CM.update({f"tree_{v}": 40000 for v in TREE_VARIANTS})
PROP_PARTS.update({f"tree_{v}": [(f"tree_{v}", 0.0)] for v in TREE_VARIANTS})

PROPS = "/Game/Cambridge/Props"
EXPOSURE_EV = 0.9   # manual exposure compensation (EV); tuned against the shot tour
SUN = {"pitch": -30.0, "yaw": -40.0, "temperature": 5400.0}   # mid-afternoon sun from the south-west
SKY_INTENSITY = 1.5
# colour grade: a touch warmer and more saturated, brighter bounce light so shade isn't grey,
# slightly cooler shadows against warm highlights (keeps depth)
GRADE = {"white_temp": 6900.0, "color_saturation": unreal.Vector4(1.08, 1.08, 1.08, 1.0),
         "color_contrast": unreal.Vector4(1.05, 1.05, 1.05, 1.0),
         "color_gain_shadows": unreal.Vector4(0.97, 0.99, 1.04, 1.0),
         "color_gain_highlights": unreal.Vector4(1.03, 1.0, 0.96, 1.0),
         "indirect_lighting_intensity": 1.3}


def prop_mesh(name):
    for p in unreal.EditorAssetLibrary.list_assets(f"{PROPS}/{name}", recursive=True):
        a = unreal.load_asset(p)
        if isinstance(a, unreal.StaticMesh):
            return a
    return None


def always_loaded(actor):
    """Keep an actor resident regardless of World Partition streaming (backdrop, lighting...)."""
    try:
        actor.set_editor_property("is_spatially_loaded", False)
    except Exception as e:
        unreal.log_warning(f"is_spatially_loaded on {actor.get_actor_label()}: {e}")


def place_props():
    """Trees and street lights from data/processed/<region>/props/props.json (tools/mapgen/props.py),
    as one APropInstancesActor (instanced static meshes, culled by distance) per prop mesh and tile."""
    path = ROOT / "data/processed" / REGION / "props/props.json"
    if not path.exists():
        return {}
    meshes = {k: prop_mesh(k) for k in PROP_CULL_CM}
    parts = PROP_PARTS
    batches = {}
    for p in json.loads(path.read_text()):
        s = p["scale"]
        scale = unreal.Vector(p.get("sx", s), p.get("sy", s), p.get("sz", s))
        for mesh_name, dz in parts.get(p["type"], []):
            if meshes.get(mesh_name) is None:
                continue
            key = (mesh_name, int(p["x"] // PROP_TILE_CM), int(p["y"] // PROP_TILE_CM))
            batches.setdefault(key, []).append(unreal.Transform(
                location=unreal.Vector(p["x"], p["y"], p["z"] + dz),
                rotation=unreal.Rotator(roll=0.0, pitch=0.0, yaw=p["yaw"]),
                scale=scale))
    counts = {}
    for (mesh_name, i, j), xforms in sorted(batches.items()):
        centre = unreal.Vector((i + 0.5) * PROP_TILE_CM, (j + 0.5) * PROP_TILE_CM, 0.0)
        a = actors.spawn_actor_from_class(unreal.PropInstancesActor, centre)
        ism = a.get_editor_property("instances")
        ism.set_static_mesh(meshes[mesh_name])
        ism.add_instances(xforms, False, True)
        ism.set_cull_distances(int(PROP_CULL_CM[mesh_name] * 0.8), PROP_CULL_CM[mesh_name])
        a.set_actor_label(f"props_{mesh_name}__{i}_{j}")
        a.set_folder_path(f"Cambridge/{REGION}/props/{mesh_name}")
        counts[mesh_name] = counts.get(mesh_name, 0) + len(xforms)
    return {"instances": counts, "batches": len(batches)}


def setup_lighting():
    """Late-afternoon sun from the south-west, light haze, tuned exposure and post."""
    for a in actors.get_all_level_actors():
        if isinstance(a, unreal.DirectionalLight):
            a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=SUN["pitch"], yaw=SUN["yaw"]), False)
            c = a.get_component_by_class(unreal.DirectionalLightComponent)
            c.set_editor_property("use_temperature", True)
            c.set_editor_property("temperature", SUN["temperature"])
        elif isinstance(a, unreal.SkyLight):
            a.get_component_by_class(unreal.SkyLightComponent).set_editor_property("intensity", SKY_INTENSITY)
        elif isinstance(a, unreal.ExponentialHeightFog):
            c = a.get_component_by_class(unreal.ExponentialHeightFogComponent)
            c.set_editor_property("fog_density", 0.006)
            c.set_editor_property("fog_height_falloff", 0.12)
    ppv = actors.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
    ppv.set_actor_label("PostProcess_Global")
    ppv.set_editor_property("unbound", True)
    s = ppv.get_editor_property("settings")
    # fixed time of day -> manual exposure (deterministic look, no adaptation "breathing")
    s.set_editor_property("override_auto_exposure_method", True)
    s.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
    s.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
    s.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
    for k, v in {"auto_exposure_bias": EXPOSURE_EV,
                 "bloom_intensity": 0.45, "vignette_intensity": 0.3, "ambient_occlusion_intensity": 0.85,
                 "motion_blur_amount": 0.25, "lumen_final_gather_quality": 2.0, "lumen_reflection_quality": 1.0,
                 "film_grain_intensity": 0.0, **GRADE}.items():
        try:
            s.set_editor_property(f"override_{k}", True)
            s.set_editor_property(k, v)
        except Exception as e:
            unreal.log_warning(f"post setting {k}: {e}")
    ppv.set_editor_property("settings", s)
    for a in actors.get_all_level_actors():
        if isinstance(a, (unreal.Light, unreal.SkyLight, unreal.ExponentialHeightFog, unreal.SkyAtmosphere,
                          unreal.VolumetricCloud, unreal.PostProcessVolume)):
            always_loaded(a)


def build():
    manifest = json.loads((SRC / "manifest.json").read_text())
    px, py, pz = manifest["pivot_ue_cm"]

    # build_level.sh deletes the previous map before the editor starts
    # (EditorAssetLibrary.duplicate_asset / new_map_from_template don't give a spawnable world in a commandlet)
    assert level_editor.new_level_from_template(MAP, "/Engine/Maps/Templates/Template_Default")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    # drop the template's floor and player start; keep its sky, sun, fog and post-process
    for a in actors.get_all_level_actors():
        if isinstance(a, (unreal.StaticMeshActor, unreal.PlayerStart)):
            actors.destroy_actor(a)

    for path in sorted(unreal.EditorAssetLibrary.list_assets(MESHES, recursive=True)):
        mesh = unreal.load_asset(path)
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        name = mesh.get_name()
        cls = name.split("__")[0]
        # spawn_actor_from_object returns None in a commandlet; spawn_actor_from_class works
        a = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(px, py, pz))
        a.set_actor_label(f"{REGION}_{name}")
        a.set_folder_path(f"Cambridge/{REGION}/{cls}")
        smc = a.get_editor_property("static_mesh_component")
        smc.set_static_mesh(mesh)
        smc.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        if cls.startswith("ctx_"):
            always_loaded(a)   # skyline stays visible from anywhere (HLODs would replace this later)
            smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            smc.set_editor_property("generate_overlap_events", False)
        if cls == "boundary":
            smc.set_material(0, placeholder_material("boundary", COLORS["boundary"]))
            a.set_actor_hidden_in_game(True)
            smc.set_editor_property("cast_shadow", False)
            smc.set_editor_property("affect_distance_field_lighting", False)

    prop_stats = place_props()
    setup_lighting()

    sx, sy, sz = manifest["spawn"]["ue_cm"]
    ps = actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(sx, sy, sz + 100.0),
                                       unreal.Rotator(roll=0.0, pitch=0.0, yaw=manifest["spawn"]["ue_yaw_deg"]))
    ps.set_actor_label("PlayerStart_MassAve")
    always_loaded(ps)

    ws = world.get_world_settings()
    ws.set_editor_property("default_game_mode", unreal.load_class(None, GAME_MODE))

    assert level_editor.save_current_level()
    labels = {}
    for a in actors.get_all_level_actors():
        k = a.get_actor_label().split("__")[0]
        labels[k] = labels.get(k, 0) + 1
    (SRC / "ue_level_report.json").write_text(json.dumps(
        {"map": MAP, "actors": len(actors.get_all_level_actors()), "props": prop_stats, "by_label": labels}, indent=2))


def streaming():
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    desc = unreal.CambridgeWorldTools.configure_streaming(world, STREAM_CELL_CM, STREAM_RANGE_CM)
    assert not desc.startswith("error"), desc
    assert unreal.EditorLoadingAndSavingUtils.save_map(world, MAP)
    report = SRC / "ue_level_report.json"
    r = json.loads(report.read_text())
    r["world_partition"] = unreal.CambridgeWorldTools.describe_streaming(world)
    report.write_text(json.dumps(r, indent=2))


{"build": build, "streaming": streaming}[PHASE]()
