"""Distance-field and surface-type masks for the ground shader (tools/unreal/shaders/ground.hlsl, water.hlsl).

Usage:  uv run make_ground_mask.py mit_core        (~1.5 min, ~6.5 GB peak memory)
Output: data/processed/<region>/ortho/, all on the ortho.jpg extent (texel centres = the shader's uv).
(Round 5's ground_mask.png, raster distance transforms off by up to a texel, is no longer used.)

  edge_mask.png      4096 px RGBA, uncompressed (exact distances, see exact_sdf):
        R = 0.5 + signed distance to the road edge / 8 m (> 0 off the road; curb tops, gutters, kerb wear)
        G = distance to the nearest building footprint / 6 m (contact darkening, mulch beds)
        B = 0.5 + signed distance to the lawn edge / 6 m (> 0 inside a lawn: worn edges, ortho fade, stripes fade)
        A = distance from the river bank into the water / 40 m (shore darkening, deep water), 0 on land

  surface_mask.png   4096 px RGBA, uncompressed (block compression at 8192 wobbled straight edges by 0.1-0.3 m;
                     exact distances at ~1 m texels keep straight edges exact, small tree wells get rounded corners),
                     signed distances 0.5 + d / 4 m (> 0 inside, clamped +-2 m) of the paving material where the City of
                     Cambridge GIS knows it (or the orthophoto shows red brick):
        R = brick (SW-BRICK sidewalks, reddish walkways / plazas / patios)
        G = asphalt (SW-BITMINOUS sidewalks, PAVED public footpaths: park paths)
        B = unsealed (TREE-WELL sidewalk cut-outs, UNPAVED footpaths, gravel parking / driveways)
        A = poured concrete (SW-CONCRETE sidewalks, plain walkways / pads); elsewhere the class texture (pavers)

  surface_angle.png  8192 px L, point-sampled (Load), lossless: per GIS polygon (hard surfaces) or lawn piece
        code = 1 + theta / 1.5 deg (1..120), 0 = unknown. theta = dominant edge direction of the polygon, snapped to
        the map's dominant directions (snap_angles) so neighbouring polygons share a code (pavers, brick bond and
        sidewalk joints follow the path / street and continue across polygon edges; lawns are mowed along it).
        Hard-surface codes are dilated 3 px into lawns so the hard side never reads a lawn code at its edge.
"""
import json
import sys
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import box
from shapely.ops import unary_union

from build_meshes import load, union_of
from geo import region_polygon

ROOT = Path(__file__).resolve().parents[2]
Image.MAX_IMAGE_PIXELS = None
EDGE_PX = 4096
SDF_PX = 4096       # surface_mask: uncompressed, ~1 m texels (BC5 / BC7 at 0.5 m wobbled straight edges by ~0.1-0.3 m)
SURF_PX = 8192      # surface_angle


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


# ---------------------------------------------------------------- exact distance fields
def polygonal(geom):
    """The polygon parts of any geometry as one MultiPolygon (boolean ops can return GeometryCollections, whose
    boundary GEOS leaves undefined)."""
    parts = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g is None or g.is_empty:
            continue
        if g.geom_type == "Polygon":
            parts.append(g)
        elif hasattr(g, "geoms"):
            stack.extend(g.geoms)
    return shapely.MultiPolygon(parts) if parts else shapely.MultiPolygon()


def exact_sdf(geom, size, e0, n1, res, band):
    """Signed distance (m, float32, > 0 outside geom) at the texel centres of a size^2 grid whose top-left corner is
    (e0, n1). Within `band` m of the boundary the distance is exact (KD-tree over the boundary densified to 4 cm, sign
    from point-in-polygon next to the edge), so the zero crossing of the bilinearly filtered field sits on the real edge
    (a raster distance transform is off by up to a texel and staircases along diagonal edges). Beyond the band:
    raster distance (only used clamped)."""
    geom = polygonal(geom)
    if geom.is_empty:
        return np.full((size, size), band * 4.0, np.float32)
    inside = raster(geom, size, e0, n1, res)
    d = np.where(inside, -ndimage.distance_transform_edt(inside), ndimage.distance_transform_edt(~inside)).astype(np.float32)
    d *= res
    pts = shapely.get_coordinates(shapely.segmentize(shapely.boundary(geom), 0.04))
    tree = cKDTree(pts)
    near = np.abs(d) < band + 1.5 * res
    iy, ix = np.nonzero(near)
    x = e0 + (ix + 0.5) * res
    y = n1 - (iy + 0.5) * res
    dist, _ = tree.query(np.column_stack([x, y]), workers=-1, distance_upper_bound=band + 3.0 * res)
    dist = np.minimum(dist, band + 3.0 * res)
    sgn = np.sign(d[near])
    amb = np.abs(d[near]) <= 2.0 * res
    shapely.prepare(geom)
    ins = shapely.contains_xy(geom, x[amb], y[amb])
    sgn[amb] = np.where(ins, -1.0, 1.0)
    sgn[sgn == 0] = 1.0
    d[near] = (sgn * dist).astype(np.float32)
    return d


