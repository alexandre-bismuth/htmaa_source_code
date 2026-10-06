"""Import a region's generated .glb mesh tiles into the Unreal project as StaticMesh assets.

Run via tools/unreal/import_region.sh <region>, which calls this once per phase:
  phase "import": wipe the region's mesh folder, Interchange-import every .glb
  phase "post":   per mesh: Nanite off, full-precision UVs, collision by class
  phase "verify": write report (fresh run, since render data is only rebuilt on reload)
Separate editor runs, because Interchange finishes asynchronously and would
overwrite post-import edits made in the same run.
"""
import json
import sys
from pathlib import Path

import unreal

ROOT = Path(__file__).resolve().parents[2]
PHASE, REGION = sys.argv[-2], sys.argv[-1]
SRC = ROOT / "data/processed" / REGION / "meshes"
DEST = f"/Game/Cambridge/{REGION}/Meshes"

# mesh classes without collision: water (walled off), road paint, and the whole ctx_ backdrop ring
NO_COLLISION = {"water", "markings_white", "markings_yellow"}   # paint is 6 mm above the road


def collides(cls):
    return cls not in NO_COLLISION and not cls.startswith("ctx_")


def mesh_class(name):
    return name.split("__")[0]


def mesh_assets():
    out = []
    for path in unreal.EditorAssetLibrary.list_assets(DEST, recursive=True):
        a = unreal.load_asset(path)
        if isinstance(a, unreal.StaticMesh):
            out.append(a)
    return out


def main():
    if PHASE == "import":
        if unreal.EditorAssetLibrary.does_directory_exist(DEST):
            unreal.EditorAssetLibrary.delete_directory(DEST)
        tasks = []
        # skip iCloud conflict copies ("name 2.glb"): the repo lives in an iCloud-synced folder
        for glb in sorted(g for g in SRC.glob("*.glb") if " " not in g.name):
            t = unreal.AssetImportTask()
            t.filename = str(glb)
            t.destination_path = f"{DEST}/{glb.stem}"
            t.destination_name = glb.stem
            t.automated = True
            t.replace_existing = True
            t.save = True
            tasks.append(t)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
        return

    meshes = mesh_assets()
    if PHASE == "post":
        for m in meshes:
            # Nanite for rendering (virtual shadow maps are much cheaper with Nanite), but with a
            # full-detail fallback mesh: complex collision uses the fallback, so curbs stay exact
            ns = m.get_editor_property("nanite_settings")
            ns.enabled = True
            ns.set_editor_property("fallback_target", unreal.NaniteFallbackTarget.RELATIVE_ERROR)
            ns.set_editor_property("fallback_relative_error", 0.0)
            ns.set_editor_property("keep_percent_triangles", 1.0)
            m.set_editor_property("nanite_settings", ns)
            # UVs are metres (up to ~2 km): 16-bit UVs would make textures swim
            bs = unreal.EditorStaticMeshLibrary.get_lod_build_settings(m, 0)
            bs.set_editor_property("use_full_precision_u_vs", True)
            bs.set_editor_property("recompute_normals", False)
            bs.set_editor_property("recompute_tangents", True)
            unreal.EditorStaticMeshLibrary.set_lod_build_settings(m, 0, bs)
            body = m.get_editor_property("body_setup")
            if body:
                body.set_editor_property(
                    "collision_trace_flag",
                    unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE if collides(mesh_class(m.get_name()))
                    else unreal.CollisionTraceFlag.CTF_USE_SIMPLE_AS_COMPLEX)
            unreal.EditorAssetLibrary.save_loaded_asset(m, only_if_is_dirty=False)
        return

    manifest = json.loads((SRC / "manifest.json").read_text())
    by_class = {}
    for m in meshes:
        c = mesh_class(m.get_name())
        e = by_class.setdefault(c, {"meshes": 0, "tris": 0, "nanite_on": 0, "full_precision_uvs": 0})
        # (tris = fallback mesh triangles; with relative error 0 it equals the source)
        e["meshes"] += 1
        e["tris"] += m.get_num_triangles(0)
        e["nanite_on"] += int(m.get_editor_property("nanite_settings").enabled)
        bs = unreal.EditorStaticMeshLibrary.get_lod_build_settings(m, 0)
        e["full_precision_uvs"] += int(bs.get_editor_property("use_full_precision_u_vs"))
    for c, e in by_class.items():
        e["generated_tris"] = manifest["triangles"].get(c)
    out = SRC / "ue_import_report.json"
    out.write_text(json.dumps({"pivot_ue_cm": manifest["pivot_ue_cm"], "classes": by_class}, indent=2))


main()
