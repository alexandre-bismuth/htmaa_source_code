"""Extract road markings from the orthophoto (fetch_ortho.py) inside the road polygons.

Usage:  uv run markings.py mit_core [--blank]
        --blank writes a 256 px all-black placeholder instead. The ground shader no longer samples this
        texture (every ground class has P1.w = 0; vector paint from TRAFFIC_PavementMarkings replaced it in
        build_meshes.py), but build_materials.py still imports T_Markings. On a 16k ortho the extraction
        would need several 3 GB float images for no visible result.
Output: data/processed/<region>/ortho/markings.png  (R = white paint, G = yellow paint; blurred so the
        shader can threshold it into crisp anti-aliased lines), same extent as ortho.jpg.

Paint = locally bright & unsaturated (white) or yellow-hued, inside the drivable polygons. Cars are
removed as connected blobs thicker than ~0.5 m (paint lines are thin; crosswalk bars are < 0.6 m).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
Image.MAX_IMAGE_PIXELS = None


def write_blank(region):
    odir = ROOT / "data/processed" / region / "ortho"
    odir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.zeros((256, 256, 3), np.uint8)).save(odir / "markings.png", optimize=True)
    print(f"wrote blank placeholder {odir / 'markings.png'}")


def main(region):
    rdir = ROOT / "data/processed" / region
    meta = json.loads((rdir / "ortho/ortho.json").read_text())
    res, e0, n1, size = meta["m_per_px"], meta["east_min_m"], meta["north_max_m"], meta["size_px"]
    img = np.asarray(Image.open(rdir / "ortho/ortho.jpg").convert("RGB")).astype(np.float32) / 255.0

    # road mask (shrink by 0.3 m so curbs/sidewalk edges are not picked up)
    roads = [shape(f["geometry"]).buffer(0) for f in json.loads((rdir / "BASEMAP_Roads.geojson").read_text())["features"]
             if f["properties"].get("TYPE") != "RD-TRAF-ISLAND"]
    road = unary_union(roads).buffer(-0.3)
    mimg = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(mimg)
    to_px = lambda c: [((x - e0) / res, (n1 - y) / res) for x, y in c]
    for p in getattr(road, "geoms", [road]):
        if p.geom_type != "Polygon":
            continue
        dr.polygon(to_px(p.exterior.coords), fill=255)
        for r in p.interiors:
            dr.polygon(to_px(r.coords), fill=0)
    road_mask = np.asarray(mimg) > 0

    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    v = img.max(-1)
    mn = img.min(-1)
    sat = np.where(v > 1e-3, (v - mn) / np.maximum(v, 1e-3), 0)
    # local background brightness (asphalt) over ~4 m
    bg = ndimage.median_filter(v[::4, ::4], size=9)
    bg = np.kron(bg, np.ones((4, 4), np.float32))[:size, :size]
    white = road_mask & (v - bg > 0.19) & (sat < 0.22) & (v > 0.45)
    yellow = road_mask & (r > 0.35) & (g > 0.28) & (b < 0.75 * g) & (sat > 0.28) & ((r - b) > 0.12) & (v - bg > 0.05)

    def drop_blobs(mask, max_halfwidth_px):
        """Keep thin, elongated components (paint); drop blobs (cars) and speckle (branches, glints)."""
        lab, n = ndimage.label(mask)
        if n == 0:
            return mask
        idx = np.arange(1, n + 1)
        dist = ndimage.distance_transform_edt(mask)
        thick = ndimage.maximum(dist, lab, index=idx)
        area = ndimage.sum(mask, lab, index=idx)
        keep = np.zeros(n + 1, bool)
        for i, sl in enumerate(ndimage.find_objects(lab)):
            length = np.hypot(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) * res
            keep[i + 1] = thick[i] <= max_halfwidth_px and area[i] >= 6 and length >= 0.8
        return keep[lab]

    hw = 0.3 / res   # half-width threshold in px (paint thinner than ~0.6 m)
    white, yellow = drop_blobs(white, hw), drop_blobs(yellow, hw)
    out = np.zeros((size, size, 3), np.uint8)
    out[..., 0] = np.clip(ndimage.gaussian_filter(white.astype(np.float32), 0.8) * 255 * 1.6, 0, 255)
    out[..., 1] = np.clip(ndimage.gaussian_filter(yellow.astype(np.float32), 0.8) * 255 * 1.6, 0, 255)
    Image.fromarray(out).save(rdir / "ortho/markings.png", optimize=True)
    print(f"white px {white.sum()}, yellow px {yellow.sum()}, road px {road_mask.sum()}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    (write_blank if "--blank" in sys.argv else main)(args[0] if args else "mit_core")
