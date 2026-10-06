"""Step 2: build the region's world meshes from the clipped layers (clip.py) and city 3D models.

Usage:  uv run build_meshes.py mit_core
Output: data/processed/<region>/meshes/<name>.glb + manifest.json

Geometry model (flat world, single physical surface):
  road              drivable pavement at z = 0
  ground_*          everything else in the playable area, raised CURB_H, split by land use
                    (sidewalk / paved / parking / grass) for materials
  curbs             vertical edges of the raised ground = the curbs, exactly on the pavement edge
  facade_<style>    building walls (city 3D models; footprint extrusion as fallback), one mesh per
                    facade style. UV0 = (metres along the wall plane, metres above ground),
                    UV1 = (wall plane width m, building seed 0..1, +2 on shopfront planes),
                    UV2 = (plane bottom, plane top m)
                    -> procedural windows fitted to each wall in the shader
  roofs             roof faces of all buildings (shader maps the orthophoto onto them)
  water             Charles River, below the ground; walled off
  boundary          invisible wall around the playable area (region minus water)

Ground meshes carry UV0 = world East/North metres (materials tile from world position anyway).
All meshes are in ENU metres relative to the region pivot; tools/unreal places them.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import mapbox_earcut as earcut
import numpy as np
from shapely.geometry import Point, Polygon, box, shape
from shapely.ops import linemerge, transform, unary_union
from shapely.prepared import prep

import buildings3d
from geo import CONFIG, Frame, boston_tiles, camb3d_tiles, city_polygon, lonlat_box_en, region_polygon
from gltf import write_glb

ROOT = Path(__file__).resolve().parents[2]
FT = CONFIG["source_units"]["height_to_m"]

CURB_H = 0.15          # m, sidewalk/ground height above the road
SLAB_BOTTOM = -1.0     # m, walls extend down to here (hides seams)
WATER_Z = -0.8
WALL_H = 25.0          # boundary wall height
DEFAULT_BLDG_H = 30 * FT
MIN_AREA = 0.25
TILE_M = 256.0         # mesh tiling (Lumen distance fields, culling)
TILES_3D = list(CONFIG["camb3d_tiles"])   # default; a region's own list: geo.camb3d_tiles(region)


# ---------------------------------------------------------------- mesh accumulation
class MeshBuilder:
    def __init__(self):
        self.p, self.n, self.uv0, self.uv1, self.uv2, self.f = [], [], [], [], [], []
        self.count = 0

    def add(self, pos, nrm, uv0, uv1, faces, uv2=None):
        self.p.append(np.asarray(pos, float)); self.n.append(np.asarray(nrm, float))
        self.uv0.append(np.asarray(uv0, float)); self.uv1.append(np.asarray(uv1, float))
        self.uv2.append(np.zeros((len(pos), 2)) if uv2 is None else np.asarray(uv2, float))
        self.f.append(np.asarray(faces, int) + self.count)
        self.count += len(pos)

    def cap(self, poly, z, up=True):
        """Triangulated horizontal face with holes; UV0 = world EN metres."""
        rings = [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in poly.interiors]
        rings = [r for r in rings if len(r) >= 3]
        if not rings:
            return
        xy = np.vstack(rings)
        tri = earcut.triangulate_float64(xy, np.cumsum([len(r) for r in rings]).astype(np.uint32)).reshape(-1, 3)
        if len(tri) == 0:
            return
        a, b, c = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
        cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        flip = (cross < 0) if up else (cross > 0)
        tri[flip] = tri[flip][:, ::-1]
        tri = tri[np.abs(cross) > 2e-4]   # drop slivers (<1 cm^2) that float32 export can flip
        nz = 1.0 if up else -1.0
        self.add(np.column_stack([xy, np.full(len(xy), z)]), np.tile([0, 0, nz], (len(xy), 1)),
                 xy, np.zeros((len(xy), 2)), tri)

    def walls(self, poly, z0, z1, outward=True, uv1=(0.0, 0.0)):
        """Vertical walls on every ring of poly. UV0 = (metres along ring, metres up)."""
        for k, ring in enumerate([poly.exterior, *poly.interiors]):
            pts = np.asarray(ring.coords)
            # out of the solid: exterior traversed CCW, holes CW (solid on the left of travel)
            if ring.is_ccw != ((k == 0) == outward):
                pts = pts[::-1]
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            dist = np.concatenate([[0], np.cumsum(seg)])
            for i in range(len(pts) - 1):
                if seg[i] < 1e-4:
                    continue
                (x0, y0), (x1, y1) = pts[i], pts[i + 1]
                d = np.array([x1 - x0, y1 - y0]) / seg[i]
                nrm = [d[1], -d[0], 0.0]          # right of travel = outside for a CCW exterior
                self.add([[x0, y0, z0], [x1, y1, z0], [x1, y1, z1], [x0, y0, z1]], [nrm] * 4,
                         [[dist[i], z0], [dist[i + 1], z0], [dist[i + 1], z1], [dist[i], z1]],
                         [uv1] * 4, [[0, 1, 2], [0, 2, 3]])

    def export(self, out_dir, pivot, name, tile=TILE_M):
        """Write one .glb per TILE_M grid cell (by face centroid): <name>__<i>_<j>.glb.
        Smaller meshes get usable Lumen distance fields and cull/stream better."""
        if not self.p:
            return 0
        p = np.vstack(self.p); n = np.vstack(self.n); f = np.vstack(self.f)
        uv0 = np.vstack(self.uv0); uv1 = np.vstack(self.uv1); uv2 = np.vstack(self.uv2)
        cell = np.floor(p[f].mean(1)[:, :2] / tile).astype(int)
        total = 0
        for key in np.unique(cell, axis=0):
            sel = np.all(cell == key, axis=1)
            ff = f[sel]
            used, inv = np.unique(ff.reshape(-1), return_inverse=True)
            tag = f"{name}__{key[0]}_{key[1]}"
            total += write_glb(out_dir / f"{tag}.glb", p[used] - np.array([pivot[0], pivot[1], 0.0]),
                               inv.reshape(-1, 3), n[used], uv0[used], uv1[used], name, uv2[used])
        return total


# ---------------------------------------------------------------- facade styles
STYLES = ["brick_red", "brick_buff", "limestone", "concrete", "glass", "metal", "siding", "wall", "brick_georgian"]
MIT_STYLE = {
    # MIT building number -> facade style (from MIT campus architecture)
    **{n: "limestone" for n in ["1", "2", "3", "4", "5", "6", "7", "8", "10", "11", "14", "50"]},
    **{n: "concrete" for n in ["54", "18", "66", "26", "36", "38", "39", "13", "9"]},
    **{n: "brick_red" for n in ["31", "33", "35", "37", "62", "64", "68", "57", "24", "16", "56", "17"]},
    "12": "glass", "76": "glass", "32": "metal",
}


def poi_has(poi, keys, strict=False):
    """POI_Type contains one of keys. strict (region "buildings" rules): "Cambridge" no longer matches "bridge"
    (Stage A silently dropped the 3D models of Kennedy Housing and Jackson Gardens, POI "Cambridge Housing")."""
    p = poi.lower()
    if strict:
        p = p.replace("cambridge", "")
    return any(k in p for k in keys)


def seed_of(key):
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def facade_style(building_id, name, height_m, seed):
    if building_id.startswith("668-"):
        style = MIT_STYLE.get(building_id.split("-", 1)[1])
        if style:
            return style
    n = name.lower()
    if height_m >= 30.0 or any(k in n for k in ("cambridge center", "main street", "marriott", "residence inn", "institute")):
        return "glass" if seed < 0.55 else "concrete"
    if height_m < 11.0:
        return "siding" if seed < 0.6 else "brick_red"
    return "brick_red" if seed < 0.6 else ("brick_buff" if seed < 0.85 else "concrete")


# Harvard (Stage B). Harvard has no single BldgID prefix (BldgIDs are map blocks), so the catalog's
# POI_Type "Harvard University" is the flag: default brick_georgian (Harvard red brick, white sashes),
# overridden per building where the real facade is something else (STAGE_B_PLAN.md section 5.2).
HARVARD_POI = "harvard university"
HARVARD_DEFAULT = "brick_georgian"
HARVARD_STYLE = {
    # granite / limestone: University Hall, Boylston Hall, Langdell, Adolphus Busch, Swartz (Andover), Littauer
    **{b: "limestone" for b in ["318-16", "318-29", "266-6", "241-54", "241-2", "241-5", "266-17"]},
    # concrete: Science Center, William James, Carpenter Center, Gund, Mather, Peabody Terrace,
    # Smith Campus Center, Hilles, Pound, Leverett Towers
    **{b: "concrete" for b in ["266-18", "241-53", "333-2", "299-6", "513-3", "513-4",
                               "560-1", "560-3", "560-19", "560-20", "560-21", "560-22", "560-23", "560-25", "560-31",
                               "357-2", "206-16", "266-3", "498-2", "498-6"]},
    "266-12": "glass", "241-65": "glass",            # LISE, Northwest Building
    "318-28": "siding", "266-19": "siding",          # Wadsworth House, Gannett House (clapboard)
    "266-20": "brick_red", "318-17": "brick_red",    # Memorial Hall, Sever Hall (Victorian, dark frames)
}

# City Assessing FY2026 Exterior_WallType -> wall class (fetch.sh downloads the parcels + property database)
ASSESSOR_WALL = {
    **{k: "brick" for k in ("BRICK", "Brick", "BRICK-VENEER", "Brick Veneer")},
    **{k: "siding" for k in ("Frame-Clapbrd", "FRAME-CLAPBD", "Wood Shingle", "WOOD-SHN-SHK", "Aluminum-Vinyl",
                             "ALUMNM-VINYL", "Asbstos Shingl", "ASBSTOS-SHNG", "Ashalt Shingle", "ASPHALT-SHNG")},
    **{k: "concrete" for k in ("CONCR-BLOCK", "Concrete Block", "CONCR PANEL", "TILT PANEL", "STUCCO", "Stucco")},
    "METAL-GLASS": "glass", "METAL": "metal",
    **{k: "limestone" for k in ("STONE-VENEER", "Stone-Veneer", "Stone")},
}


class AssessorWalls:
    """Building centre (world EN) -> majority Exterior_WallType class of the parcel it stands on, or None."""

    def __init__(self, frame):
        import csv
        from collections import Counter
        from shapely.strtree import STRtree
        raw = ROOT / "data/raw/cambridge_gis"
        recs = defaultdict(Counter)
        for r in csv.DictReader(open(raw / "ASSESSING_PropertyDatabase_FY2026.csv", encoding="utf-8-sig")):
            k = ASSESSOR_WALL.get(r["Exterior_WallType"])
            if k:
                recs[r["GISID"]][k] += 1
        self.kind = {ml: c.most_common(1)[0][0] for ml, c in recs.items()}
        self.parcels = []
        for f in json.loads((raw / "ASSESSING_ParcelsFY2026.geojson").read_text())["features"]:
            if f.get("geometry"):
                g = transform(lambda x, y, z=None: frame.to_en(x, y), shape(f["geometry"])).buffer(0)
                self.parcels.append((g, f["properties"]["ML"]))
        self.tree = STRtree([g for g, _ in self.parcels])

    def __call__(self, e, n):
        """(wall class or None, parcel area m2), or (None, 0) off any parcel."""
        pt = Point(e, n)
        for i in self.tree.query(pt):
            g, ml = self.parcels[i]
            if g.contains(pt):
                return self.kind.get(ml), g.area
        return None, 0.0


class FacadeStyler:
    """Region facade rules. Without a "buildings" block in the region config this is exactly facade_style()
    (Stage A). With assessor_styles / harvard_styles (Stage B) the precedence is:
      1. MIT_STYLE by MIT building number;  2. HARVARD_STYLE[BldgID];  3. POI "Harvard University" ->
      brick_georgian;  4. the parcel's assessor wall type (house-scale parcels only, see assessor_style);
      5. the height / name / seed heuristic, where ">= 30 m" only means glass / concrete for buildings that
      are not churches, chapels, schools, libraries or museums (TRADITIONAL_NAMES)."""

    def __init__(self, bcfg, frame):
        self.harvard = bool(bcfg.get("harvard_styles"))
        self.assessor = AssessorWalls(frame) if bcfg.get("assessor_styles") else None
        self.v2 = self.harvard or self.assessor is not None
        self.source = defaultdict(int)    # which rule decided, for the manifest

    def __call__(self, building_id, name, height_m, seed, poi="", centre=None):
        if not self.v2:
            return facade_style(building_id, name, height_m, seed)
        if building_id.startswith("668-") and MIT_STYLE.get(building_id.split("-", 1)[1]):
            self.source["mit"] += 1
            return MIT_STYLE[building_id.split("-", 1)[1]]
        if self.harvard and building_id in HARVARD_STYLE:
            self.source["harvard_table"] += 1
            return HARVARD_STYLE[building_id]
        if self.harvard and poi.strip().lower() == HARVARD_POI:
            self.source["harvard_poi"] += 1
            return HARVARD_DEFAULT
        base = self.heuristic(building_id, name, height_m, seed)
        if self.assessor is not None and centre is not None and poi.strip().lower() != "mit":
            k = self.assessor_style(*self.assessor(*centre), height_m, seed, base)
            if k:
                self.source["assessor"] += 1
                return k
        self.source["heuristic"] += 1
        return base

    @staticmethod
    def heuristic(building_id, name, height_m, seed):
        n = name.lower()
        if height_m >= 30.0 and any(k in n for k in TRADITIONAL_NAMES):
            return "brick_red" if seed < 0.75 else "limestone"
        return facade_style(building_id, name, height_m, seed)

    @staticmethod
    def assessor_style(kind, parcel_m2, height_m, seed, base):
        """The assessor's majority wall type is per parcel: trusted on house-scale parcels (the Cambridgeport /
        Mid-Cambridge triple-deckers really are clapboard), not on institutional / office parcels holding many
        different buildings (MIT, Kendall), which keep the heuristic. A brick verdict keeps the heuristic's own
        brick colour (no red <-> buff churn); siding only on buildings up to ASSESSOR_SIDING_MAX_H."""
        if not kind or parcel_m2 > ASSESSOR_MAX_PARCEL_M2:
            return None
        if kind == "siding" and height_m > ASSESSOR_SIDING_MAX_H:
            return None
        if kind == "brick":
            return base if base in ("brick_red", "brick_buff") else ("brick_red" if seed < 0.75 else "brick_buff")
        return kind


# wood / vinyl siding only on buildings up to this height (triple-deckers are ~10-12 m; a 4-storey frame house ~14 m)
ASSESSOR_SIDING_MAX_H = 15.0
ASSESSOR_MAX_PARCEL_M2 = 8000.0   # bigger parcels (campuses, office blocks) keep the heuristic

# ">= 30 m" is not "modern" for these (steeples and towers of old masonry buildings). Not "hall" / "house":
# MIT's modern dorm towers (Tang Hall, MacGregor House, Simmons Hall) keep the approved Stage A look; Harvard's
# halls and houses are styled by their POI.
TRADITIONAL_NAMES = ("church", "chapel", "cathedral", "temple", "parish", "meeting", "library", "school", "museum")

# streets with ground-floor retail: wall planes facing them get shopfronts in the facade shader.
# props.py keeps an identical copy. The Harvard Square ones are outside Stage A (no effect there).
RETAIL_STREETS = {"Massachusetts Ave", "Main St", "River St", "Western Ave", "Prospect St", "Hampshire St",
                  "Broadway", "Cambridge St", "Third St", "Pleasant St", "Brookline St",
                  "JFK St", "Brattle St", "Mt Auburn St", "Church St", "Dunster St", "Holyoke St", "Palmer St",
                  "Eliot St", "Bow St", "Arrow St", "Winthrop St"}
SHOP_STYLES = {"brick_red", "brick_buff", "concrete", "limestone"}
MIN_WALL_M = 0.5


def reseat_walls(models, tiles=TILES_3D):
    """City 'Wall' models (garden / retaining walls) have no Ground_Elev_Ft in the catalog and their OBJs
    reach down to a common base ~10 ft below grade, so buildings3d seats them 4-9 m too tall (giant stone
    slabs). Re-seat each on the median ground elevation of the 6 nearest catalogued buildings
    (real tops: median ~0.6 m, 95th percentile ~3 m above grade)."""
    from scipy.spatial import cKDTree
    walls = [b for b in models if b.poi_type.lower() == "wall"]
    if not walls:
        return 0
    rows = buildings3d.catalog(tiles)
    frame = Frame()
    g = [r for r in rows if r["Ground_Elev_Ft"]]
    e, n = frame.to_en(np.array([float(r["Center_Long"]) for r in g]), np.array([float(r["Center_Lat"]) for r in g]))
    kd = cKDTree(np.column_stack([e, n]))
    gnd = np.array([float(r["Ground_Elev_Ft"]) for r in g])
    by_id = {r["Model_ID"]: r for r in rows}
    for b in walls:
        r = by_id[b.model_id]
        obj = next((buildings3d.RAW / r["Tile"] / "models" / f"{r['Model_ID']}_OBJ").glob("*.obj"))
        vmin_ft = buildings3d._read_obj(obj)[0][:, 2].min()
        _, idx = kd.query(b.vertices[:, :2].mean(0), k=6)
        z = b.vertices[:, 2] - (np.median(gnd[idx]) - vmin_ft) * FT
        if z.max() < MIN_WALL_M:
            z = b.vertices[:, 2] * (MIN_WALL_M / max(b.vertices[:, 2].max(), 1e-3))
        b.vertices[:, 2] = np.maximum(z, 0.0)
    return len(walls)


WALL_MAX_OVERLAP = 0.5   # a garden wall mostly inside a building footprint is a modelling duplicate


def model_footprint(b):
    """Union of a model's projected triangles (courtyards stay open, unlike a convex hull)."""
    tri = b.vertices[b.faces][:, :, :2]
    u, v = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    keep = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) > 2e-3
    return unary_union([Polygon(t) for t in tri[keep]])


