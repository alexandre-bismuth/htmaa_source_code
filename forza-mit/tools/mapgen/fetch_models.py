"""Download the CC0 Poly Haven models the game uses (glTF + textures) into data/raw/models/<id>/.

Usage:  uv run fetch_models.py
Uses the Poly Haven API (https://api.polyhaven.com/files/<id>): the glTF at the given resolution
plus every file it includes (bin, textures), keeping the relative paths the glTF expects.
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data/raw/models"
MODELS = {
    "jacaranda_tree": "2k",          # trees (tools/mapgen/props.py)
    "street_lamp_02": "2k",          # lanterns on the historic posts
    "fire_hydrant": "1k",            # street furniture
    "metal_trash_can": "1k",
    "painted_wooden_bench": "1k",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "forza-mit-pipeline"})) as r:
        return r.read()


def fetch(model, res):
    out = DEST / model
    files = json.loads(get(f"https://api.polyhaven.com/files/{model}"))
    entry = files["gltf"][res]["gltf"]
    gltf = out / f"{model}.gltf"
    if gltf.exists():
        print(f"{model}: cached")
        return
    out.mkdir(parents=True, exist_ok=True)
    for rel, inc in entry.get("include", {}).items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(get(inc["url"]))
    gltf.write_bytes(get(entry["url"]))   # keep the model's own relative paths
    print(f"{model}: {res}, {len(entry.get('include', {}))} files")


def main():
    for model, res in MODELS.items():
        if len(sys.argv) > 1 and model not in sys.argv[1:]:
            continue
        fetch(model, res)


if __name__ == "__main__":
    main()
