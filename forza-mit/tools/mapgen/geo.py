"""World frame: WGS84 lon/lat -> local East/North meters around a fixed origin.

Uses an exact ECEF -> ENU rotation (same tangent plane CesiumGeoreference uses),
so generated meshes line up with Cesium tiles if we ever add them as a backdrop.
Heights are NOT taken from ENU 'up': we keep NAVD88 orthometric height so the
ground stays level (earth curvature would drop the map edges ~0.3 m at 2 km).
"""
import json
from pathlib import Path

import numpy as np

CONFIG = json.loads((Path(__file__).parent / "config.json").read_text())

# WGS84 ellipsoid
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)


def _ecef(lon_deg, lat_deg, h=0.0):
    lon, lat = np.radians(lon_deg), np.radians(lat_deg)
    n = _A / np.sqrt(1 - _E2 * np.sin(lat) ** 2)
    x = (n + h) * np.cos(lat) * np.cos(lon)
    y = (n + h) * np.cos(lat) * np.sin(lon)
    z = (n * (1 - _E2) + h) * np.sin(lat)
    return np.stack([x, y, z], axis=-1)


class Frame:
    def __init__(self, cfg=CONFIG["frame"]):
        self.lon0, self.lat0 = cfg["origin_lon"], cfg["origin_lat"]
        self.h0 = cfg["origin_height_navd88_m"]
        self.o = _ecef(self.lon0, self.lat0)
        lon, lat = np.radians(self.lon0), np.radians(self.lat0)
        # rows: east, north, up unit vectors in ECEF
        self.R = np.array([
            [-np.sin(lon), np.cos(lon), 0.0],
            [-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)],
            [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)],
        ])

    def to_en(self, lon, lat):
        """lon/lat arrays (deg) -> (east_m, north_m) arrays."""
        enu = (_ecef(np.asarray(lon), np.asarray(lat)) - self.o) @ self.R.T
        return enu[..., 0], enu[..., 1]

    def height_m(self, navd88_ft):
        return navd88_ft * CONFIG["source_units"]["height_to_m"] - self.h0

    @staticmethod
    def en_to_ue_cm(e, n, z):
        """East/North/Up meters -> UE (X=E, Y=-N, Z=Up) centimeters."""
        return np.stack([e * 100.0, -n * 100.0, z * 100.0], axis=-1)


# ---------------------------------------------------------------- per-region config + playable polygon
ROOT = Path(__file__).resolve().parents[2]


def region_cfg(region, key, default=None):
    """CONFIG["regions"][region][key], falling back to the top-level CONFIG[key], then default."""
    spec = CONFIG["regions"][region]
    if key in spec:
        return spec[key]
    return CONFIG.get(key, default)


def camb3d_tiles(region):
    """City of Cambridge 3D model tiles a region needs (play area + context ring)."""
    return list(region_cfg(region, "camb3d_tiles"))


def boston_tiles(region):
    """City of Boston 3D model tiles for the region's backdrop."""
    spec = CONFIG["regions"][region]
    return list(spec["boston_tiles"]) if "boston_tiles" in spec else list(CONFIG.get("boston", {}).get("tiles", []))


def all_tiles(kind="camb3d"):
    """Union of the tile lists of every region (fetch.sh / fetch_boston.sh download all of them)."""
    get = camb3d_tiles if kind == "camb3d" else boston_tiles
    return sorted({t for r in CONFIG["regions"] for t in get(r)})


def lonlat_box_en(bbox, frame=None):
    from shapely.geometry import box
    from shapely.ops import transform
    frame = frame or Frame()
    return transform(lambda x, y, z=None: frame.to_en(x, y), box(*bbox))


def _raw_union_en(path, frame):
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    gs = []
    for f in json.loads(Path(path).read_text())["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        gs.append(transform(lambda x, y, z=None: frame.to_en(x, y), g).buffer(0))
    return unary_union(gs)


def region_polygon(region, frame=None):
    """World-frame (East/North m) playable polygon of a region.

    Without a "playable" block it is the lon/lat bbox (Stage A behaviour). With one:
        bbox ∩ city.buffer(city_buffer_m) − (city land boundary, i.e. not in the river).buffer(inset)
    keeping the part that contains the spawn. City = raw BOUNDARY_CityBoundary (fetch.sh),
    water = raw HYDRO_WaterBodies. Cached in data/processed/<region>/region.geojson together with
    its parameters (recomputed when they change)."""
    from shapely.geometry import Point, mapping, shape
    frame = frame or Frame()
    spec = CONFIG["regions"][region]
    bb = lonlat_box_en(spec["bbox_lonlat"], frame)
    pl = spec.get("playable")
    if not pl or not pl.get("clip_to_city"):
        return bb
    params = {"bbox_lonlat": spec["bbox_lonlat"], "city_buffer_m": pl["city_buffer_m"],
              "land_boundary_inset_m": pl["land_boundary_inset_m"], "spawn_near_en": spec["spawn"]["start_near_en"]}
    cache = ROOT / "data/processed" / region / "region.geojson"
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("properties", {}).get("params") == params:
            return shape(c["geometry"])
    raw = ROOT / "data/raw/cambridge_gis"
    city = _raw_union_en(raw / "BOUNDARY_CityBoundary.geojson", frame)
    water = _raw_union_en(raw / "HYDRO_WaterBodies.geojson", frame)
    outline = city.boundary   # all rings of all parts
    land_line = outline.difference(water.buffer(5.0))
    reg = bb.intersection(city.buffer(pl["city_buffer_m"])).difference(land_line.buffer(pl["land_boundary_inset_m"]))
    spawn = Point(*spec["spawn"]["start_near_en"])
    parts = [g for g in getattr(reg, "geoms", [reg]) if g.geom_type == "Polygon"]
    main = next(g for g in parts if g.buffer(1.0).contains(spawn))
    dropped = sum(g.area for g in parts if g is not main)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"type": "Feature", "properties": {
        "params": params, "rule": region_polygon.__doc__.split("\n\n")[1].strip(),
        "area_m2": round(main.area), "dropped_parts_m2": round(dropped), "bounds_en_m": [round(v, 1) for v in main.bounds],
        "vertices": len(main.exterior.coords), "holes": len(main.interiors)}, "geometry": mapping(main)}))
    return main


def city_polygon(frame=None):
    """City of Cambridge boundary (raw BOUNDARY_CityBoundary, fetch.sh) in the world frame."""
    return _raw_union_en(ROOT / "data/raw/cambridge_gis/BOUNDARY_CityBoundary.geojson", frame or Frame())
