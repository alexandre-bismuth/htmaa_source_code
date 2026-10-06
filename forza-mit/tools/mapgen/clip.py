"""Step 1: clip raw Cambridge GIS layers to a region and reproject to the world frame.

Usage:  uv run clip.py mit_core
Output: data/processed/<region>/<layer>.geojson  (coordinates = local East/North meters)
        data/processed/<region>/preview.png
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely.geometry import (GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Polygon, box, mapping,
                              shape)
from shapely.ops import transform
from shapely.prepared import prep
from shapely.validation import make_valid

from geo import CONFIG, Frame, region_polygon

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/cambridge_gis"

STYLE = {  # layer -> (facecolor, edgecolor, linewidth, zorder)
    "BASEMAP_Roads": ("#4a4a4a", None, 0, 2),
    "BASEMAP_Sidewalks": ("#bdbdbd", None, 0, 1),
    "BASEMAP_Plazas": ("#d6d0c4", None, 0, 1),
    "BASEMAP_Driveways": ("#7a7a7a", None, 0, 1),
    "BASEMAP_Bridges": ("#8d6e63", None, 0, 3),
    "BASEMAP_Vegetation": ("#a5d6a7", None, 0, 0),
    "HYDRO_WaterBodies": ("#90caf9", None, 0, 0),
    "BASEMAP_Buildings": ("#c97b63", "#7a3f2c", 0.3, 4),
    "BASEMAP_Curbs": (None, "#ffeb3b", 0.4, 5),
    "BASEMAP_Walls": (None, "#6d4c41", 0.5, 5),
    "TRANS_Centerlines": (None, "#ffffff", 0.5, 6),
}


def load_shape(geom):
    """shapely.shape(), but drops degenerate rings (<4 coords) present in the source data."""
    t = geom["type"]
    if t == "Polygon":
        rings = [r for r in geom["coordinates"] if len(r) >= 4]
        return Polygon(rings[0], rings[1:]) if rings else None
    if t == "MultiPolygon":
        polys = [load_shape({"type": "Polygon", "coordinates": p}) for p in geom["coordinates"]]
        polys = [p for p in polys if p is not None]
        return MultiPolygon(polys) if polys else None
    return shape(geom)


_DIM = {"Point": 0, "MultiPoint": 0, "LineString": 1, "LinearRing": 1, "MultiLineString": 1, "Polygon": 2, "MultiPolygon": 2}
_MULTI = {0: MultiPoint, 1: MultiLineString, 2: MultiPolygon}


def same_dim(g, dim):
    """Parts of g with the given dimension (drops the stray points / lines a polygon clip can produce)."""
    if g.is_empty:
        return g
    parts = [q for q in getattr(g, "geoms", [g]) for q in getattr(q, "geoms", [q]) if _DIM.get(q.geom_type) == dim and not q.is_empty]
    if not parts:
        return GeometryCollection()
    return parts[0] if len(parts) == 1 else _MULTI[dim](parts)


def main(region, context=False):
    """context=True clips the wider backdrop box into data/processed/<region>/context/."""
    frame = Frame()
    lon0, lat0, lon1, lat1 = CONFIG["regions"][region]["context_bbox_lonlat" if context else "bbox_lonlat"]
    clip_ll = box(lon0, lat0, lon1, lat1)
    to_local = lambda x, y, z=None: frame.to_en(x, y)
    out = ROOT / "data/processed" / region / ("context" if context else "")
    # regions with a "playable" block (city-clipped polygon, geo.region_polygon) clip the play layers to it,
    # so nothing beyond the invisible walls (e.g. Somerville-edge streets tracks.py could route on) remains
    rpoly = None if context or not CONFIG["regions"][region].get("playable") else region_polygon(region, frame)
    rprep = prep(rpoly) if rpoly is not None else None
    out.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 11), dpi=130)
    ax.set_facecolor("#e8e8e0")
    for layer in CONFIG["layers"]:
        src = RAW / f"{layer}.geojson"
        if not src.exists():
            print(f"  skip {layer} (not downloaded)")
            continue
        feats = []
        for f in json.loads(src.read_text())["features"]:
            g = load_shape(f["geometry"])
            if g is None:
                continue
            if not g.is_valid:
                g = g.buffer(0)
            if not g.intersects(clip_ll):
                continue
            g = transform(to_local, g.intersection(clip_ll))
            if rpoly is not None and not g.is_empty and not rprep.contains(g):
                dim = _DIM.get(g.geom_type)
                # the reprojected bbox clip can be invalid (the big road-network polygon is); GEOS then
                # intersects it wrongly and fills block holes (whole blocks become "road"): make it valid first.
                # Bbox-only regions keep writing the raw geometry; build_meshes' load() buffer(0)s it.
                if not g.is_valid:
                    g = make_valid(g)
                g = g.intersection(rpoly)
                if dim is not None:
                    g = same_dim(g, dim)
            if g.is_empty:
                continue
            feats.append({"type": "Feature", "properties": f["properties"], "geometry": mapping(g)})
        (out / f"{layer}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        print(f"  {layer:28s} {len(feats):5d} features")

        fc, ec, lw, z = STYLE.get(layer, (None, "#000", 0.3, 1))
        for f in feats:
            g = load_shape(f["geometry"])
            if g is None:
                continue
            for part in getattr(g, "geoms", [g]):
                if part.geom_type == "Polygon":
                    # compound path so holes (city blocks inside road polygons) stay empty
                    path = MplPath.make_compound_path(*[MplPath(list(r.coords)) for r in [part.exterior, *part.interiors]])
                    ax.add_patch(PathPatch(path, fc=fc or "none", ec=ec or "none", lw=lw, zorder=z))
                elif part.geom_type == "LineString":
                    x, y = part.xy
                    ax.plot(x, y, color=ec, lw=lw, zorder=z)

    # label major streets once each
    cl = out / "TRANS_Centerlines.geojson"
    if cl.exists():
        seen = set()
        for f in json.loads(cl.read_text())["features"]:
            name = f["properties"].get("Label")
            g = load_shape(f["geometry"])
            if g is None:
                continue
            if name and name not in seen and g.length > 120:
                p = g.interpolate(0.5, normalized=True)
                ax.text(p.x, p.y, name, fontsize=7, zorder=10, ha="center",
                        bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
                seen.add(name)

    if rpoly is not None:
        x, y = rpoly.exterior.xy
        ax.plot(x, y, color="#d50000", lw=1.0, zorder=11)
    ax.set_aspect("equal")
    ax.set_title(f"{region}: world-frame meters (origin {frame.lat0}, {frame.lon0})")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.grid(True, lw=0.3, alpha=0.5)
    fig.tight_layout()
    fig.savefig(out / "preview.png")
    print(f"wrote {out}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "mit_core", context="--context" in sys.argv)
