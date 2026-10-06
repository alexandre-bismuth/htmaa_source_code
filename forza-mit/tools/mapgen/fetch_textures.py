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
}
MAPS = {"diff": "Diffuse", "nor": "nor_dx", "arm": "arm"}


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
        print(f"  {surface:11s} {asset:22s} {meta[surface]['size_m']} m")
    (OUT / "textures.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
