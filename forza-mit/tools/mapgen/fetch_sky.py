"""Download the CC0 sky HDRI (Poly Haven, sky-only "puresky" edit) that replaces the volumetric clouds.

Usage:  uv run fetch_sky.py
Output: data/raw/sky/<id>_8k.hdr; then tools/blender/make_sky.py turns it into the sky dome texture.
"""
import json
from pathlib import Path

from fetch_textures import get

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/raw/sky"
ASSET = "rustig_koppie_puresky"   # deep blue sky, small clouds, sun at 28 deg: long afternoon shadows (Greg Zaal, CC0)
RES = "8k"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{ASSET}_{RES}.hdr"
    if not p.exists():
        files = json.loads(get(f"https://api.polyhaven.com/files/{ASSET}"))
        p.write_bytes(get(files["hdri"][RES]["hdr"]["url"]))
    print(f"{p} ({p.stat().st_size / 1e6:.0f} MB), CC0 (Poly Haven)")


if __name__ == "__main__":
    main()
