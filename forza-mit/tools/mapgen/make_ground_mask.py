"""Distance-field mask for ground weathering in the ground shader (tools/unreal/shaders/ground.hlsl).

Usage:  uv run make_ground_mask.py mit_core
Output: data/processed/<region>/ortho/ground_mask.png, same extent as ortho.jpg, 4096 px (RGB):
        R = signed distance to the road (drivable) edge: 0.5 + d / 8 m, d > 0 off the road (clamped +-4 m)
        G = distance to the nearest building footprint: d / 6 m (clamped to 1)
        B = distance from any hard surface (road, sidewalk, plaza / footpath, parking, building): d / 3 m,
            i.e. how far into a lawn a point is (worn lawn edges along paths and kerbs)
Distance fields interpolate linearly, so bilinear sampling keeps the curb line sharp to ~0.1 m even
at 0.58 m/px. The shader uses them for gutter grime along curbs, kerb-side wear on sidewalks and
contact darkening where the ground meets building walls.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.ops import unary_union

from build_meshes import CONFIG, load, union_of
from geo import region_polygon
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
Image.MAX_IMAGE_PIXELS = None
OUT_PX = 4096   # default: rasterise at the ortho size and average down to this (Stage A: 8192 -> 4096)
# A region's "ground_mask_px" rasterises DIRECTLY at that size instead (no 2x supersample): at a 16k ortho
# the supersampled path would need several 2 GB float64 distance fields.


def raster(geom, size, e0, n1, res):
    img = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(img)
    to_px = lambda c: [((x - e0) / res, (n1 - y) / res) for x, y in c]
    for p in getattr(geom, "geoms", [geom]):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        dr.polygon(to_px(p.exterior.coords), fill=255)
        for r in p.interiors:
            dr.polygon(to_px(r.coords), fill=0)
    return np.asarray(img) > 0


def main(region):
    rdir = ROOT / "data/processed" / region
    meta = json.loads((rdir / "ortho/ortho.json").read_text())
    size, res, e0, n1 = meta["size_px"], meta["m_per_px"], meta["east_min_m"], meta["north_max_m"]
    out_px = OUT_PX
    direct = CONFIG["regions"][region].get("ground_mask_px")
    if direct:
        out_px = size = int(direct)
        res = meta["side_m"] / size

    # drivable area exactly as build_meshes.py builds the road mesh
    region_poly = region_polygon(region)
    roads = load(rdir, "BASEMAP_Roads")
    paved_road = unary_union([g for g, p in roads if p.get("TYPE") != "RD-TRAF-ISLAND"])
    islands = unary_union([g for g, p in roads if p.get("TYPE") == "RD-TRAF-ISLAND"] or [box(0, 0, 0, 0)])
    drivable = paved_road.difference(islands).intersection(region_poly)
    buildings = union_of(rdir, "BASEMAP_Buildings")

    road = raster(drivable, size, e0, n1, res)
    d_out = ndimage.distance_transform_edt(~road) * res        # off-road distance to the edge
    d_in = ndimage.distance_transform_edt(road) * res          # on-road distance to the edge
    sd = np.where(road, -d_in, d_out)
    del d_out, d_in
    bld = raster(buildings, size, e0, n1, res)
    db = ndimage.distance_transform_edt(~bld) * res
    del bld

    hard = unary_union([drivable, buildings, union_of(rdir, "BASEMAP_Sidewalks", "BASEMAP_Plazas",
                        "BASEMAP_PublicFootpaths", "BASEMAP_PrivateWalkways", "BASEMAP_ImperviousOther",
                        "BASEMAP_ParkingLots", "BASEMAP_Driveways")])
    hd = ndimage.distance_transform_edt(~raster(hard, size, e0, n1, res)) * res

    k = size // out_px
    down = (lambda a: a) if k == 1 else (lambda a: a.reshape(out_px, k, out_px, k).mean((1, 3)))
    out = np.zeros((out_px, out_px, 3), np.uint8)
    out[..., 0] = np.clip((0.5 + down(sd) / 8.0) * 255.0 + 0.5, 0, 255)
    out[..., 1] = np.clip(down(db) / 6.0 * 255.0 + 0.5, 0, 255)
    out[..., 2] = np.clip(down(hd) / 3.0 * 255.0 + 0.5, 0, 255)
    Image.fromarray(out).save(rdir / "ortho/ground_mask.png", optimize=True)
    print(f"ground_mask.png {out_px} px ({res * k:.2f} m/px), road px {road.mean():.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