def carriageway_check(models, drivable, drop_m2=None, skip_area=None, report_m2=2.0):
    """Models whose footprint covers the drivable road surface. Returns (kept models, report rows, dropped rows).
    With drop_m2, 'Wall' models covering more than drop_m2 of carriageway are dropped (underpass trench walls,
    the BU Bridge parapet...), except those whose centre lies in skip_area (Stage A: checked in game first)."""
    from shapely.strtree import STRtree
    parts = list(polys(drivable))
    tree = STRtree(parts)
    kept, report, dropped = [], [], []
    for b in models:
        f = model_footprint(b)
        a = sum(f.intersection(parts[i]).area for i in tree.query(f)) if not f.is_empty else 0.0
        c = b.vertices[:, :2].mean(0)
        row = {"model_id": b.model_id, "bldg_id": b.building_id, "name": b.name, "poi": b.poi_type,
               "road_m2": round(a, 1), "en_m": [round(float(c[0])), round(float(c[1]))]}
        is_wall = b.poi_type.lower() == "wall"
        if (drop_m2 is not None and is_wall and a > drop_m2
                and not (skip_area is not None and skip_area.contains(Point(float(c[0]), float(c[1]))))):
            dropped.append(row)
            continue
        if a > report_m2:
            report.append(row)
        kept.append(b)
    return kept, sorted(report, key=lambda r: -r["road_m2"]), sorted(dropped, key=lambda r: -r["road_m2"])


