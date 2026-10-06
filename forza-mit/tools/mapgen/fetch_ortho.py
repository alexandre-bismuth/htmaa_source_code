"""Fetch MassGIS 2023 orthoimagery (public domain, 15 cm native) for a region and resample it
into the world frame (axis-aligned East/North), so materials can map it from world position.

Usage:  uv run fetch_ortho.py mit_core [--context]
Output: data/processed/<region>/ortho/ortho.jpg  (SIZE x SIZE, north up, east right)
        data/processed/<region>/ortho/ortho.json (world-frame extent, for materials)

Tiles are cached in data/raw/ortho2023/z<Z>/<x>_<y>.jpg.
"""
import io
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform

from geo import CONFIG, Frame

ROOT = Path(__file__).resolve().parents[2]
URL = "https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services/orthos2023/MapServer/tile/{z}/{y}/{x}"
# Defaults (Stage A); a region can override them with "ortho": {"play": {"z", "size_px"}, "ctx": {...}}.
# z20 = 0.149 m/px in web mercator = ~0.11 m on the ground at 42.36 N (native is 0.15 m); z19 = 0.22 m.
ORTHO_DEFAULT = {"play": {"z": 20, "size_px": 8192}, "ctx": {"z": 18, "size_px": 8192}}
MARGIN_M = 10.0   # extra coverage around the region


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    y = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2.0 * n
    return x, y


def fetch(z, x, y, cache):
    p = cache / f"{x}_{y}.jpg"
    if p.exists() and p.stat().st_size > 0:
        return
    for attempt in range(4):
        try:
            req = Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "forza-MIT student project (HTMAA)"})
            data = urlopen(req, timeout=30).read()
            p.write_bytes(data)
            return
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    print(f"  failed tile {x},{y}")


def main(region, context=False):
    """context=True: the wider backdrop ring at lower resolution -> ortho_ctx.jpg/json."""
    frame = Frame()
    key = "context_bbox_lonlat" if context else "bbox_lonlat"
    ocfg = {**ORTHO_DEFAULT, **CONFIG["regions"][region].get("ortho", {})}["ctx" if context else "play"]
    Z, SIZE = int(ocfg["z"]), int(ocfg["size_px"])
    lon0, lat0, lon1, lat1 = CONFIG["regions"][region][key]
    rpoly = transform(lambda x, y, z=None: frame.to_en(x, y), box(lon0, lat0, lon1, lat1))
    e0, n0, e1, n1 = rpoly.bounds
    e0, n0, e1, n1 = e0 - MARGIN_M, n0 - MARGIN_M, e1 + MARGIN_M, n1 + MARGIN_M
    side = max(e1 - e0, n1 - n0)       # square texture, square pixels
    e1, n0 = e0 + side, n1 - side
    res = side / SIZE

    # tiles needed (pad by one; region bbox in lon/lat is slightly smaller than the EN square)
    pad = 0.0004
    tx0, ty0 = tile_xy(lon0 - pad, lat1 + pad, Z)
    tx1, ty1 = tile_xy(lon1 + pad, lat0 - pad, Z)
    xs, ys = range(int(tx0), int(tx1) + 1), range(int(ty0), int(ty1) + 1)
    cache = ROOT / f"data/raw/ortho2023/z{Z}"
    cache.mkdir(parents=True, exist_ok=True)
    jobs = [(x, y) for x in xs for y in ys]
    print(f"{len(jobs)} tiles at z{Z}; output {SIZE}px at {res:.3f} m/px over {side:.0f} m")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda j: fetch(Z, j[0], j[1], cache), jobs))

    # mosaic
    W, H = len(xs) * 256, len(ys) * 256
    mosaic = np.zeros((H, W, 3), np.uint8)
    for x in xs:
        for y in ys:
            p = cache / f"{x}_{y}.jpg"
            if p.exists() and p.stat().st_size > 0:
                img = Image.open(io.BytesIO(p.read_bytes())).convert("RGB")
                mosaic[(y - ys[0]) * 256:(y - ys[0] + 1) * 256, (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = np.asarray(img)

    # resample into the world frame: output pixel (row, col) -> (e, n) -> lon/lat -> mosaic pixel
    to_ll = Transformer.from_crs("EPSG:4978", "EPSG:4326", always_xy=True)
    out = np.zeros((SIZE, SIZE, 3), np.uint8)
    cols = e0 + (np.arange(SIZE) + 0.5) * res
    for r0 in range(0, SIZE, 256):
        rows = n1 - (np.arange(r0, min(r0 + 256, SIZE)) + 0.5) * res
        E, N = np.meshgrid(cols, rows)
        ecef = frame.o + np.stack([E, N, np.zeros_like(E)], -1) @ frame.R    # R rows are E,N,U axes
        lon, lat, _ = to_ll.transform(ecef[..., 0], ecef[..., 1], ecef[..., 2])
        px, py = tile_xy(lon, lat, Z)
        px = (px - xs[0]) * 256 - 0.5
        py = (py - ys[0]) * 256 - 0.5
        x0 = np.clip(np.floor(px).astype(int), 0, W - 2)
        y0 = np.clip(np.floor(py).astype(int), 0, H - 2)
        fx = np.clip(px - x0, 0, 1)[..., None]
        fy = np.clip(py - y0, 0, 1)[..., None]
        # gather the 4 neighbours from the uint8 mosaic, convert only the gathered samples
        # (converting the whole mosaic per stripe cost GBs per 256 rows at z19/16k)
        g = lambda yy, xx: mosaic[yy, xx].astype(np.float32)
        top = g(y0, x0) * (1 - fx) + g(y0, x0 + 1) * fx
        bot = g(y0 + 1, x0) * (1 - fx) + g(y0 + 1, x0 + 1) * fx
        out[r0:r0 + len(rows)] = np.clip(top * (1 - fy) + bot * fy, 0, 255).astype(np.uint8)

    odir = ROOT / "data/processed" / region / "ortho"
    odir.mkdir(parents=True, exist_ok=True)
    stem = "ortho_ctx" if context else "ortho"
    Image.fromarray(out).save(odir / f"{stem}.jpg", quality=94)
    meta = {
        "source": "MassGIS 2023 orthoimagery (public domain), tile service z%d" % Z,
        "size_px": SIZE, "m_per_px": res,
        "east_min_m": e0, "north_max_m": n1, "side_m": side,
        # material mapping: u = (X_cm/100 - east_min) / side ; v = (-Y_cm/100 ... ) see README
        "ue_x0_cm": e0 * 100.0, "ue_y0_cm": -n1 * 100.0, "ue_side_cm": side * 100.0,
    }
    (odir / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "mit_core", context="--context" in sys.argv)
