"""Merge a multi-node glTF (e.g. Poly Haven props with separate caps / lids) into one object and
export a single-mesh .glb (materials and textures kept), so the Unreal import yields one static mesh.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/merge_model.py -- in.gltf out.glb
"""
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
src, dst = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in bpy.context.scene.objects:
    o.select_set(o in meshes)
bpy.context.view_layer.objects.active = meshes[0]
# bake the node hierarchy into the vertices, then join
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if len(meshes) > 1:
    bpy.ops.object.join()
merged = bpy.context.view_layer.objects.active
merged.name = merged.data.name = bpy.path.display_name_from_filepath(dst)
for o in list(bpy.context.scene.objects):
    if o is not merged:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=False, export_apply=True)
print(f"merged {len(meshes)} meshes -> {dst}")