def drop_buried_walls(models):
    """Drop 'Wall' models whose footprint lies mostly inside building footprints (they poke through
    facades as stray stone strips). Footprints = projected triangles, so courtyards stay open."""
    from shapely.geometry import Polygon
    from shapely.strtree import STRtree

    foot = model_footprint
    is_wall = [b.poi_type.lower() == "wall" for b in models]
    blds = [foot(b) for b, w in zip(models, is_wall) if not w]
    tree = STRtree(blds)
    out, dropped = [], 0
    for b, w in zip(models, is_wall):
        if w:
            f = foot(b)
            if not f.is_empty and sum(f.intersection(blds[i]).area for i in tree.query(f)) > WALL_MAX_OVERLAP * f.area:
                dropped += 1
                continue
        out.append(b)
    return out, dropped


def shop_tester(rdir):
    """f(centre_xy, outward_normal_xy) -> True when a wall plane faces a retail street within ~12 m."""
    lines = [g for g, p in load(rdir, "TRANS_Centerlines") if p.get("Street") in RETAIL_STREETS]
    if not lines:
        return None
    zone = prep(unary_union(lines).buffer(13.0))
    return lambda c, nxy: zone.contains(Point(c[0] + nxy[0] * 7.0, c[1] + nxy[1] * 7.0))