def dominant_angle(poly):
    """Dominant edge direction of a polygon in degrees [0, 180) (East = 0, counter-clockwise): the peak of the
    edge-length histogram of edge directions mod 180 (robust to L shapes, unlike the minimum rotated rectangle)."""
    e = np.diff(np.asarray(poly.exterior.coords), axis=0)
    for r in poly.interiors:
        e = np.vstack([e, np.diff(np.asarray(r.coords), axis=0)])
    ln = np.hypot(e[:, 0], e[:, 1])
    if ln.sum() <= 0:
        return 0.0
    a = np.degrees(np.arctan2(e[:, 1], e[:, 0])) % 180.0
    h, _ = np.histogram(a, bins=90, range=(0, 180), weights=ln)
    h = h + 0.5 * (np.roll(h, 1) + np.roll(h, -1))            # 2 deg bins, wrap-around smoothing
    i = int(np.argmax(h))
    sel = np.abs(((a - (i * 2 + 1)) + 90) % 180 - 90) < 3.0     # refine: length-weighted mean of the peak's edges
    if sel.any():
        d = ((a[sel] - (i * 2 + 1)) + 90) % 180 - 90
        return float(((i * 2 + 1) + np.average(d, weights=ln[sel])) % 180.0)
    return float(i * 2 + 1)


def ortho_colour(img, meta, g):
    """Mean colour (0..255) of the sunlit 40% of the orthophoto inside polygon g (shadows / cars excluded)."""
    res, e0, n1 = meta["m_per_px"], meta["east_min_m"], meta["north_max_m"]
    x0, y0, x1, y1 = g.bounds
    c0, r0 = int((x0 - e0) / res), int((n1 - y1) / res)
    c1, r1 = int((x1 - e0) / res) + 2, int((n1 - y0) / res) + 2
    if c0 < 0 or r0 < 0 or c1 >= img.shape[1] or r1 >= img.shape[0]:
        return None
    msk = Image.new("L", (c1 - c0, r1 - r0), 0)
    dr = ImageDraw.Draw(msk)
    for p in getattr(g, "geoms", [g]):
        if p.geom_type == "Polygon":
            dr.polygon([((x - e0) / res - c0, (n1 - y) / res - r0) for x, y in p.exterior.coords], fill=255)
    px = img[r0:r1, c0:c1][np.asarray(msk) > 0].astype(np.float32)
    if len(px) < 8:
        return None
    lum = px @ np.array([0.299, 0.587, 0.114], np.float32)
    return px[lum >= np.percentile(lum, 60)].mean(0)


BRICK_RED = 0.12     # (R - B) / luminance of the sunlit part: SW-BRICK sidewalks median 0.12, SW-CONCRETE p75 0.08


