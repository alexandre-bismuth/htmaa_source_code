"""Minimal binary glTF (.glb) writer: one mesh, one primitive, flat arrays.

Supports POSITION, NORMAL, TEXCOORD_0..2 (trimesh only writes one UV set).
Input is right-handed ENU meters; written as glTF axes (X=E, Y=Up, Z=S), which is a proper
rotation, so triangle winding is preserved.
"""
import json
import struct

import numpy as np


def enu_to_gltf(a):
    a = np.asarray(a, np.float64)
    return np.column_stack([a[:, 0], a[:, 2], -a[:, 1]])


def write_glb(path, positions_enu, faces, normals_enu=None, uv0=None, uv1=None, material="default", uv2=None):
    pos = enu_to_gltf(positions_enu).astype(np.float32)
    idx = np.asarray(faces, np.uint32).reshape(-1)
    arrays = [("POSITION", pos, "VEC3")]
    if normals_enu is not None:
        nrm = enu_to_gltf(normals_enu).astype(np.float32)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        arrays.append(("NORMAL", nrm, "VEC3"))
    if uv0 is not None:
        arrays.append(("TEXCOORD_0", np.asarray(uv0, np.float32), "VEC2"))
    if uv1 is not None:
        arrays.append(("TEXCOORD_1", np.asarray(uv1, np.float32), "VEC2"))
    if uv2 is not None:
        arrays.append(("TEXCOORD_2", np.asarray(uv2, np.float32), "VEC2"))

    blob, views, accessors, attrs = bytearray(), [], [], {}
    for name, arr, typ in arrays:
        off = len(blob)
        blob += arr.tobytes()
        views.append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes, "target": 34962})
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": len(arr), "type": typ}
        if name == "POSITION":
            acc["min"], acc["max"] = pos.min(0).tolist(), pos.max(0).tolist()
        accessors.append(acc)
        attrs[name] = len(accessors) - 1
        while len(blob) % 4:
            blob += b"\0"
    off = len(blob)
    blob += idx.tobytes()
    views.append({"buffer": 0, "byteOffset": off, "byteLength": idx.nbytes, "target": 34963})
    accessors.append({"bufferView": len(views) - 1, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
    while len(blob) % 4:
        blob += b"\0"

    doc = {
        "asset": {"version": "2.0", "generator": "forza-MIT mapgen"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": material}],
        "materials": [{"name": material}],
        "meshes": [{"name": material, "primitives": [{"attributes": attrs, "indices": len(accessors) - 1, "material": 0}]}],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return len(idx) // 3