BOSTON_TILES = CONFIG.get("boston", {}).get("tiles", [])


def boston_style(name, height_m, east, seed):
    """Boston backdrop facades: glass / metal towers, Back Bay and Beacon Hill brick rowhouses,
    limestone and concrete downtown (east of ~3.2 km in our frame)."""
    if height_m >= 60.0:
        return "glass" if seed < 0.65 else ("metal" if seed < 0.85 else "concrete")
    if east < 3200.0 and height_m < 30.0:
        return "brick_red" if seed < 0.55 else ("brick_buff" if seed < 0.85 else "limestone")
    return "limestone" if seed < 0.4 else ("concrete" if seed < 0.7 else ("brick_buff" if seed < 0.85 else "glass"))


def add_building_faces(walls_by_style, roofs, verts, faces, style, seed, shop_fn=None):
    """Split a building mesh into wall faces (procedural-window UVs) and roof faces.
    shop_fn(centre_xy, normal_xy) marks street-facing shopfront planes (UV1.y = seed + 2)."""
    tri = verts[faces].copy()
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(nrm, axis=1)
    keep = area > 1e-6
    tri, nrm, area = tri[keep], nrm[keep], area[keep]
    nrm = nrm / area[:, None]
    is_wall = np.abs(nrm[:, 2]) < 0.35
    # make walls face outward relative to the building centre (two-sided materials cover the
    # remaining cases on concave buildings); roofs face up
    centre = verts.mean(0)
    flip = np.where(is_wall, np.einsum("ij,ij->i", nrm[:, :2], tri.mean(1)[:, :2] - centre[:2]) < 0, nrm[:, 2] < 0)
    tri[flip] = tri[flip][:, ::-1]
    nrm[flip] = -nrm[flip]

    # walls: group faces by plane so windows can be centred on each wall plane
    w = np.where(is_wall)[0]
    if len(w):
        t = np.column_stack([-nrm[w, 1], nrm[w, 0]])
        t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
        ang = np.round(np.degrees(np.arctan2(nrm[w, 1], nrm[w, 0])) / 2.0).astype(int)
        off = np.round(np.einsum("ij,ij->i", nrm[w, :2], tri[w, 0, :2]) / 0.3).astype(int)
        u = np.einsum("ijk,ik->ij", tri[w][:, :, :2], t)          # (faces, 3) metres along plane
        planes = defaultdict(list)
        for i, key in enumerate(zip(ang, off)):
            planes[key].append(i)
        mb = walls_by_style[style]
        for idxs in planes.values():
            idxs = np.array(idxs)
            u0 = u[idxs].min()
            width = u[idxs].max() - u0
            zb = tri[w[idxs]][:, :, 2].min()
            zt = tri[w[idxs]][:, :, 2].max()
            pseed = seed
            if shop_fn is not None and width >= 4.0 and zb < 1.0 and zt > 5.5:
                if shop_fn(tri[w[idxs]][:, :, :2].reshape(-1, 2).mean(0), nrm[w[idxs[0]], :2]):
                    pseed = seed + 2.0
            for i in idxs:
                fi = w[i]
                p3 = tri[fi]
                mb.add(p3, [nrm[fi]] * 3, np.column_stack([u[i] - u0, p3[:, 2]]), [[width, pseed]] * 3, [[0, 1, 2]],
                       [[zb, zt]] * 3)
    for fi in np.where(~is_wall)[0]:
        p3 = tri[fi]
        roofs.add(p3, [nrm[fi]] * 3, p3[:, :2], [[0.0, seed]] * 3, [[0, 1, 2]])


