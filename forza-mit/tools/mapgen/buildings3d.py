"""City of Cambridge 3D building models (CyberCity3D photogrammetry, 2023 update) -> world frame.

Source: https://www.cambridgema.gov/GIS/3D/3ddata (tiled OBJ, one OBJ per building, public data).
OBJ coordinates are MA State Plane feet (EPSG:2249) minus a fixed offset, heights NAVD88 feet.
Each building is seated so its own ground elevation is at z = 0 (our world is flat in v1).
"""
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pyproj import Transformer

from geo import Frame

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/camb3d"
URL = "https://cambmagisdata.blob.core.windows.net/camb3d/Camb3D_{tile}_2023_Bulding_Models_OBJ.zip"
OFFSET_X_FT, OFFSET_Y_FT = 731100.0, 2902900.0     # from the dataset readme
FT = 0.3048006096                                   # US survey foot

_SP_TO_LL = Transformer.from_crs("EPSG:2249", "EPSG:4326", always_xy=True)


@dataclass
class Building3D:
    model_id: str
    building_id: str
    name: str
    height_m: float
    model_date: str
    poi_type: str
    vertices: np.ndarray = field(repr=False)   # (N, 3) world-frame E, N, U meters (ground at 0)
    faces: np.ndarray = field(repr=False)      # (M, 3) triangle indices


def catalog(tiles):
    rows = []
    for t in tiles:
        p = RAW / t / "catalog" / "catalog.csv"
        rows += list(csv.DictReader(open(p, encoding="utf-8-sig")))
    return rows


def _read_obj(path):
    verts, faces = [], []
    for line in open(path):
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("f "):
            idx = [int(tok.split("/")[0]) for tok in line.split()[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):          # fan-triangulate polygons
                faces.append([idx[0], idx[k], idx[k + 1]])
    return np.asarray(verts, float), np.asarray(faces, int).reshape(-1, 3)


def load(tiles, region_poly_en, frame=None):
    """All building models whose catalog centre falls inside the region polygon (world-frame EN)."""
    from shapely.geometry import Point
    frame = frame or Frame()
    out = []
    for row in catalog(tiles):
        e, n = frame.to_en(float(row["Center_Long"]), float(row["Center_Lat"]))
        if not region_poly_en.contains(Point(float(e), float(n))):
            continue
        # sorted + no spaces: deterministic, and never an iCloud conflict copy ("<id> 2.obj")
        obj = next((p for p in sorted((RAW / row["Tile"] / "models" / f"{row['Model_ID']}_OBJ").glob("*.obj"))
                    if " " not in p.name), None)
        if obj is None:
            continue
        v, f = _read_obj(obj)
        if len(f) == 0:
            continue
        lon, lat = _SP_TO_LL.transform(v[:, 0] + OFFSET_X_FT, v[:, 1] + OFFSET_Y_FT)
        E, N = frame.to_en(lon, lat)
        ground_ft = float(row["Ground_Elev_Ft"] or v[:, 2].min())
        U = (v[:, 2] - ground_ft) * FT
        out.append(Building3D(
            model_id=row["Model_ID"], building_id=row["Building_ID"] or "", name=(row["Name"] or "").strip(),
            height_m=float(row["Height_Ft"] or 0) * FT, model_date=row["Model_Date"] or "",
            poi_type=(row["POI_Type"] or "").strip(),
            vertices=np.column_stack([E, N, U]), faces=f))
    return out


BOS_RAW = ROOT / "data/raw/bos3d"   # tools/mapgen/fetch_boston.sh


def load_boston(tiles, region_poly_en, frame=None, keep=None):
    """City of Boston Planning Department 3D Smart Model buildings (same State Plane grid and offset as
    Cambridge) whose catalog centre is inside the region: existing buildings only (Status Current /
    Complete, StructType Building; walls, docks, bridges and demolished or planned models are skipped).
    keep(e, n, height_m) can drop more (e.g. small buildings far from the river)."""
    from shapely.geometry import Point
    frame = frame or Frame()
    out = []
    for t in tiles:
        for row in csv.DictReader(open(BOS_RAW / t / "catalog.csv", encoding="utf-8-sig")):
            if row["StructType"] != "Building" or row["Status"] not in ("Current", "Complete"):
                continue
            e, n = frame.to_en(float(row["Centr_Lon"]), float(row["Centr_Lat"]))
            height = float(row["Height_Ft"] or 0) * FT
            if not region_poly_en.contains(Point(float(e), float(n))) or (keep and not keep(float(e), float(n), height)):
                continue
            obj = BOS_RAW / t / "models" / f"{row['Model_ID']}_OBJ" / f"{row['Model_ID']}.obj"
            if not obj.exists():
                continue
            v, f = _read_obj(obj)
            if len(f) == 0:
                continue
            lon, lat = _SP_TO_LL.transform(v[:, 0] + OFFSET_X_FT, v[:, 1] + OFFSET_Y_FT)
            E, N = frame.to_en(lon, lat)
            ground_ft = float(row["Gnd_El_Ft"]) if row["Gnd_El_Ft"] else v[:, 2].min()
            U = (v[:, 2] - ground_ft) * FT
            out.append(Building3D(
                model_id=row["Model_ID"], building_id="", name=(row["Name"] or "").strip(), height_m=height,
                model_date=row.get("Model_Dt") or "", poi_type=(row.get("StructUse") or "").strip(),
                vertices=np.column_stack([E, N, U]), faces=f))
    return out


if __name__ == "__main__":
    import sys
    from shapely.geometry import box
    from shapely.ops import transform
    from geo import camb3d_tiles, region_polygon
    region = sys.argv[1] if len(sys.argv) > 1 else "mit_core"
    fr = Frame()
    rp = region_polygon(region, fr)
    bs = load(camb3d_tiles(region), rp, fr)
    tris = sum(len(b.faces) for b in bs)
    print(f"{len(bs)} models, {tris} triangles")
    for b in sorted(bs, key=lambda b: -b.height_m)[:12]:
        print(f"  {b.building_id:10s} {b.name[:40]:40s} {b.height_m:5.1f} m  z=[{b.vertices[:,2].min():.1f},{b.vertices[:,2].max():.1f}]  {b.poi_type}")
