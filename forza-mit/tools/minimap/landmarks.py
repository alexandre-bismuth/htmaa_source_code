"""Landmarks (GTA-style points of interest) for forza-MIT: where each one is, in the game frame.

Usage (reuses the tools/mapgen uv environment, like make_map.py):

    cd tools/mapgen && uv run ../minimap/landmarks.py [region]        # default region: mit_core

Writes CambridgeRacer/Tracks/<region>_landmarks.json (committed; the game reads it at runtime:
ULandmarkSubsystem spawns the floating signs, the minimap / full map draw the tags). The sign and map-icon
art is drawn by tools/ui/make_landmark_signs.py and tools/minimap/make_map.py --icons-only.

How a landmark is placed (nothing is guessed from street geometry):
  1. Its address point from the City of Cambridge Address Points layer (cambridgegis_data
     Address/Address_Points, public domain): lon/lat and the city BldgID it belongs to. The points are copied
     below so the build needs no network.
  2. The City 3D model with that Building_ID (data/raw/camb3d, the same models the game renders): footprint =
     union of its projected triangles, local roof = highest vertex within ROOF_RADIUS_M of the entrance.
  3. Entrance = the footprint boundary point nearest the address point; "facing" = the outward direction
     from the building towards the street there. The sign's arrow tip floats OUT_M in front of it.
  4. Viewpoints for tests (cr.Landmark.GoTo <id> <metres>): points on the road graph (Tracks/<region>_roads.json)
     about 50 / 150 / 300 m away, heading roughly towards the landmark.

Coordinates: local East/North metres (tools/mapgen/geo.py Frame) -> UE cm X = e * 100, Y = -n * 100, Z up
(ground at z = 0: the world is flat in v1).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mapgen"))

from shapely.geometry import Point, Polygon, box  # noqa: E402
from shapely.ops import nearest_points, unary_union  # noqa: E402

import buildings3d  # noqa: E402
from geo import Frame, all_tiles  # noqa: E402

TRACKS = ROOT / "CambridgeRacer" / "Tracks"
TILES_3D = all_tiles()     # every City 3D tile any region uses (fetch.sh downloads them all)
ROOF_RADIUS_M = 30.0      # roof height = highest part of the model this close to the entrance
OUT_M = 4.0               # arrow tip this far in front of the facade (over the sidewalk)
VIEW_DISTANCES_M = [50, 150, 300]

# Address points: City of Cambridge ADDRESS_AddressPoints.geojson (fetched 2026-10-04).
#
# "134 Vassar St" is not a Cambridge address: the city's Vassar St points go 120 (W35 Zesiger) -> 130 (W36)
# -> 189 (New Vassar), MIT's whereis has no such number, and Nominatim / the US Census geocoder only
# interpolate along the street range. The building meant is the Metropolitan Storage Warehouse at the corner of
# Massachusetts Ave and Vassar St: city BldgID 703-1, address points "134 Massachusetts Ave" (primary) and
# "95 Vassar St", renovated (2026) as the new home of MIT's School of Architecture and Planning with its
# workshops and the Project Manus makerspace. We use its Vassar St address point (the Vassar-facing entrance).
LANDMARKS = [
    {
        "id": "arch_shop",
        "label": "ARCHITECTURE SHOP",
        "subtitle": "MET WAREHOUSE",
        "address": "134 Massachusetts Ave / 95 Vassar St",
        "building": "Metropolitan Storage Warehouse (MIT SA+P)",
        "bldg_id": "703-1",
        "lonlat": (-71.09524747013292, 42.360083765529346),       # "95 Vassar St", BldgID 703-1
        "icon": "landmark_arch",
        "accent": "#ff9a1f",     # warm amber / orange (Race.Amber family)
        # the floating sign shows only fairly close (full to 380 m, gone by 450 m; still full at the MIT Loop
        # start, ~327 m away). Landmarks without it use LandmarkActor's defaults (950 -> 1300 m).
        "fade_far_m": (380, 450),
    },
    {
        "id": "htmaa",
        "label": "HTMAA LECTURES",
        "subtitle": "MEDIA LAB E14",
        "address": "75 Amherst St",
        "building": "MIT Media Lab, Building E14",
        "bldg_id": "672-6",
        "lonlat": (-71.08750013331287, 42.3602115461785),         # "75 Amherst St", BldgID 672-6
        "icon": "landmark_htmaa",
        "accent": "#3fc8ff",     # cyan / Luna light blue
    },
]


def footprint(model) -> Polygon:
    tri = model.vertices[model.faces][:, :, :2]
    u, v = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    a = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) * 0.5
    fp = unary_union([Polygon(t) for t in tri[a > 1e-3]]).buffer(0.05).buffer(-0.05)
    return max(getattr(fp, "geoms", [fp]), key=lambda g: g.area)


def ue(e, n, z=0.0):
    return [round(float(e) * 100.0, 1), round(-float(n) * 100.0, 1), round(float(z) * 100.0, 1)]


def yaw_deg(de, dn):
    """UE yaw (degrees) of a direction given in East/North (UE X = E, Y = -N)."""
    return round(math.degrees(math.atan2(-float(dn), float(de))), 2)


def road_samples(region):
    graph = json.loads((TRACKS / f"{region}_roads.json").read_text())
    pts, tangents, streets = [], [], []
    for e in graph["edges"]:
        p = np.array(e["pts"], float) / 100.0
        p[:, 1] *= -1.0                       # UE cm -> E/N metres
        for a, b in zip(p[:-1], p[1:]):
            seg = b - a
            L = float(np.hypot(*seg))
            if L < 1e-3:
                continue
            k = max(1, int(L // 5.0))
            for i in range(k):
                pts.append(a + seg * (i / k))
                tangents.append(seg / L)
                streets.append(graph["streets"][e["s"]] if 0 <= e["s"] < len(graph["streets"]) else "")
    return np.array(pts), np.array(tangents), streets


def viewpoints(entrance, roads):
    pts, tan, streets = roads
    d = pts - entrance
    dist = np.hypot(d[:, 0], d[:, 1])
    to = -d / np.maximum(dist, 1e-6)[:, None]
    cosang = np.abs((tan * to).sum(axis=1))     # road heading towards (or away from) the landmark
    out = []
    for target in VIEW_DISTANCES_M:
        score = np.abs(dist - target) / target + 0.6 * (1.0 - cosang)
        i = int(np.argmin(score))
        # drive towards the landmark: pick the road direction that points at it
        heading = tan[i] if (tan[i] * to[i]).sum() >= 0 else -tan[i]
        out.append({"d_m": round(float(dist[i]), 1), "loc": ue(*pts[i], 0.6), "yaw": yaw_deg(*heading),
                    "street": streets[i]})
    return out


def main(region):
    frame = Frame()
    roads = road_samples(region)
    out = []
    for spec in LANDMARKS:
        e, n = (float(v) for v in frame.to_en(*spec["lonlat"]))
        area = box(e - 150, n - 150, e + 150, n + 150)
        models = [m for m in buildings3d.load(TILES_3D, area, frame) if m.building_id == spec["bldg_id"]]
        if not models:
            sys.exit(f"{spec['id']}: no 3D model with Building_ID {spec['bldg_id']} near the address point")
        fp = unary_union([footprint(m) for m in models])
        fp = max(getattr(fp, "geoms", [fp]), key=lambda g: g.area)
        verts = np.vstack([m.vertices for m in models])
        addr = Point(e, n)
        on_wall = nearest_points(fp.exterior, addr)[0]
        ent = np.array([on_wall.x, on_wall.y])
        out_dir = np.array([e, n]) - ent
        if np.hypot(*out_dir) < 0.5 or fp.contains(addr):
            c = np.array(fp.centroid.coords[0])        # address point on / inside the wall: away from the centre
            out_dir = ent - c
        out_dir /= np.hypot(*out_dir)
        near = np.hypot(verts[:, 0] - ent[0], verts[:, 1] - ent[1]) < ROOF_RADIUS_M
        roof_local = float(verts[near, 2].max()) if near.any() else float(verts[:, 2].max())
        roof_max = float(verts[:, 2].max())
        tip = ent + out_dir * OUT_M
        c = np.array(fp.centroid.coords[0])
        lm = {
            "id": spec["id"],
            "label": spec["label"],
            "subtitle": spec["subtitle"],
            "address": spec["address"],
            "building": spec["building"],
            "bldg_id": spec["bldg_id"],
            "lonlat": [round(spec["lonlat"][0], 7), round(spec["lonlat"][1], 7)],
            "icon": spec["icon"],
            "accent": spec["accent"],
            "entrance": ue(*ent),
            "anchor": ue(*tip),                       # arrow tip XY (in front of the entrance)
            "centroid": ue(*c),
            "roof_m": round(roof_local, 2),           # roof near the entrance (the sign floats above it)
            "roof_max_m": round(roof_max, 2),
            "facing_yaw": yaw_deg(*out_dir),          # building -> street at the entrance
            "footprint_m2": round(fp.area),
            "viewpoints": viewpoints(ent, roads),
        }
        if "fade_far_m" in spec:
            lm["fade_far_m"] = list(spec["fade_far_m"])   # sign fully visible to [0], faded out at [1] (m)
        out.append(lm)
        print(f"  {lm['id']:10s} {spec['building']}: entrance {lm['entrance']} roof {roof_local:.1f} m "
              f"(max {roof_max:.1f}) facing {lm['facing_yaw']} deg, footprint {lm['footprint_m2']} m2")
        for v in lm["viewpoints"]:
            print(f"             view {v['d_m']:6.1f} m on {v['street']}: {v['loc']} yaw {v['yaw']}")
    doc = {
        "region": region,
        "units": "UE cm (X east, Y south, Z up; ground at 0); roof_m in metres above the ground",
        "source": "City of Cambridge address points + 3D building models (tools/minimap/landmarks.py)",
        "landmarks": out,
    }
    path = TRACKS / f"{region}_landmarks.json"
    path.write_text(json.dumps(doc, indent=1))
    print(f"  {path.relative_to(ROOT)}: {len(out)} landmarks")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
