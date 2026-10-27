"""Step 3: place props (trees, street lights) from the city inventories, and generate the simple
prop meshes (lamp posts / cobrahead poles) that have no free model.

Usage:  uv run props.py mit_core
Output: data/processed/<region>/props/props.json   [{type, x, y, z (UE cm), yaw, scale}]
        data/processed/common/props/*.glb          generated pole meshes
Needs:  data/processed/common/props/parked_cars.json (tools/blender/parked_cars.py) for the parked cars ("parked_<body>",
        see place_parked; skipped without it) and CambridgeRacer/Tracks/<region>.json (events they must keep clear of).
        Check: uv run checks/parked_check.py <region>

Trees: live street trees (SiteType "Tree") + MIT campus trees (Ownership "MIT"), target height from
trunk diameter (inches DBH) with a simple urban allometry: H = 4 m + 0.55 m/in, clamped to 4..22 m.
Then thinned (~60% dropped, see thin_trees()), then each kept tree gets one of the procedural
variants in data/processed/common/props/trees/trees.json (tools/blender/build_trees.py) from its
Genus (trees.json genus_map), the variant whose height is closest to the target (young variants for
small trees), scaled uniformly by target / variant height (clamped). Prop type "tree_<variant>".
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon, box, shape
from shapely.ops import nearest_points, transform, unary_union
from shapely.prepared import prep

import buildings3d
from geo import CONFIG, Frame, camb3d_tiles, region_polygon
from gltf import write_glb

ROOT = Path(__file__).resolve().parents[2]
CURB_H = 0.15
CROWN_R = 0.4              # crown radius / tree height used for thinning (the old jacaranda's ratio)
CROWN_OVERLAP = 0.8        # drop a tree whose crown overlaps a taller kept one by more than 20%
YOUNG_H, YOUNG_KEEP = 8.0, 0.25  # keep 25% of young trees (< 8 m)
# utility poles: the inventory's TYPE "UNKNOWN" points come in 3 m clusters (bollards / sign posts, not
# 10 m wooden poles), and Cambridge's main commercial streets have buried utilities
UPOLE_SPACING = 15.0       # keep at most one pole per 15 m
UPOLE_LIGHT_CLEAR = 2.5    # a pole this close to a street light is that light's own pole
CURB_SETBACK = 0.6        # anything the inventories put on the carriageway goes this far behind the curb
SIGNAL_POLE_SPACING = 8.0  # the signal inventory has a point per head; one mast pole per approach
SHELTER_MAX_OVERLAP = 0.15 # bus-shelter footprints that sit on a building (e.g. the Central Sq T headhouse)
RETAIL_STREETS = {"Massachusetts Ave", "Main St", "River St", "Western Ave", "Prospect St", "Hampshire St",
                  "Broadway", "Cambridge St", "Third St", "Pleasant St", "Brookline St",
                  "JFK St", "Brattle St", "Mt Auburn St", "Church St", "Dunster St", "Holyoke St", "Palmer St",
                  "Eliot St", "Bow St", "Arrow St", "Winthrop St"}   # = build_meshes.py
# what blocks a tree: the 3D models' convex hulls ("hull", Stage A: also swallows courtyards and back yards),
# their projected-triangle footprints ("footprint"), or footprints only for Harvard University models
# ("harvard": the river-house courtyards and Widener light courts keep their trees, everything else as Stage A)
TREE_BLOCK = "harvard"

TREES_JSON = ROOT / "data/processed/common/props/trees/trees.json"
SCALE_MIN, SCALE_MAX = 0.6, 1.4      # uniform scale clamp (trunks stay plausible, no skinny giants)
FIT_MIN, FIT_MAX = 0.75, 1.3         # a variant "fits" a target height within this scale band
YOUNG_VARIANTS = ("oak_c", "linden_b", "honeylocust_b", "plane_b")   # small trees: no shrunk adults
# inventory spellings / genera missing from trees.json genus_map -> closest look-alike genus
GENUS_ALIAS = {
    "Quercos": "Quercus", "Styphnolobium": "Styphnoloblum",            # typos (data or genus_map)
    "Maackia": "Koelreuteria", "Robinia": "Gleditsia", "Carya": "Fraxinus", "Phellodendron": "Fraxinus",
    "Ailanthus": "Fraxinus",                                            # pinnate leaves -> honey locust
    "Chionanthus": "Cornus", "Halesia": "Cornus", "Styrax": "Cornus", "Oxydendrum": "Cornus",
    "Sorbus": "Malus",                                                  # small flowering -> ornamental
    "Sassafras": "Nyssa", "Morus": "Tilia", "Corylus": "Carpinus", "Maclura": "Celtis",
    # conifers: no conifer model. ginkgo_a has the narrowest, most upright crown and the generator
    # already uses it for Metasequoia; a missing street tree reads worse than a wrong-genus one
    "Pinus": "Ginkgo", "Picea": "Ginkgo", "Tsuga": "Ginkgo", "Larix": "Ginkgo", "Taxodium": "Ginkgo",
    "Thuja": "Ginkgo",
}
SKIP_GENERA = {"Taxus", "Juniperus"}  # yews / junipers: mostly shrubs and hedges, not street trees


def rnd(key, salt):
    return int(hashlib.md5(f"{key}:{salt}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def curb_snapper(load):
    """-> (snap, carriageway_prep). snap(pt) moves a point that lies on the carriageway (roads minus
    traffic islands, exactly as build_meshes.py builds the drivable surface) to the nearest curb plus
    CURB_SETBACK, onto the sidewalk / island; returns (point, moved), point None = drop it."""
    from shapely.geometry import Point as P
    from shapely.ops import nearest_points
    feats = [f for f in load("BASEMAP_Roads") if f.get("geometry")]
    roads = unary_union([shape(f["geometry"]).buffer(0) for f in feats if f["properties"].get("TYPE") != "RD-TRAF-ISLAND"])
    islands = unary_union([shape(f["geometry"]).buffer(0) for f in feats if f["properties"].get("TYPE") == "RD-TRAF-ISLAND"] or [P(0, 0).buffer(0)])
    cw = roads.difference(islands)
    cw_prep, edge = prep(cw), cw.boundary

    def snap(pt):
        if not cw_prep.contains(pt):
            return pt, False
        out = pt
        for step in (CURB_SETBACK, 1.0, 2.0, 3.0):     # thin islands / slivers: re-snap from the new point
            q = nearest_points(edge, out)[0]
            d = np.array([q.x - out.x, q.y - out.y])
            d /= np.linalg.norm(d) + 1e-9
            out = P(q.x + d[0] * step, q.y + d[1] * step)
            if not cw_prep.contains(out):
                return out, True
        return None, True                              # no curb within reach: drop it
    return snap, cw_prep


def building_footprints(models, load):
    """Union of the real building footprints: projected triangles of the 3D models (not their convex
    hulls, which would swallow courtyards) plus the 2D basemap buildings. Garden walls excluded."""
    from shapely.geometry import Polygon
    parts = []
    for b in models:
        if b.poi_type.lower() in ("wall", "bridge", "overpass", "tunnel"):
            continue
        tri = b.vertices[b.faces][:, :, :2]
        u, v = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        a = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) * 0.5
        parts += [Polygon(t) for t in tri[a > 1e-3]]
    parts += [shape(f["geometry"]).buffer(0) for f in load("BASEMAP_Buildings")
              if f.get("geometry") and f["properties"].get("TYPE") != "OVHD-WALKWAY"]
    return unary_union(parts)


def cylinder(r0, r1, z0, z1, seg=12, cx=0.0, cy=0.0):
    a = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    p, n, f = [], [], []
    for i in range(seg):
        j = (i + 1) % seg
        for (ang, r, z) in [(a[i], r0, z0), (a[j], r0, z0), (a[j], r1, z1), (a[i], r1, z1)]:
            p.append([cx + r * math.cos(ang), cy + r * math.sin(ang), z])
            n.append([math.cos(ang), math.sin(ang), 0.0])
        k = len(p) - 4
        f += [[k, k + 1, k + 2], [k, k + 2, k + 3]]
    return np.array(p), np.array(n), np.array(f)


def boxmesh(x0, y0, z0, x1, y1, z1):
    p, n, f = [], [], []
    faces = [((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
             ((0, 0, -1), [(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)]),
             ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ((-1, 0, 0), [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]),
             ((0, 1, 0), [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]),
             ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)])]
    for nn, quad in faces:
        k = len(p)
        p += quad; n += [nn] * 4
        f += [[k, k + 1, k + 2], [k, k + 2, k + 3]]
    return np.array(p, float), np.array(n, float), np.array(f)


def merge(parts):
    P, N, F, off = [], [], [], 0
    for p, n, f in parts:
        P.append(p); N.append(n); F.append(f + off); off += len(p)
    return np.vstack(P), np.vstack(N), np.vstack(F)


def write_pole_meshes(out):
    out.mkdir(parents=True, exist_ok=True)
    # historic post (lantern mounted on top in Unreal): 3.6 m black fluted-ish post with a base
    p, n, f = merge([cylinder(0.16, 0.13, 0.0, 0.5, 16), cylinder(0.07, 0.055, 0.5, 3.6, 12), cylinder(0.09, 0.09, 3.6, 3.75, 12)])
    write_glb(out / "lamp_post.glb", p, f, n, np.zeros((len(p), 2)), np.zeros((len(p), 2)), "lamp_post")
    # cobrahead: 8.5 m galvanised pole, 2.4 m arm, flat luminaire head (arm points +X)
    pole = cylinder(0.11, 0.07, 0.0, 8.6, 12)
    arm = boxmesh(0.0, -0.04, 8.25, 2.4, 0.04, 8.33)
    head = boxmesh(2.0, -0.22, 8.12, 2.85, 0.22, 8.32)
    p, n, f = merge([pole, arm, head])
    write_glb(out / "cobra_pole.glb", p, f, n, np.zeros((len(p), 2)), np.zeros((len(p), 2)), "cobra_pole")


def thin_trees(trees):
    """Tallest first, keep a tree unless its crown overlaps a kept one; then thin young trees."""
    from scipy.spatial import cKDTree
    xy = np.array([[t["x"], t["y"]] for t in trees]) / 100.0
    h = np.array([t["h"] for t in trees])
    kd = cKDTree(xy)
    keep = np.zeros(len(trees), bool)
    for i in np.argsort(-h):
        near = kd.query_ball_point(xy[i], CROWN_OVERLAP * CROWN_R * (h[i] + h.max()))
        if not any(keep[j] and np.hypot(*(xy[i] - xy[j])) < CROWN_OVERLAP * CROWN_R * (h[i] + h[j]) for j in near):
            keep[i] = True
    return [t for k, t in zip(keep, trees)
            if k and (t["h"] >= YOUNG_H or rnd(t["id"], "keep") < YOUNG_KEEP)]


class TreeVariants:
    """Genus + target height -> (variant, uniform scale), from trees.json."""

    def __init__(self, path=TREES_JSON):
        d = json.loads(path.read_text())
        self.height = {k: v["height_m"] for k, v in d["variants"].items()}
        self.genus_map = {g.lower(): vs for g, vs in d["genus_map"].items()}
        self.default = self.genus_map[""]
        self.alias = {k.lower(): v.lower() for k, v in GENUS_ALIAS.items()}
        self.skip = {g.lower() for g in SKIP_GENERA}

    def family(self, variants):
        """All variants of the same species group (oak_c for oak_a, ornamental_b for ornamental_a...)."""
        fams = {v.rsplit("_", 1)[0] for v in variants}
        return sorted(v for v in self.height if v.rsplit("_", 1)[0] in fams)

    def resolve(self, genus):
        """-> (candidate variants or None to skip, how the genus was resolved)."""
        g = (genus or "").strip().lower()
        if g in self.skip:
            return None, "skip"
        if g in self.alias:
            return self.genus_map[self.alias[g]], "alias"
        if g in self.genus_map:
            return self.genus_map[g], "map" if g else "empty"
        return self.default, "unknown"

    def pick(self, cands, h, key):
        H = self.height
        ratio = lambda v: h / H[v]
        choose = lambda ok: ok[min(int(rnd(key, "variant") * len(ok)), len(ok) - 1)]   # deterministic
        fam = self.family(cands)
        best = min(fam, key=lambda v: abs(math.log(ratio(v))))
        small = ratio(best) < FIT_MIN
        # a variant of the genus, then of its species group, then (small trees whose group has no
        # young variant) a generic young one, that fits the target height; per-tree pick among them
        for pool in (cands, fam, YOUNG_VARIANTS if small else ()):
            ok = [v for v in pool if FIT_MIN <= ratio(v) <= FIT_MAX]
            if ok:
                return choose(ok)
        # nothing fits: the closest (scale clamped), a young one for very small trees
        if small:
            return min(list(fam) + list(YOUNG_VARIANTS), key=lambda v: abs(math.log(ratio(v))))
        return best

    def assign(self, t):
        cands, how = self.resolve(t["genus"])
        if cands is None:
            return None, how
        v = self.pick(cands, t["h"], t["id"])
        return (v, float(np.clip(t["h"] / self.height[v], SCALE_MIN, SCALE_MAX))), how


def place_furniture(load, roads, inside, bldg=None, stats=None, snap=None):
    """Street furniture from the city's inventories (the layers fetch.sh downloads):
    hydrants, park benches (footprint lines), litter barrels, bike racks, bus shelters (footprints),
    traffic signal poles, parking meters (one per two metered spaces, at the curb), the street
    lights the city doesn't own (MIT's), utility poles."""
    from shapely.geometry import LineString
    from shapely.ops import nearest_points
    road_union = unary_union(roads)
    road_edge = road_union.boundary
    on_road = prep(road_union)
    in_bldg = prep(bldg.buffer(-0.2)) if bldg is not None else None
    stats = {} if stats is None else stats
    out = []

    def pos(pt, kind, yaw=0.0, **extra):
        if snap is not None:                                  # last line of defence (meters, benches, shelters)
            pt, moved = snap(pt)
            if moved:
                stats[f"{kind}_off_carriageway"] = stats.get(f"{kind}_off_carriageway", 0) + 1
            if pt is None:
                return
        if in_bldg is not None and in_bldg.contains(pt):
            stats[f"{kind}_in_building"] = stats.get(f"{kind}_in_building", 0) + 1
            return
        z = 0.0 if on_road.contains(pt) else CURB_H * 100
        out.append({"type": kind, "x": pt.x * 100, "y": -pt.y * 100, "z": z, "yaw": yaw, "scale": 1.0, **extra})

    def yaw_to(pt, q):
        return math.degrees(math.atan2(-(q.y - pt.y), q.x - pt.x))   # UE yaw (Y = south)

    def facing_road(pt):
        return yaw_to(pt, nearest_points(road_edge, pt)[0])

    def points(layer):
        for f in load(layer):
            if f.get("geometry"):
                g = shape(f["geometry"])
                if g.geom_type == "Point" and inside.contains(g):
                    p = dict(f["properties"], _orig=g)
                    if snap is not None:
                        g, moved = snap(g)
                        if moved:
                            stats[f"{layer}_moved_to_curb"] = stats.get(f"{layer}_moved_to_curb", 0) + 1
                        if g is None:
                            continue
                    yield g, p

    for pt, p in points("INFRA_Hydrants"):
        pos(pt, "hydrant", -(p.get("ROTATION") or 0.0))
    for pt, p in points("DPW_LitterBarrels"):
        pos(pt, "litter", facing_road(pt))
    for pt, p in points("RECREATION_BikeRacks"):
        if p.get("Status", "Existing") == "Existing":
            pos(pt, "bikerack", facing_road(pt) + 90.0)     # racks run along the curb
    for pt, p in points("INFRA_StreetLightsNotCityOwned"):
        pos(pt, "lamp", facing_road(pt))
    # utility poles: none on the retail streets, none next to a street light, one per UPOLE_SPACING
    # (inventory "UTILITY-POLE" points win over "UNKNOWN" ones)
    from scipy.spatial import cKDTree
    lights = [g for n in ("INFRA_StreetLights", "INFRA_StreetLightsNotCityOwned") for g, _ in points(n)]
    kl = cKDTree([(g.x, g.y) for g in lights]) if lights else None
    retail = [shape(f["geometry"]) for f in load("TRANS_Centerlines")
              if f.get("geometry") and f["properties"].get("Street") in RETAIL_STREETS]
    on_retail = prep(unary_union(retail).buffer(15.0)) if retail else None
    poles = sorted(points("INFRA_UtilityPoles"), key=lambda q: q[1].get("TYPE") != "UTILITY-POLE")
    kept = []
    for pt, p in poles:
        why = ("retail" if on_retail is not None and on_retail.contains(pt) else
               "light" if kl is not None and kl.query((pt.x, pt.y))[0] < UPOLE_LIGHT_CLEAR else
               "spacing" if any(pt.distance(q) < UPOLE_SPACING for q in kept) else None)
        if why:
            stats[f"upole_dropped_{why}"] = stats.get(f"upole_dropped_{why}", 0) + 1
            continue
        kept.append(pt)
        pos(pt, "upole", facing_road(pt) + 90.0)
    nodes = [shape(f["geometry"]) for f in load("TRANS_Intersections") if f.get("geometry")]
    # traffic signals: the inventory points are the signal heads, mostly over the lanes. One mast-arm
    # pole per approach at the curb (snapped by points()), the arm reaching back over the lanes toward
    # the head position, heads facing the intersection (traffic approaching a far-side mast arm).
    # signal_pole lenses are on the mesh -y side, signal_m's on +y: pick the one facing the node.
    sigs = []
    for pt, p in points("TRAFFIC_Signals"):
        if any(pt.distance(o) < SIGNAL_POLE_SPACING for o in sigs):
            stats["signal_same_approach"] = stats.get("signal_same_approach", 0) + 1
            continue
        sigs.append(pt)
        o = p["_orig"]
        a = np.array([o.x - pt.x, o.y - pt.y])
        if np.linalg.norm(a) < 0.3:                       # inventory point already at the curb
            q = nearest_points(road_edge, pt)[0]
            a = np.array([q.x - pt.x, q.y - pt.y])
        a /= np.linalg.norm(a) + 1e-9
        node = min(nodes, key=lambda n: n.distance(pt)) if nodes else o
        lens_minus_y = np.array([a[1], -a[0]])           # mesh -y = Unreal local +Y = arm rotated -90 deg (ENU)
        kind = "signal" if lens_minus_y @ np.array([node.x - pt.x, node.y - pt.y]) >= 0 else "signal_m"
        pos(pt, kind, math.degrees(math.atan2(-a[1], a[0])))
    for f in load("INFRA_ParkBenches"):
        g = shape(f["geometry"]) if f.get("geometry") else None
        if g is None or g.length < 0.5 or not inside.contains(g.centroid):
            continue
        a, b = np.array(g.coords[0]), np.array(g.coords[-1])
        c = g.interpolate(0.5, normalized=True)
        pos(c, "bench", math.degrees(math.atan2(-(b[1] - a[1]), b[0] - a[0])),
            sx=float(np.clip(g.length / 1.17, 0.8, 2.2)))
    for f in load("TRANS_BusShelters"):
        g = shape(f["geometry"]).buffer(0) if f.get("geometry") else None
        if g is None or g.is_empty or not inside.contains(g.centroid):
            continue
        if bldg is not None and g.intersection(bldg).area > SHELTER_MAX_OVERLAP * g.area:
            stats["shelter_on_building"] = stats.get("shelter_on_building", 0) + 1
            continue
        rect = list(g.minimum_rotated_rectangle.exterior.coords)[:4]
        e0, e1 = np.subtract(rect[1], rect[0]), np.subtract(rect[2], rect[1])
        long_e, short = (e0, np.linalg.norm(e1)) if np.linalg.norm(e0) >= np.linalg.norm(e1) else (e1, np.linalg.norm(e0))
        yaw = math.degrees(math.atan2(-long_e[1], long_e[0]))
        c = g.centroid
        # the open side must face the street (mesh +y north = Unreal local -Y, i.e. yaw - 90)
        to_road = facing_road(c)
        if math.cos(math.radians(to_road - (yaw - 90.0))) < 0:
            yaw += 180.0
        pos(c, "shelter", yaw, sx=float(np.clip(np.linalg.norm(long_e) / 4.0, 0.6, 2.5)), sy=float(np.clip(short / 1.6, 0.6, 2.0)))
    # meters: one double-head post per two metered spaces, on the sidewalk next to the space
    spaces = [shape(f["geometry"]).buffer(0) for f in load("TRAFFIC_MeteredParkingSpaces")
              if f.get("geometry") and f["properties"].get("Status", "In Service") == "In Service"]
    spaces = [g for g in spaces if not g.is_empty and inside.contains(g.centroid)]
    spaces.sort(key=lambda g: (round(g.centroid.x / 50), g.centroid.y))
    for g in spaces[::2]:
        c = g.centroid
        q = nearest_points(road_edge, c)[0]          # the curb next to the space
        d = np.array([q.x - c.x, q.y - c.y])
        d = d / (np.linalg.norm(d) + 1e-9)
        from shapely.geometry import Point as P
        m = P(q.x + d[0] * 0.45, q.y + d[1] * 0.45)
        pos(m, "meter", yaw_to(m, c))
    return out


def write_furniture_meshes(out):
    """Generated street furniture (no free models exist for these): Cambridge "staple" bike rack,
    single-head parking meter, mast-arm traffic signal (pole + arm in black, heads, lenses),
    wooden utility pole, bus shelter (frame, roof, glass). Origin at the base, +X forward."""
    def save(name, parts):
        p, n, f = merge(parts)
        write_glb(out / f"{name}.glb", p, f, n, np.zeros((len(p), 2)), np.zeros((len(p), 2)), name)

    # bike rack: inverted U of 4 cm tube, 0.75 m wide, 0.85 m tall (bent top as short segments)
    rack = []
    for x in (-0.375, 0.375):
        rack.append(cylinder(0.024, 0.024, 0.0, 0.70, 10, cx=x))
    for k in range(6):
        a0, a1 = math.pi * k / 6, math.pi * (k + 1) / 6
        x0, z0 = -0.375 * math.cos(a0), 0.70 + 0.15 * math.sin(a0)
        x1, z1 = -0.375 * math.cos(a1), 0.70 + 0.15 * math.sin(a1)
        rack.append(boxmesh(min(x0, x1) - 0.024, -0.024, min(z0, z1) - 0.02, max(x0, x1) + 0.024, 0.024, max(z0, z1) + 0.02))
    save("bike_rack", rack)
    # parking meter: post + head
    save("parking_meter", [cylinder(0.045, 0.045, 0.0, 1.05, 10), boxmesh(-0.11, -0.09, 1.05, 0.11, 0.09, 1.42),
                           cylinder(0.11, 0.11, 1.42, 1.48, 12)])
    # traffic signal: 6 m pole, 5.5 m mast arm toward +X (over the street), two heads on the arm and a
    # pedestal head on the pole; lenses face -y (signal_lens) or +y (signal_lens_m), i.e. across the arm,
    # toward the approaching traffic
    save("signal_pole", [cylinder(0.14, 0.11, 0.0, 6.2, 14), boxmesh(0.0, -0.06, 5.75, 5.5, 0.06, 5.9),
                         boxmesh(2.6, -0.17, 4.75, 2.98, 0.17, 5.75), boxmesh(4.9, -0.17, 4.75, 5.28, 0.17, 5.75),
                         boxmesh(-0.2, -0.17, 2.6, 0.18, 0.17, 3.6)])
    for name, side in (("signal_lens", -1.0), ("signal_lens_m", 1.0)):
        lens = []
        for hx, ztop in ((2.6, 5.62), (4.9, 5.62), (-0.2, 3.47)):
            for k in range(3):
                z = ztop - 0.3 * k
                y0, y1 = sorted((side * 0.17, side * 0.20))
                lens.append(boxmesh(hx + 0.08, y0, z - 0.11, hx + 0.30, y1, z + 0.11))
        save(name, lens)
    # wooden utility pole with a crossarm
    save("utility_pole", [cylinder(0.16, 0.12, 0.0, 10.5, 12), boxmesh(-0.06, -1.2, 9.6, 0.06, 1.2, 9.75)])
    # bus shelter 4.0 x 1.6 x 2.5 m, open to the front (+Y side, the street)
    frame = [cylinder(0.04, 0.04, 0.0, 2.45, 8, cx=x, cy=y) for x in (-1.95, 1.95) for y in (-0.75, 0.75)]
    frame.append(boxmesh(-2.05, -0.85, 2.45, 2.05, 0.9, 2.55))       # roof
    save("bus_shelter", frame)
    save("bus_shelter_glass", [boxmesh(-1.95, -0.77, 0.15, 1.95, -0.74, 2.3),       # back wall
                               boxmesh(-1.97, -0.75, 0.15, -1.94, 0.3, 2.3),        # side panels
                               boxmesh(1.94, -0.75, 0.15, 1.97, 0.3, 2.3)])


# ------------------------------------------------------------------------------------------------ parked cars
# Static parked cars (tools/blender/parked_cars.py meshes, prop type "parked_<body>"), parallel to the curb with the
# kerb-side wheels ~0.25 m off the kerb, or nose-in in marked lot stalls. Where Cambridge parks:
#   metered spaces (TRAFFIC_MeteredParkingSpaces: one car per space, centred in it; not "Permanently Removed"/"Proposed"),
#   marked on-street spaces (TRAFFIC_PavementMarkings PM-PARKING: T-marks and lane lines -> that curb has parking),
#   local streets (TRANS_Centerlines MajorRoad None, not restricted ways / alleys) by kerb-to-kerb width: >= 9 m both
#   sides, 7-9 m one side (per street segment), minor arterials (MajorRoad 2) >= 11.5 m both sides except the campus
#   streets in NO_PARK_STREETS, never on principal arterials (Mass Ave, Memorial Dr, Mt Auburn St) outside meters,
#   surface lots (BASEMAP_ParkingLots stall lines PM-PARKING-OS: one car between two adjacent stall lines).
# Never: within PARK_JUNCTION_M + half the widest street of a junction, PARK_CROSSWALK_M of a crosswalk / stop line,
# PARK_HYDRANT_M of a hydrant, PARK_DRIVEWAY_M of a driveway, PARK_BUS_M of a bus shelter, on bridges / alleys, in a
# building, or within PARK_LINE_CLEAR_M (footprint to polyline) of any event's racing line, inside any gate band
# (PARK_GATE_ALONG_M along the route x gate width + PARK_GATE_SIDE_M), any start box, or near the spawns.
# Densities: occupancy per block / lot (gaps, not bumper to bumper); body type by the fleet weights in parked_cars.json.
PARKED_JSON = ROOT / "data/processed/common/props/parked_cars.json"
PARK_KERB_GAP = 0.25          # m from the kerb line to the car's kerb-side flank
PARK_JUNCTION_M = 10.0        # m past the cross street's half width
PARK_CROSSWALK_M = 6.0        # MA: 20 ft from a crosswalk
PARK_HYDRANT_M = 3.0          # MA: 10 ft from a hydrant
PARK_DRIVEWAY_M = 1.0
PARK_BUS_M = 15.0
PARK_LINE_CLEAR_M = 3.5       # footprint (incl. mirrors) to any racing line
PARK_GATE_ALONG_M = 5.0       # each side of a gate, along the route (pylons + curtain + a car length of slack)
PARK_GATE_SIDE_M = 3.0        # beyond the gate's half width
PARK_START_M = 12.0           # around a start box / start line
PARK_SPAWN_M = 25.0
OCC_METER, OCC_MARKED, OCC_RESID, OCC_LOT = 0.72, 0.66, 0.62, (0.30, 0.75)
NO_PARK_STREETS = {"Vassar St", "Ames St", "Memorial Dr", "Binney St", "Galileo Galilei Way", "Edwin H Land Blvd",
                   "Land Blvd", "Monsignor OBrien Hwy", "Msgr OBrien Hwy", "Albany St", "Harvard Bridge", "Longfellow Bridge",
                   "Massachusetts Ave", "Mt Auburn St", "Main St", "Fresh Pond Pkwy", "Soldiers Field Rd"}


def _rect(cx, cy, hx, hy, L, W):
    """Footprint polygon: centre, unit heading (hx, hy), length, width."""
    ax, ay = hx * L / 2, hy * L / 2
    bx, by = -hy * W / 2, hx * W / 2
    return Polygon([(cx + ax + bx, cy + ay + by), (cx - ax + bx, cy - ay + by), (cx - ax - bx, cy - ay - by),
                    (cx + ax - bx, cy + ay - by)])


def parking_exclusions(load, region, cw):
    """-> dict name: geometry of the places no parked car may touch (ENU m) + the event geometry for the check."""
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    ex = {}
    # junctions: radius = PARK_JUNCTION_M + half the widest street there (width measured across each centreline)
    edge = cw.boundary
    cl = [(shape(f["geometry"]), f["properties"]) for f in load("TRANS_Centerlines") if f.get("geometry")]
    widths = []
    for g, p in cl:
        ls = g if g.geom_type == "LineString" else max(g.geoms, key=lambda q: q.length)
        widths.append(street_width(cw, ls) or 10.0)
    tree = STRtree([g for g, _ in cl])
    circles = []
    for f in load("TRANS_Intersections"):
        if not f.get("geometry"):
            continue
        n = shape(f["geometry"])
        near = tree.query(n.buffer(1.0))
        w = max([widths[i] for i in near] or [10.0])
        circles.append(n.buffer(PARK_JUNCTION_M + 0.5 * min(w, 30.0), 16))
    ex["junction"] = unary_union(circles)
    pm = load("TRAFFIC_PavementMarkings")
    ex["crosswalk"] = unary_union([shape(f["geometry"]).buffer(PARK_CROSSWALK_M, 6) for f in pm
                                   if f.get("geometry") and f["properties"].get("TYPE") in ("PM-CROSSWALK", "PM-RAISE-CW")])
    ex["stopline"] = unary_union([shape(f["geometry"]).buffer(4.0, 6) for f in pm
                                  if f.get("geometry") and f["properties"].get("TYPE") == "PM-STOPLINE"])
    ex["hydrant"] = unary_union([shape(f["geometry"]).buffer(PARK_HYDRANT_M, 8) for f in load("INFRA_Hydrants") if f.get("geometry")])
    ex["driveway"] = unary_union([shape(f["geometry"]).buffer(PARK_DRIVEWAY_M) for f in load("BASEMAP_Driveways") if f.get("geometry")])
    ex["bus"] = unary_union([shape(f["geometry"]).buffer(PARK_BUS_M) for f in load("TRANS_BusShelters") if f.get("geometry")])
    rl = [shape(f["geometry"]).buffer(0) for f in load("BASEMAP_Roads") if f.get("geometry")
          and f["properties"].get("TYPE") in ("RD-BRIDGE", "RD-ALLEY", "RD-UNPAVED")]
    ex["bridge_alley"] = unary_union(rl).buffer(3.0) if rl else Polygon()
    # events (CambridgeRacer/Tracks/<region>.json, UE cm -> ENU m)
    en = lambda x, y: (x / 100.0, -y / 100.0)
    tj = ROOT / f"CambridgeRacer/Tracks/{region}.json"
    lines, gates, starts = [], [], []
    tracks = json.loads(tj.read_text()) if tj.exists() else {"tracks": []}
    for t in tracks["tracks"]:
        pts = [en(p[0], p[1]) for p in t["line"]]
        if t["type"] == "circuit":
            pts.append(pts[0])
        lines.append(LineString(pts))
        for g in t["gates"]:
            c = np.array(en(g["x"], g["y"]))
            a = math.radians(-g["yaw"])                         # UE yaw (Y south) -> ENU heading
            fwd = np.array([math.cos(a), math.sin(a)])
            gates.append(_rect(c[0], c[1], fwd[0], fwd[1], 2 * PARK_GATE_ALONG_M, g["width"] / 100.0 + 2 * PARK_GATE_SIDE_M))
        s0, g0 = np.array(en(t["start"]["x"], t["start"]["y"])), t["gates"][0]
        c1 = np.array(en(g0["x"], g0["y"]))
        d = c1 - s0
        Ld = float(np.linalg.norm(d))
        fwd = d / Ld if Ld > 0.1 else np.array([math.cos(math.radians(-g0["yaw"])), math.sin(math.radians(-g0["yaw"]))])
        mid = (s0 + c1) / 2
        starts.append(_rect(mid[0], mid[1], fwd[0], fwd[1], Ld + 2 * PARK_START_M, g0["width"] / 100.0 + 2 * PARK_GATE_SIDE_M))
    fr = tracks.get("free_roam")
    spawns = [Point(en(fr["x"], fr["y"]))] if fr else []
    mf = ROOT / f"data/processed/{region}/meshes/manifest.json"
    if mf.exists():
        sp = json.loads(mf.read_text())["spawn"]["ue_cm"]
        spawns.append(Point(en(sp[0], sp[1])))
    ex["line"] = unary_union([l.buffer(PARK_LINE_CLEAR_M, 4) for l in lines]) if lines else Polygon()
    ex["gate"] = unary_union(gates) if gates else Polygon()
    ex["start"] = unary_union(starts) if starts else Polygon()
    ex["spawn"] = unary_union([p.buffer(PARK_SPAWN_M) for p in spawns]) if spawns else Polygon()
    return ex, {"lines": lines, "gates": gates, "starts": starts, "spawns": spawns}


def street_width(cw, ls, at=0.5):
    """Kerb-to-kerb width (m) across a centreline at fraction `at` (None if the ray leaves no carriageway)."""
    from shapely.geometry import LineString
    if ls.length < 1.0:
        return None
    p = ls.interpolate(at, normalized=True)
    q = ls.interpolate(min(ls.length, ls.project(p) + 1.0))
    r = ls.interpolate(max(0.0, ls.project(p) - 1.0))
    t = np.array([q.x - r.x, q.y - r.y])
    t /= np.linalg.norm(t) + 1e-9
    nrm = np.array([-t[1], t[0]])
    tot = 0.0
    for sg in (1, -1):
        ray = LineString([(p.x, p.y), (p.x + sg * nrm[0] * 30, p.y + sg * nrm[1] * 30)])
        seg = ray.intersection(cw)
        if seg.is_empty:
            return None
        parts = [g for g in getattr(seg, "geoms", [seg]) if g.distance(p) < 0.2]
        if not parts:
            return None
        tot += parts[0].length
    return tot


def place_parked(load, region, inside, bldg, stats, furniture=()):
    """-> props of type parked_<body> (see the block comment above). furniture: (x, y) m of the props placed so far
    (poles, lamps, trees, hydrants...): no car stands on one."""
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    from scipy.spatial import cKDTree
    if not PARKED_JSON.exists():
        stats["skipped"] = "no parked_cars.json (run tools/blender/parked_cars.py)"
        return []
    fleet = json.loads(PARKED_JSON.read_text())["types"]
    names = sorted(fleet)
    wts = np.array([fleet[n]["weight"] for n in names], float)
    wts /= wts.sum()
    dims = {n: (fleet[n]["length_m"], fleet[n]["width_m"], 2 * max(abs(fleet[n]["bounds_m"][0][1]), fleet[n]["bounds_m"][1][1]))
            for n in names}

    def pick(key, max_len=99.0):
        ok = [i for i, n in enumerate(names) if dims[n][0] <= max_len] or [min(range(len(names)), key=lambda i: dims[names[i]][0])]
        w = wts[ok] / wts[ok].sum()
        r = rnd(key, "type")
        return names[ok[min(int(np.searchsorted(np.cumsum(w), r)), len(ok) - 1)]]

    feats = [f for f in load("BASEMAP_Roads") if f.get("geometry")]
    roads = unary_union([shape(f["geometry"]).buffer(0) for f in feats if f["properties"].get("TYPE") != "RD-TRAF-ISLAND"])
    islands = unary_union([shape(f["geometry"]).buffer(0) for f in feats if f["properties"].get("TYPE") == "RD-TRAF-ISLAND"] or [Polygon()])
    cw = roads.difference(islands)
    cw_in = prep(cw.buffer(-0.08))
    ex, ev = parking_exclusions(load, region, cw)
    hard = prep(unary_union([ex[k] for k in ("line", "gate", "start", "spawn")]))
    street_ex = prep(unary_union([g for k, g in ex.items() if k not in ("line", "gate", "start", "spawn")]))
    in_bldg = prep(bldg.buffer(-0.1)) if bldg is not None else None
    placed, out = [], []          # footprints (body width) for the car-car overlap test
    grid = {}
    for x, y in furniture:                      # (a pole / trunk: 0.3 m)
        grid.setdefault((int(x // 20), int(y // 20)), []).append(Point(x, y).buffer(0.3, 6))

    def free(poly):
        c = poly.centroid
        k = (int(c.x // 20), int(c.y // 20))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in grid.get((k[0] + dx, k[1] + dy), ()):
                    if q.intersects(poly):
                        return False
        return True

    def add(kind, name, cx, cy, hx, hy, z, src):
        L, W, Wm = dims[name]
        body = _rect(cx, cy, hx, hy, L + 0.1, W)
        wide = _rect(cx, cy, hx, hy, L, Wm)
        if hard.intersects(wide):
            stats[f"{src}_drop_event"] = stats.get(f"{src}_drop_event", 0) + 1
            return False
        if in_bldg is not None and in_bldg.intersects(body):
            stats[f"{src}_drop_building"] = stats.get(f"{src}_drop_building", 0) + 1
            return False
        if not free(body):
            stats[f"{src}_drop_overlap"] = stats.get(f"{src}_drop_overlap", 0) + 1
            return False
        c = body.centroid
        grid.setdefault((int(c.x // 20), int(c.y // 20)), []).append(body)
        out.append({"type": f"parked_{name}", "x": round(cx * 100, 1), "y": round(-cy * 100, 1), "z": z,
                    "yaw": round(math.degrees(math.atan2(-hy, hx)), 2), "scale": 1.0, "src": src})
        stats[f"{src}_placed"] = stats.get(f"{src}_placed", 0) + 1
        return True

    # traffic direction of the nearest centreline (for which way a kerbside car faces)
    cl = [(shape(f["geometry"]), f["properties"]) for f in load("TRANS_Centerlines") if f.get("geometry")]
    cl = [(g if g.geom_type == "LineString" else max(g.geoms, key=lambda q: q.length), p) for g, p in cl]
    cl_tree = STRtree([g for g, _ in cl])

    def nearest_cl(pt, maxd=14.0):
        i = cl_tree.nearest(pt)
        if i is None:
            return None
        g, p = cl[int(i)]
        return (g, p) if g.distance(pt) <= maxd else None

    def heading(pt, t):
        """Unit heading for a kerbside car at pt with kerb tangent t: kerb on its right (two-way), with the flow
        on one-way streets (Direction 1 = digitised direction, -1 = against)."""
        t = np.asarray(t, float)
        nc = nearest_cl(pt)
        if nc is not None:
            g, p = nc
            s = g.project(pt)
            a, b = g.interpolate(max(0.0, s - 1.0)), g.interpolate(min(g.length, s + 1.0))
            d = np.array([b.x - a.x, b.y - a.y])
            d /= np.linalg.norm(d) + 1e-9
            if str(p.get("Direction")) in ("1", "-1"):
                f = d * (1.0 if str(p.get("Direction")) == "1" else -1.0)
                return t if np.dot(t, f) >= 0 else -t
            # two-way: kerb on the right -> the car's right (hy, -hx) points from the centreline toward the car
            q = g.interpolate(s)
            off = np.array([pt.x - q.x, pt.y - q.y])
            right = np.array([t[1], -t[0]])
            return t if np.dot(right, off) > 0 else -t
        return t

    # 1. metered spaces: one car per space (centred, along the space's long axis)
    edge = cw.boundary
    for f in load("TRAFFIC_MeteredParkingSpaces"):
        p = f["properties"]
        if not f.get("geometry") or p.get("Status") in ("Permanently Removed", "Proposed"):
            continue
        g = shape(f["geometry"]).buffer(0)
        if g.is_empty or not inside.contains(g.centroid):
            continue
        key = p.get("GlobalID") or f"{g.centroid.x:.1f},{g.centroid.y:.1f}"
        if rnd(key, "occ") > OCC_METER:
            stats["meter_empty"] = stats.get("meter_empty", 0) + 1
            continue
        rr = list(g.minimum_rotated_rectangle.exterior.coords)[:4]
        e0, e1 = np.subtract(rr[1], rr[0]), np.subtract(rr[2], rr[1])
        long_e = e0 if np.linalg.norm(e0) >= np.linalg.norm(e1) else e1
        Ls = float(np.linalg.norm(long_e))
        if Ls < 4.6:
            stats["meter_too_short"] = stats.get("meter_too_short", 0) + 1
            continue
        t = long_e / Ls
        c = g.centroid
        name = pick(key, Ls - 0.25)
        L, W, _ = dims[name]
        # kerb side: shift so the kerb-side flank sits PARK_KERB_GAP off the kerb (space centre if no kerb within 3 m)
        q = nearest_points(edge, c)[0]
        dk = c.distance(q)
        cx, cy = c.x, c.y
        if dk < 3.0:
            nvec = np.array([c.x - q.x, c.y - q.y]) / (dk + 1e-9)
            nvec = np.array([-t[1], t[0]]) * np.sign(np.dot(np.array([-t[1], t[0]]), nvec) or 1.0)
            cx, cy = q.x + nvec[0] * (PARK_KERB_GAP + W / 2), q.y + nvec[1] * (PARK_KERB_GAP + W / 2)
            # keep the along-kerb position of the space centre
            along = np.dot([c.x - cx, c.y - cy], t)
            cx, cy = cx + t[0] * along, cy + t[1] * along
        jit = (rnd(key, "jit") - 0.5) * max(0.0, Ls - L - 0.3)
        cx, cy = cx + t[0] * jit, cy + t[1] * jit
        h = heading(Point(cx, cy), t)
        if not cw_in.contains(_rect(cx, cy, h[0], h[1], L - 0.1, W - 0.1)):
            stats["meter_off_carriageway"] = stats.get("meter_off_carriageway", 0) + 1
            continue
        add("meter", name, cx, cy, h[0], h[1], 0.0, "meter")
    # 2. kerbside walk: marked spaces + local streets + minor arterials
    meter_zone = prep(unary_union([shape(f["geometry"]).buffer(8.0) for f in load("TRAFFIC_MeteredParkingSpaces")
                                   if f.get("geometry") and f["properties"].get("Status") not in ("Permanently Removed", "Proposed")]))
    marks = unary_union([shape(f["geometry"]).buffer(6.0) for f in load("TRAFFIC_PavementMarkings")
                         if f.get("geometry") and f["properties"].get("TYPE") == "PM-PARKING"])
    marked = prep(marks.intersection(roads))
    rings = []
    for poly in getattr(cw, "geoms", [cw]):
        rings += [poly.exterior] + list(poly.interiors)
    seg_width = {}
    for ring in rings:
        ring = LineString(ring.coords)
        Lr = ring.length
        if Lr < 12.0:
            continue
        s0 = 0.0
        while s0 < Lr - 5.0:
            key = f"{ring.coords[0][0]:.1f},{ring.coords[0][1]:.1f}:{s0:.1f}"
            name = pick(key)
            L, W, _ = dims[name]
            sc = s0 + L / 2
            a, b = ring.interpolate(sc - 2.5), ring.interpolate(sc + 2.5)
            t = np.array([b.x - a.x, b.y - a.y])
            nt = np.linalg.norm(t)
            if nt < 4.0:                         # bends: no kerb straight enough here
                s0 += 0.5
                continue
            t /= nt
            a2, b2 = ring.interpolate(sc - 4.0), ring.interpolate(sc + 4.0)
            m0 = ring.interpolate(sc)
            dev = LineString([(a2.x, a2.y), (b2.x, b2.y)]).distance(m0)
            if dev > 0.25:
                s0 += 0.5
                continue
            nrm = np.array([-t[1], t[0]])
            if not cw.contains(Point(m0.x + nrm[0] * 1.2, m0.y + nrm[1] * 1.2)):
                nrm = -nrm
            off = PARK_KERB_GAP + W / 2
            cx, cy = m0.x + nrm[0] * off, m0.y + nrm[1] * off
            c = Point(cx, cy)
            if not inside.contains(c) or meter_zone.contains(c):
                s0 += 1.0
                continue
            # permission
            src = None
            if marked.contains(c):
                src, occ = "marked", OCC_MARKED
            else:
                nc = nearest_cl(c)
                if nc is not None:
                    g, p = nc
                    st = p.get("Street") or ""
                    gid = p.get("ID") or st
                    if gid not in seg_width:
                        seg_width[gid] = street_width(cw, g) or 0.0
                    w = seg_width[gid]
                    restricted = p.get("Restriction") == "T" or st.endswith((" Aly", " Pl", " Way", " Ter", " Ct")) or st in NO_PARK_STREETS
                    gx, gy = g.coords[-1][0] - g.coords[0][0], g.coords[-1][1] - g.coords[0][1]
                    side = 1 if gx * (cy - g.coords[0][1]) - gy * (cx - g.coords[0][0]) > 0 else -1
                    if restricted:
                        pass
                    elif p.get("MajorRoad") is None and (w >= 9.0 or (w >= 7.0 and side == (1 if rnd(gid, "side") < 0.5 else -1))):
                        src, occ = "resid", OCC_RESID * (0.75 + 0.5 * rnd(gid, "block"))
                    elif p.get("MajorRoad") == 2 and w >= 11.5:
                        src, occ = "arterial", OCC_RESID * (0.7 + 0.5 * rnd(gid, "block"))
            if src is None:
                s0 += 1.0
                continue
            fp = _rect(cx, cy, t[0], t[1], L + 0.6, W)
            if not cw_in.contains(_rect(cx, cy, t[0], t[1], L - 0.1, W - 0.05)) or street_ex.intersects(fp):
                s0 += 0.5
                continue
            gap = 0.6 + 1.4 * rnd(key, "gap")
            if rnd(key, "occ") < occ:
                h = heading(c, t)
                add(src, name, cx, cy, h[0], h[1], 0.0, src)
            else:
                stats[f"{src}_empty"] = stats.get(f"{src}_empty", 0) + 1
            s0 += L + gap
    # 3. surface lots: between adjacent parallel stall lines
    lots = unary_union([shape(f["geometry"]).buffer(0) for f in load("BASEMAP_ParkingLots") if f.get("geometry")])
    lots_prep = prep(lots.buffer(0.6))
    lot_list = list(getattr(lots, "geoms", [lots]))
    lot_tree = STRtree(lot_list)
    segs = []
    for f in load("TRAFFIC_PavementMarkings"):
        if not f.get("geometry") or f["properties"].get("TYPE") != "PM-PARKING-OS":
            continue
        g = shape(f["geometry"])
        for ls in getattr(g, "geoms", [g]):
            c = list(ls.coords)
            for a, b in zip(c[:-1], c[1:]):
                d = np.subtract(b, a)
                ln = float(np.linalg.norm(d))
                if 3.6 <= ln <= 6.6:
                    segs.append((np.array(a), np.array(b)))
                elif 8.8 <= ln <= 13.0:          # one line for two stalls back to back
                    m = (np.array(a) + np.array(b)) / 2
                    segs += [(np.array(a), m), (m, np.array(b))]
    if segs:
        mids = np.array([(a + b) / 2 for a, b in segs])
        dirs = np.array([(b - a) / np.linalg.norm(b - a) for a, b in segs])
        kd = cKDTree(mids)
        used = set()
        for i in range(len(segs)):
            m, d = mids[i], dirs[i]
            perp = np.array([-d[1], d[0]])
            best = None
            for j in kd.query_ball_point(m, 3.6):
                if j == i or abs(d[0] * dirs[j][1] - d[1] * dirs[j][0]) > 0.17:
                    continue
                v = mids[j] - m
                off, along = float(np.dot(v, perp)), float(np.dot(v, d))
                if 2.2 <= off <= 3.4 and abs(along) < 1.2 and (best is None or off < best[0]):
                    best = (off, j)
            if best is None:
                continue
            j = best[1]
            c = (m + mids[j]) / 2
            key = f"lot:{c[0]:.1f},{c[1]:.1f}"
            if key in used:
                continue
            used.add(key)
            pt = Point(c)
            if not inside.contains(pt) or not lots_prep.contains(pt):
                continue
            li = lot_tree.nearest(pt)
            lk = f"{lot_list[int(li)].centroid.x:.0f},{lot_list[int(li)].centroid.y:.0f}" if li is not None else key
            occ = OCC_LOT[0] + (OCC_LOT[1] - OCC_LOT[0]) * rnd(lk, "lotocc")
            if rnd(key, "occ") > occ:
                stats["lot_empty"] = stats.get("lot_empty", 0) + 1
                continue
            ln = float(np.linalg.norm(segs[i][1] - segs[i][0]))
            name = pick(key, ln + 0.7)
            h = d if rnd(key, "nose") < 0.5 else -d
            sh = (rnd(key, "jit") - 0.5) * 0.3
            add("lot", name, c[0] + h[0] * sh, c[1] + h[1] * sh, h[0], h[1], 0.0 if roads.contains(pt) else CURB_H * 100, "lot")
    stats["total"] = len(out)
    return out


def main(region):
    frame = Frame()
    rdir = ROOT / "data/processed" / region
    region_poly = region_polygon(region, frame)   # = the lon/lat bbox unless the region has a "playable" block
    load = lambda l: json.loads((rdir / f"{l}.geojson").read_text())["features"]

    roads = [shape(f["geometry"]).buffer(0) for f in load("BASEMAP_Roads") if f["properties"].get("TYPE") != "RD-TRAF-ISLAND"]
    water = unary_union([shape(f["geometry"]).buffer(0) for f in load("HYDRO_WaterBodies")])
    # the same 3D models build_meshes.py renders (bridges / overpasses / the Cambridge St underpass are not built;
    # "Cambridge Housing" is not a bridge)
    skip_poi = tuple(CONFIG["regions"][region].get("buildings", {}).get("skip_poi", ()))
    models = [b for b in buildings3d.load(camb3d_tiles(region), region_poly, frame)
              if not (skip_poi and any(k in b.poi_type.lower().replace("cambridge", "") for k in skip_poi))]

    skip_bb = CONFIG["regions"][region].get("buildings", {}).get("drop_road_walls_skip_bbox_lonlat")   # = Stage A
    stage_a = prep(transform(lambda x, y, z=None: frame.to_en(x, y), box(*skip_bb))) if skip_bb else prep(Polygon())

    def model_foot(b):
        # walls (the City 3D "Wall" models: garden walls, the Harvard Yard fence) block by their own footprint: the
        # convex hull of a ring of wall is the whole enclosure (the Yard fence's hull is 0.73 km2 and removed 166 trees)
        # (outside the Stage A bbox only: Stage A keeps its approved, perf-gated tree set)
        is_wall = b.poi_type.strip().lower() == "wall" and not stage_a.contains(Point(*b.vertices[:, :2].mean(0)))
        if not is_wall and (TREE_BLOCK == "hull" or (TREE_BLOCK == "harvard" and b.poi_type.strip().lower() != "harvard university")):
            return MultiPoint(b.vertices[:, :2]).convex_hull
        tri = b.vertices[b.faces][:, :, :2]
        u, v = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        keep = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) > 2e-3
        return unary_union([Polygon(t) for t in tri[keep]])
    blocked = prep(unary_union(roads + [water] + [model_foot(b) for b in models]
                               + [shape(f["geometry"]).buffer(0) for f in load("BASEMAP_Buildings")]))
    inside = prep(region_poly.buffer(-2.0))
    snap, carriageway = curb_snapper(load)

    trees, skipped = [], 0
    for f in load("ENVIRONMENTAL_StreetTrees"):
        p = f["properties"]
        live = p.get("SiteType") == "Tree" or (p.get("SiteType") is None and p.get("Ownership") in ("MIT", "Other"))
        if not live or not f.get("geometry"):
            continue
        pt = shape(f["geometry"])
        if not inside.contains(pt) or blocked.contains(pt):
            skipped += 1
            continue
        dbh = p.get("diameter") or 8.0
        h = min(max(4.0 + 0.55 * dbh, 4.0), 22.0) * (0.9 + 0.2 * rnd(p.get("GlobalID"), "h"))
        trees.append({"type": "tree", "x": pt.x * 100, "y": -pt.y * 100, "z": CURB_H * 100,
                      "yaw": 360.0 * rnd(p.get("GlobalID"), "yaw"), "h": h,
                      "genus": p.get("Genus") or "", "id": p.get("GlobalID") or f"{pt.x:.1f},{pt.y:.1f}"})
    tv = TreeVariants()
    resolved = {}
    for t in trees:
        how = tv.resolve(t["genus"])[1]
        if how != "map":
            g = (t["genus"] or "").strip() or "(none)"
            resolved.setdefault(how, {}).setdefault(g, 0)
            resolved[how][g] += 1
    trees = [t for t in trees if tv.resolve(t["genus"])[0] is not None]   # before thinning: shrubs don't shadow trees
    kept = thin_trees(trees)
    thinned = len(trees) - len(kept)
    props, tree_stats = [], {}
    for t in kept:
        vs, _ = tv.assign(t)
        v, s = vs
        props.append({**t, "type": f"tree_{v}", "scale": s})
        st = tree_stats.setdefault(v, {"n": 0, "scale": [9.0, 0.0], "h": [99.0, 0.0], "clamped": 0})
        st["n"] += 1
        st["scale"] = [round(min(st["scale"][0], s), 2), round(max(st["scale"][1], s), 2)]
        st["h"] = [round(min(st["h"][0], t["h"]), 1), round(max(st["h"][1], t["h"]), 1)]
        st["clamped"] += int(abs(s - t["h"] / tv.height[v]) > 1e-6)

    lamps_moved = 0
    for f in load("INFRA_StreetLights"):
        p = f["properties"]
        if not f.get("geometry"):
            continue
        pt = shape(f["geometry"])
        if not inside.contains(pt):
            continue
        kind = "cobra" if (p.get("Description") or "").lower().startswith("cobra") else "lamp"
        pt, moved = snap(pt)
        lamps_moved += moved
        if pt is None:
            continue
        # face the nearest road (cobra arm / lantern bracket point over the street)
        near = min(roads, key=lambda r: r.distance(pt)) if roads else None
        yaw = 0.0
        if near is not None:
            from shapely.ops import nearest_points
            q = nearest_points(near, pt)[0]
            yaw = math.degrees(math.atan2(-(q.y - pt.y), q.x - pt.x))   # UE yaw (Y = south)
        z = 0.0 if any(r.contains(pt) for r in roads) else CURB_H * 100
        props.append({"type": kind, "x": pt.x * 100, "y": -pt.y * 100, "z": z, "yaw": yaw, "scale": 1.0})

    furniture_stats = {}
    furniture_stats["streetlight_moved_to_curb"] = lamps_moved
    bfoot = building_footprints(models, load)
    props += place_furniture(load, roads, inside, bfoot, furniture_stats, snap)
    parked_stats = {}
    props += place_parked(load, region, inside, bfoot, parked_stats, [(p["x"] / 100.0, -p["y"] / 100.0) for p in props])
    # validation: nothing may stand on the carriageway (expected 0; parked cars do, by design)
    from shapely.geometry import Point as P
    on_cw = {}
    for pr in props:
        if not pr["type"].startswith("parked_") and carriageway.contains(P(pr["x"] / 100.0, -pr["y"] / 100.0)):
            on_cw[pr["type"]] = on_cw.get(pr["type"], 0) + 1

    out = rdir / "props"
    out.mkdir(exist_ok=True)
    (out / "props.json").write_text(json.dumps(props))
    write_pole_meshes(ROOT / "data/processed/common/props")
    write_furniture_meshes(ROOT / "data/processed/common/props")
    counts = {}
    for pr in props:
        counts[pr["type"]] = counts.get(pr["type"], 0) + 1
    print(json.dumps({"counts": counts, "props_on_carriageway": on_cw, "furniture_dropped": furniture_stats,
                      "parked": dict(sorted(parked_stats.items())), "skipped_trees": skipped, "thinned_trees": thinned,
                      "trees": sum(st["n"] for st in tree_stats.values()),
                      "tree_variants": dict(sorted(tree_stats.items())),
                      "genus_not_in_map_live_trees": resolved}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mit_core")
