"""Download the CC0 PBR texture sets used by the world materials (Poly Haven, 2K JPG).

Usage:  uv run fetch_textures.py
Output: data/raw/textures/polyhaven/<id>/{diff,nor,arm}.jpg and textures.json
        (arm = packed AO / Roughness / Metal, nor = DirectX convention like Unreal)
textures.json records each set's real-world size in metres, which the materials use for tiling.
"""
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/raw/textures/polyhaven"
RES = "2k"

# surface -> Poly Haven asset id (all CC0)
SETS = {
    "road": "asphalt_02",
    "parking": "asphalt_04",
    "sidewalk": "concrete_pavement",
    "paved": "concrete_pavement_02",
    "grass": "leafy_grass",
    "curb": "granite_tile_03",
    "brick_red": "red_brick",
    "brick_buff": "brick_wall_07",
    "limestone": "marble_01",
    "concrete": "concrete_layers_02",
    "siding": "brown_planks_05",
    "sidewalk_brick": "brick_pavement_04",     # Cambridge's red-brick sidewalks
    # facades / roofs (round v2): grey ashlar for the MIT Indiana limestone and Harvard granite (marble_01 read
    # cream-yellow), photographed slate / shingle courses for the pitched roofs
    "ashlar": "stone_tile_wall",
    "slate": "roof_slates_02",
}
MAPS = {"diff": "Diffuse", "nor": "nor_dx", "arm": "arm"}
# brick sets that get a per-brick id in the ARM blue channel (metal, unused on brick): the facade shader tints
# every brick on its own and re-hashes the ids per texture tile, which also breaks up the 1.4 m tile repeat
BRICK_ID_SETS = {"brick_red"}
DERIVED = ROOT / "data/processed/common/textures"


def make_brick_ids(set_dir, out):
    """arm.jpg with B = brick id: bricks segmented from the photo (saturated clay vs grey mortar), one value per
    brick from its position (wrap-consistent across the tile edge), mortar = 0."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(Image.open(set_dir / "diff.jpg").convert("RGB"), float) / 255.0
    sat = (a.max(2) - a.min(2)) / np.maximum(a.max(2), 1e-3)
    mask = ndimage.binary_opening(sat > 0.30, iterations=2)
    h, w = mask.shape
    mos = np.tile(mask, (3, 3))
    lab, n = ndimage.label(mos)
    cen = ndimage.center_of_mass(mos, lab, range(1, n + 1))
    c = lab[h:2 * h, w:2 * w]
    val = np.zeros(n + 1)
    for i in np.unique(c)[1:]:
        cy, cx = cen[i - 1]
        k = (int(round(cy)) % h // 8, int(round(cx)) % w // 8)
        val[i] = 0.1 + 0.9 * (((k[0] * 73856093) ^ (k[1] * 19349663)) % 1000) / 999.0
    arm = np.asarray(Image.open(set_dir / "arm.jpg").convert("RGB")).copy()
    arm[..., 2] = (val[c] * 255).astype(np.uint8)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arm).save(out)
    return len(np.unique(c)) - 1


def get(url):
    req = Request(url, headers={"User-Agent": "forza-MIT student project (HTMAA)"})
    for attempt in range(4):
        try:
            return urlopen(req, timeout=60).read()
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(url)


def main():
    meta = {}
    for surface, asset in SETS.items():
        d = OUT / asset
        d.mkdir(parents=True, exist_ok=True)
        files = json.loads(get(f"https://api.polyhaven.com/files/{asset}"))
        info = json.loads(get(f"https://api.polyhaven.com/info/{asset}"))
        for short, key in MAPS.items():
            p = d / f"{short}.jpg"
            if not p.exists():
                p.write_bytes(get(files[key][RES]["jpg"]["url"]))
        dims = info.get("dimensions") or [2000.0, 2000.0]
        meta[surface] = {"asset": asset, "size_m": [round(dims[0] / 1000.0, 3), round(dims[1] / 1000.0, 3)],
                         "license": "CC0 (Poly Haven)", "dir": str(d.relative_to(ROOT))}
        if surface in BRICK_ID_SETS:
            out = DERIVED / f"{asset}_arm_id.png"
            nb = make_brick_ids(d, out)
            meta[surface]["arm_id"] = str(out.relative_to(ROOT))
            print(f"  {surface:11s} {nb} bricks -> {out.name}")
        print(f"  {surface:11s} {asset:22s} {meta[surface]['size_m']} m")
    (OUT / "textures.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