# ---------------------------------------------------------------- helpers
def polys(geom):
    if geom is None or geom.is_empty:
        return
    for g in getattr(geom, "geoms", [geom]):
        if isinstance(g, Polygon) and g.area >= MIN_AREA:
            yield g
        elif hasattr(g, "geoms"):
            yield from polys(g)


def load(region_dir, layer):
    p = region_dir / f"{layer}.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text())["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        out.append((g.buffer(0) if g.geom_type in ("Polygon", "MultiPolygon") else g, f["properties"]))
    return out


def union_of(region_dir, *layers):
    gs = [g for l in layers for g, _ in load(region_dir, l) if g.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(gs) if gs else Polygon()


def compute_spawn(rdir, spec, drivable):
    """Point on a street centerline, dist_m from the end nearest start_near_en, offset into the right lane."""
    lines = [g for g, p in load(rdir, "TRANS_Centerlines") if p.get("Street") == spec["street"]]
    merged = linemerge(unary_union(lines))
    start = Point(spec["start_near_en"])
    line = min(getattr(merged, "geoms", [merged]), key=lambda g: g.distance(start))
    if Point(line.coords[0]).distance(start) > Point(line.coords[-1]).distance(start):
        line = type(line)(line.coords[::-1])
    p0, p1 = line.interpolate(spec["dist_m"]), line.interpolate(spec["dist_m"] + 1.0)
    de, dn = p1.x - p0.x, p1.y - p0.y
    norm = (de * de + dn * dn) ** 0.5
    de, dn = de / norm, dn / norm
    e, n = p0.x + dn * spec["lane_offset_m"], p0.y - de * spec["lane_offset_m"]  # right of travel
    assert drivable.contains(Point(e, n)), "spawn is not on the road surface"
    yaw = float(np.degrees(np.arctan2(-dn, de)))  # UE yaw: 0 = +X (east), +90 = +Y (south)
    return {"en_m": [round(e, 2), round(n, 2)], "ue_cm": [round(e * 100, 1), round(-n * 100, 1), 50.0], "ue_yaw_deg": round(yaw, 2)}


# ---------------------------------------------------------------- main
# vector road paint (City of Cambridge TRAFFIC_PavementMarkings): line centres -> stripes of these
# widths (m); closed outlines of these types are filled (crosswalk bars, stop bars, arrows, text...)
MARK_WIDTH = {"PM-LANEMARKER": 0.12, "PM-PARKING": 0.10, "PM-PARKING-OS": 0.10, "PM-BIKE": 0.10,
              "PM-DIRECTIONAL": 0.12, "PM-TEXT": 0.10, "PM-STOPLINE": 0.40, "PM-CROSSWALK": 0.30,
              "PM-YIELD": 0.10, "PM-HANDICAPPED": 0.08, "PM-RAISE-CW": 0.30, "PM-BUFFER": 0.10}
MARK_FILL = {"PM-CROSSWALK", "PM-STOPLINE", "PM-DIRECTIONAL", "PM-TEXT", "PM-YIELD", "PM-HANDICAPPED",
             "PM-BIKE", "PM-RAISE-CW"}
MARK_Z = 0.006


def build_markings(rdir, road_area):
    """White / yellow paint as thin geometry 6 mm above the road. The layer has no colour: lane lines
    within ~1 m of a two-way street's centreline (TRANS_Centerlines Direction "0") are the yellow centre
    lines; everything else is white. (The aerial photo can't tell them apart at 13 cm/px.)
    Returns (white, yellow) geometries clipped to the road."""
    from shapely.geometry import Point
    path = rdir / "TRAFFIC_PavementMarkings.geojson"
    if not path.exists():
        return Polygon(), Polygon()
    two_way = unary_union([shape(f["geometry"]) for f in json.loads((rdir / "TRANS_Centerlines.geojson").read_text())["features"]
                           if f.get("geometry") and (f["properties"] or {}).get("Direction") == "0"])
    two_way = prep(two_way.buffer(1.0)) if not two_way.is_empty else None
    is_yellow = lambda ls: two_way is not None and two_way.contains(ls.interpolate(0.5, normalized=True))

    white, yellow = [], []
    for f in json.loads(path.read_text())["features"]:
        if not f.get("geometry"):
            continue
        t = (f["properties"] or {}).get("TYPE")
        if t not in MARK_WIDTH:
            continue
        g = shape(f["geometry"])
        for ls in getattr(g, "geoms", [g]):
            if ls.length < 0.05:
                continue
            c = list(ls.coords)
            closed = len(c) >= 4 and np.allclose(c[0], c[-1], atol=0.02)
            if closed and t in MARK_FILL:
                piece = Polygon(c).buffer(0)
            else:
                piece = ls.buffer(MARK_WIDTH[t] / 2, cap_style=2, join_style=2)
            if piece.is_empty:
                continue
            (yellow if t == "PM-LANEMARKER" and is_yellow(ls) else white).append(piece)
    area = road_area.buffer(0.2)
    clip = lambda gs: unary_union(gs).intersection(area) if gs else Polygon()
    return clip(white), clip(yellow)


def main(region):
    frame = Frame()
    rdir = ROOT / "data/processed" / region
    out = rdir / "meshes"
    out.mkdir(exist_ok=True)
    for old in (g for g in out.glob("*.glb") if " " not in g.name):   # leave iCloud conflict copies alone
        old.unlink()

    spec = CONFIG["regions"][region]
    bcfg = spec.get("buildings", {})
    tiles = camb3d_tiles(region)
    skip_poi = tuple(bcfg.get("skip_poi", ("bridge", "overpass")))
    region_poly = region_polygon(region, frame)   # = the lon/lat bbox unless the region has a "playable" block
    c = region_poly.centroid
    pivot = (round(c.x), round(c.y))

    water = union_of(rdir, "HYDRO_WaterBodies")
    playable = region_poly.difference(water)
    roads = load(rdir, "BASEMAP_Roads")
    paved_road = unary_union([g for g, p in roads if p.get("TYPE") != "RD-TRAF-ISLAND"])
    islands = unary_union([g for g, p in roads if p.get("TYPE") == "RD-TRAF-ISLAND"] or [Polygon()])
    drivable = paved_road.difference(islands).intersection(region_poly)
    ground = playable.difference(drivable)

    # land-use split of the raised ground (materials only; physically it is one surface)
    sidewalk = ground.intersection(union_of(rdir, "BASEMAP_Sidewalks"))
    paved = ground.intersection(union_of(rdir, "BASEMAP_Plazas", "BASEMAP_PublicFootpaths",
                                         "BASEMAP_PrivateWalkways", "BASEMAP_ImperviousOther")).difference(sidewalk)
    parking = ground.intersection(union_of(rdir, "BASEMAP_ParkingLots", "BASEMAP_Driveways")).difference(sidewalk).difference(paved)
    grass = ground.difference(sidewalk).difference(paved).difference(parking)

    stats = {}

    def emit(name, mb):
        stats[name] = mb.export(out, pivot, name)

    m = MeshBuilder()
    for p in polys(drivable):
        m.cap(p, 0.0)
    emit("road", m)
    white, yellow = build_markings(rdir, drivable)
    for name, geom in (("markings_white", white), ("markings_yellow", yellow)):
        m = MeshBuilder()
        for p in polys(geom):
            m.cap(p, MARK_Z)
        emit(name, m)
    for name, geom in [("ground_sidewalk", sidewalk), ("ground_paved", paved), ("ground_parking", parking), ("ground_grass", grass)]:
        m = MeshBuilder()
        for p in polys(geom):
            m.cap(p, CURB_H)
        emit(name, m)
    m = MeshBuilder()
    for p in polys(ground):
        m.walls(p, SLAB_BOTTOM, CURB_H)
    emit("curbs", m)
    m = MeshBuilder()
    for p in polys(water.intersection(region_poly)):
        m.cap(p, WATER_Z)
    emit("water", m)
    m = MeshBuilder()
    for p in polys(playable):
        m.walls(p, SLAB_BOTTOM, WALL_H, outward=False)  # face the player, inside the area
    emit("boundary", m)

    # --- buildings: city 3D models, footprint extrusion for the rest
    walls_by_style = defaultdict(MeshBuilder)
    roofs = MeshBuilder()
    styles_used = defaultdict(int)
    all_models = buildings3d.load(tiles, region_poly, frame)
    strict = bool(bcfg)
    skipped_poi = [{"model_id": b.model_id, "name": b.name, "poi": b.poi_type} for b in all_models
                   if poi_has(b.poi_type, skip_poi, strict)]
    models = [b for b in all_models if not poi_has(b.poi_type, skip_poi, strict)]
    modelled_ids = {b.building_id for b in models if b.building_id}
    from shapely.geometry import MultiPoint
    modelled_area = unary_union([MultiPoint(b.vertices[:, :2]).convex_hull for b in models])
    reseated = reseat_walls(models, tiles)
    models, walls_dropped = drop_buried_walls(models)
    road_check = None
    if "drop_road_walls_m2" in bcfg:
        skip = bcfg.get("drop_road_walls_skip_bbox_lonlat")
        models, overlaps, road_dropped = carriageway_check(
            models, drivable, bcfg["drop_road_walls_m2"], lonlat_box_en(skip, frame) if skip else None)
        road_check = {"walls_dropped_on_carriageway": road_dropped, "carriageway_overlaps": overlaps}
    styler = FacadeStyler(bcfg, frame)
    shop_fn = shop_tester(rdir)
    harvard_shop = styler.harvard
    shop_ok = lambda bid, style, seed, poi="": (shop_fn if style in SHOP_STYLES and not bid.startswith("668-") and seed < 0.85
                                                 and not (harvard_shop and poi.strip().lower() == HARVARD_POI) else None)
    for b in models:
        seed = seed_of(b.model_id)
        # garden / river walls are modelled too: plain stone, no windows
        style = "wall" if b.poi_type.lower() == "wall" else styler(
            b.building_id, b.name, b.height_m, seed, b.poi_type, b.vertices[:, :2].mean(0))
        styles_used[style] += 1
        add_building_faces(walls_by_style, roofs, b.vertices, b.faces, style, seed,
                           shop_ok(b.building_id, style, seed, b.poi_type))

    fallback = 0
    for g, p in load(rdir, "BASEMAP_Buildings"):
        bid = p.get("BldgID") or ""
        if bid in modelled_ids or p.get("TYPE") == "OVHD-WALKWAY":
            continue
        if g.area > 0 and g.intersection(modelled_area).area > 0.3 * g.area:
            continue  # same building under a different id: the 3D model already covers it
        h = (p.get("ELEV_GL") or 0) * FT
        if h <= 0:
            h = DEFAULT_BLDG_H
        seed = seed_of(bid or str(g.centroid))
        rp = g.representative_point()
        style = styler(bid, "", h, seed, "", (rp.x, rp.y))
        for poly in polys(g.intersection(region_poly)):
            mb = MeshBuilder()
            mb.walls(poly, SLAB_BOTTOM, h)
            mb.cap(poly, h)
            add_building_faces(walls_by_style, roofs, np.vstack(mb.p), np.vstack(mb.f), style, seed, shop_ok(bid, style, seed))
            fallback += 1
            styles_used[style] += 1

    for style in STYLES:
        if style in walls_by_style:
            emit(f"facade_{style}", walls_by_style[style])
    emit("roofs", roofs)

    stats.update(build_context(region, frame, region_poly, out, pivot, styler if styler.v2 else None))

    manifest = {
        "region": region,
        "spawn": compute_spawn(rdir, CONFIG["regions"][region]["spawn"], drivable),
        "pivot_en_m": pivot,
        "pivot_ue_cm": [pivot[0] * 100.0, -pivot[1] * 100.0, 0.0],
        "triangles": stats,
        "buildings": {"models_3d": len(models), "fallback_extrusions": fallback, "styles": dict(styles_used),
                      "walls_reseated": reseated, "walls_dropped_in_buildings": walls_dropped,
                      **({"tiles": tiles, "skipped_poi": skipped_poi, "style_rule": dict(styler.source)} if bcfg else {}),
                      **(road_check or {})},
        "areas_m2": {k: round(v.area) for k, v in [("drivable", drivable), ("sidewalk", sidewalk), ("paved", paved),
                                                    ("parking", parking), ("grass", grass)]},
        "constants": {"curb_h": CURB_H, "water_z": WATER_Z, "wall_h": WALL_H},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def build_context(region, frame, region_poly, out, pivot, styler=None):
    """Backdrop ring around the play area (context bbox minus region): same surfaces and buildings,
    prefixed ctx_, coarser tiles, no collision, no curbs. Seen across the boundary walls."""
    spec = CONFIG["regions"][region].get("context_bbox_lonlat")
    cdir = ROOT / "data/processed" / region / "context"
    if not spec or not cdir.exists():
        return {}
    bcfg = CONFIG["regions"][region].get("buildings", {})
    tiles = camb3d_tiles(region)
    bos_tiles = boston_tiles(region)
    skip_poi = tuple(bcfg.get("skip_poi", ("bridge", "overpass"))) + ("wall",)
    ctx = lonlat_box_en(spec, frame)
    ring = ctx.difference(region_poly)
    water = union_of(cdir, "HYDRO_WaterBodies")
    land = ring.difference(water)
    roads = load(cdir, "BASEMAP_Roads")
    paved_road = unary_union([g for g, p in roads if p.get("TYPE") != "RD-TRAF-ISLAND"])
    road = paved_road.intersection(land)
    ground = land.difference(road)
    sidewalk = ground.intersection(union_of(cdir, "BASEMAP_Sidewalks"))
    paved = ground.intersection(union_of(cdir, "BASEMAP_Plazas", "BASEMAP_PublicFootpaths", "BASEMAP_PrivateWalkways",
                                          "BASEMAP_ImperviousOther", "BASEMAP_ParkingLots", "BASEMAP_Driveways")).difference(sidewalk)
    # Boston: the land across the river has no Cambridge GIS surfaces; it's one piece of "city ground"
    # textured mostly by the aerial photo (the land component that touches no Cambridge road)
    if bcfg.get("ctx_city_ground") == "outside_city":
        # all ring land outside the City of Cambridge (Boston, Allston, Somerville, which has no 3D models):
        # ortho-dominant "city ground" instead of Cambridge-style lawn. Fringe streets in the Cambridge GIS
        # (200 ft past the line) stay ctx_road.
        outside = land.difference(city_polygon(frame)).difference(paved_road)
        city = unary_union([p for p in polys(outside) if p.area > 2000.0])
        sidewalk = sidewalk.difference(city)
        paved = paved.difference(city)
    else:
        city = unary_union([p for p in polys(land) if not p.intersects(paved_road)]) if bos_tiles else Polygon()
    ground = ground.difference(city)
    grass = ground.difference(sidewalk).difference(paved)
    stats = {}
    tile = 512.0

    def emit(name, mb):
        stats[name] = mb.export(out, pivot, name, tile)

    for name, geom, z in [("ctx_road", road, 0.0), ("ctx_ground_sidewalk", sidewalk, CURB_H),
                          ("ctx_ground_paved", paved, CURB_H), ("ctx_ground_grass", grass, CURB_H),
                          ("ctx_ground_city", city, CURB_H),
                          ("ctx_water", water.intersection(ring), WATER_Z)]:
        m = MeshBuilder()
        for p in polys(geom):
            m.cap(p, z)
        emit(name, m)

    walls_by_style = defaultdict(MeshBuilder)
    roofs = MeshBuilder()
    models = [b for b in buildings3d.load(tiles, ring, frame) if not poi_has(b.poi_type, skip_poi, bool(bcfg))]
    for b in models:
        seed = seed_of(b.model_id)
        style = (styler(b.building_id, b.name, b.height_m, seed, b.poi_type, b.vertices[:, :2].mean(0)) if styler
                 else facade_style(b.building_id, b.name, b.height_m, seed))
        add_building_faces(walls_by_style, roofs, b.vertices, b.faces, style, seed)
    # Boston skyline (City of Boston 3D model): the river bank and anything taller than 12 m
    river = water.buffer(0)
    keep = lambda e, n, h: h >= 12.0 or river.distance(Point(e, n)) < 400.0
    bos = buildings3d.load_boston(bos_tiles, ring, frame, keep) if bos_tiles else []
    for b in bos:
        seed = seed_of(b.model_id)
        e = float(b.vertices[:, 0].mean())
        add_building_faces(walls_by_style, roofs, b.vertices, b.faces, boston_style(b.name, b.height_m, e, seed), seed)
    for style in STYLES:
        if style in walls_by_style:
            emit(f"ctx_facade_{style}", walls_by_style[style])
    emit("ctx_roofs", roofs)
    stats["ctx_models"] = len(models)
    stats["boston_models"] = len(bos)
    return stats


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