def classify(region, rdir, meta):
    """Surface type geometries (brick, asphalt, unsealed) and angle features [(polygon, code)] in drawing order
    (later wins: parking < paved < sidewalks < tree wells, the precedence build_meshes.py uses for the mesh classes)."""
    print("  loading orthophoto for brick detection ...", flush=True)
    img = np.asarray(Image.open(rdir / "ortho/ortho.jpg").convert("RGB"))
    side = load(rdir, "BASEMAP_Sidewalks")
    paved_layers = ["BASEMAP_PublicFootpaths", "BASEMAP_PrivateWalkways", "BASEMAP_Plazas", "BASEMAP_ImperviousOther"]
    paved = [(g, p, L) for L in paved_layers for g, p in load(rdir, L)]
    park = [(g, p) for L in ("BASEMAP_ParkingLots", "BASEMAP_Driveways") for g, p in load(rdir, L)]
    poly_ok = lambda g: g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty

    S = {"brick": [], "asph": [], "tree": [], "other": []}
    for g, p in side:
        if not poly_ok(g):
            continue
        t = p.get("TYPE")
        S["brick" if t == "SW-BRICK" else "asph" if t == "SW-BITMINOUS" else "tree" if t == "TREE-WELL" else "other"].append(g)
    side_all = unary_union([g for v in S.values() for g in v])

    P = {"brick": [], "asph": [], "uns": [], "poured": [], "pavers": []}
    stats = {"brick_by_ortho": 0}
    pk = []
    for g, p, L in paved:
        if not poly_ok(g):
            continue
        t = p.get("TYPE")
        if t == "PAVED":
            k = "asph"
        elif t == "UNPAVED":
            k = "uns"
        else:
            c = ortho_colour(img, meta, g)
            red = (c[0] - c[2]) / max(float(c @ np.array([0.299, 0.587, 0.114])), 1.0) if c is not None else 0.0
            if red >= BRICK_RED and t in ("SW-PRIVATE", "PLAZA", "PATIO", None):
                k = "brick"
                stats["brick_by_ortho"] += 1
            elif t in ("PLAZA", "PATIO") or (t is None and L == "BASEMAP_Plazas"):
                k = "pavers"
            else:
                k = "poured"
        P[k].append(g)
        pk.append((g, k))
    del img
    paved_all = unary_union([g for v in P.values() for g in v]).difference(side_all)
    K_uns = [g for g, p in park if poly_ok(g) and p.get("TYPE") in ("PRKNG-UNP", "DRIVE-UNP")]
    K_all = unary_union([g for g, p in park if poly_ok(g)]).difference(side_all).difference(paved_all)

    tree = unary_union(S["tree"])
    brick = unary_union([unary_union(S["brick"]).difference(tree), unary_union(P["brick"]).intersection(paved_all)])
    asph = unary_union([unary_union(S["asph"]).difference(tree).difference(brick),
                        unary_union(P["asph"]).intersection(paved_all).difference(brick)])
    uns = unary_union([tree, unary_union(P["uns"]).intersection(paved_all).difference(brick).difference(asph),
                       unary_union(K_uns).intersection(K_all)])
    # poured (cast-in-place) concrete: concrete sidewalks, plain walkways / pads (else: pavers, the class texture)
    poured = unary_union([unary_union(S["other"]), unary_union(P["poured"]).intersection(paved_all)])
    for k, v in (("brick", brick), ("asphalt", asph), ("unsealed", uns), ("poured", poured)):
        stats[f"{k}_m2"] = round(v.area)

    # angle features in drawing order (later overwrites): parking, paved, sidewalks, tree wells
    feats = [g for g, p in park if poly_ok(g)] + [g for g, k in pk] + S["other"] + S["brick"] + S["asph"] + S["tree"]
    return brick, asph, uns, poured, feats, stats


ANGLE_STEP = 1.5      # deg per code: 90 deg = 60 codes exactly, so square grids turned by 90 deg keep their phase


def angle_code(theta):
    return 1 + int(round((theta % 180.0) / ANGLE_STEP)) % int(180 / ANGLE_STEP)


def polygon_angles(geoms):
    """[(polygon, theta deg, area)] for every polygon part (>= 0.25 m2) of the given geometries."""
    out = []
    for g in geoms:
        for p in getattr(g, "geoms", [g]):
            if p.geom_type == "Polygon" and p.area >= 0.25:
                out.append((p, dominant_angle(p), p.area))
    return out


def snap_angles(items, tol=4.0):
    """Snap polygon directions to the map's dominant directions (area-weighted peaks of theta mod 90): neighbouring
    polygons along one street then share exactly one code, so paver / joint / brick patterns (anchored at the world
    origin) continue across their common edge instead of jumping. Keeps each polygon's own 90 deg quadrant."""
    th = np.array([t for _, t, _ in items]) % 90.0
    w = np.array([a for _, _, a in items])
    h, _ = np.histogram(th, bins=180, range=(0, 90), weights=w)
    k = np.exp(-0.5 * (np.arange(-8, 9) / 3.0) ** 2)
    hs = np.convolve(np.concatenate([h[-8:], h, h[:8]]), k / k.sum(), "valid")
    peaks = [i for i in range(180) if hs[i] >= hs[i - 1] and hs[i] >= hs[(i + 1) % 180] and hs[i] > 0.004 * hs.sum()]
    centres = np.array(sorted({round((i * 0.5 + 0.25) / ANGLE_STEP) * ANGLE_STEP % 90.0 for i in peaks}))
    out, n = [], 0
    for p, t, a in items:
        if len(centres):
            d = (centres - (t % 90.0) + 45.0) % 90.0 - 45.0
            j = int(np.argmin(np.abs(d)))
            if abs(d[j]) <= tol:
                t = t + d[j]
                n += 1
        out.append((p, angle_code(t)))
    return out, len(centres), n


def draw_codes(items, size, e0, n1, res):
    img = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(img)
    to_px = lambda c: [((x - e0) / res, (n1 - y) / res) for x, y in c]
    for p, code in items:
        dr.polygon(to_px(p.exterior.coords), fill=code)
    return np.asarray(img).copy()


def new_masks(region):
    rdir = ROOT / "data/processed" / region
    meta = json.loads((rdir / "ortho/ortho.json").read_text())
    side_m, e0, n1 = meta["side_m"], meta["east_min_m"], meta["north_max_m"]
    region_poly = region_polygon(region)
    roads = load(rdir, "BASEMAP_Roads")
    paved_road = unary_union([g for g, p in roads if p.get("TYPE") != "RD-TRAF-ISLAND"])
    islands = unary_union([g for g, p in roads if p.get("TYPE") == "RD-TRAF-ISLAND"] or [box(0, 0, 0, 0)])
    drivable = paved_road.difference(islands).intersection(region_poly)
    buildings = union_of(rdir, "BASEMAP_Buildings")
    water = union_of(rdir, "HYDRO_WaterBodies").intersection(region_poly)
    hard = unary_union([drivable, buildings, union_of(rdir, "BASEMAP_Sidewalks", "BASEMAP_Plazas",
                        "BASEMAP_PublicFootpaths", "BASEMAP_PrivateWalkways", "BASEMAP_ImperviousOther",
                        "BASEMAP_ParkingLots", "BASEMAP_Driveways")])
    lawn = region_poly.difference(water).difference(hard)
    report = {}

    # ---- edge mask (4096, ~1 m texels, exact distances)
    size = EDGE_PX
    res = side_m / size
    print(f"edge_mask {size} px ({res:.2f} m/px)", flush=True)
    out = np.zeros((size, size, 4), np.uint8)
    q = lambda a: np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 0] = q(0.5 + exact_sdf(drivable, size, e0, n1, res, 4.5) / 8.0)
    out[..., 1] = q(np.maximum(exact_sdf(buildings, size, e0, n1, res, 6.5), 0.0) / 6.0)
    out[..., 2] = q(0.5 - exact_sdf(lawn, size, e0, n1, res, 3.5) / 6.0)
    wat = raster(water, size, e0, n1, res)
    out[..., 3] = q(ndimage.distance_transform_edt(wat) * res / 40.0) * wat
    Image.fromarray(out, "RGBA").save(rdir / "ortho/edge_mask.png")

    # ---- surface types (8192, ~0.5 m texels)
    size = SURF_PX
    res = side_m / size
    print(f"surface_mask {size} px ({res:.2f} m/px)", flush=True)
    brick, asph, uns, poured, feats, stats = classify(region, rdir, meta)
    report.update(stats)
    sres = side_m / SDF_PX
    out = np.zeros((SDF_PX, SDF_PX, 4), np.uint8)
    for i, g in enumerate((brick, asph, uns, poured)):
        out[..., i] = q(0.5 - exact_sdf(g, SDF_PX, e0, n1, sres, 2.2) / 4.0)
    Image.fromarray(out, "RGBA").save(rdir / "ortho/surface_mask.png")
    del out

    # ---- angles: hard polygons (dilated 3 px), then lawn pieces, then nearest fill
    print("surface_angle", flush=True)
    hard_items = polygon_angles(feats)
    lawn_items = sorted(polygon_angles([p for p in getattr(lawn, "geoms", [lawn]) if p.area >= 4.0]), key=lambda f: -f[2])
    snapped, ncentres, nsnapped = snap_angles(hard_items + lawn_items)   # small lawn pieces (islands in holes) last
    H = draw_codes(snapped[:len(hard_items)], size, e0, n1, res)
    Lw = draw_codes(snapped[len(hard_items):], size, e0, n1, res)
    lawn_feats = lawn_items
    report.update({"angle_centres": ncentres, "angles_snapped": nsnapped, "angles_total": len(snapped)})
    dist, (iy, ix) = ndimage.distance_transform_edt(H == 0, return_indices=True)
    A = np.where((H == 0) & (dist <= 3.0), H[iy, ix], H)
    del dist, iy, ix
    A = np.where((A == 0) & (Lw > 0), Lw, A)
    del Lw, H
    dist, (iy, ix) = ndimage.distance_transform_edt(A == 0, return_indices=True)
    A = A[iy, ix]
    del dist, iy, ix
    Image.fromarray(A.astype(np.uint8), "L").save(rdir / "ortho/surface_angle.png")
    report.update({"lawn_pieces": len(lawn_feats), "angle_features": len(feats)})
    (rdir / "ortho/surface_mask.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    new_masks(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
