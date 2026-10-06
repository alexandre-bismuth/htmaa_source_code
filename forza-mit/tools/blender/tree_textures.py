"""Bark textures for the procedural street trees (tools/blender/build_trees.py).

Downloads CC0 bark sets (Poly Haven, ambientCG) at 2K and bakes two procedural birch barks
(no CC0 birch bark exists on either site). Idempotent: existing files are kept.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/tree_textures.py

Output layout (data/raw/textures/ is gitignored):
    polyhaven/<id>/{diff,nor,nor_gl,arm}.jpg      nor = DirectX (Unreal), arm = AO/Rough/Metal
    ambientcg/<id>/{diff,nor,nor_gl,rough}.jpg    nor = DirectX
    procedural/<id>/{diff,nor,nor_gl,rough}.png   birch_white, birch_river
Every set's metadata (paths, real-world size, roughness channel) is returned by bark_sets().
"""
import io
import json
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TEX = ROOT / "data/raw/textures"
RES = "2k"

# bark set id -> (source, real-world tile size in metres along u (around), v (along the branch))
BARKS = {
    "Bark001": ("ambientcg", 1.0, 1.0),          # grey, deep flat-topped ridges: oak
    "Bark004": ("ambientcg", 1.0, 1.0),          # grey interlacing ridges: elm
    "Bark009": ("ambientcg", 1.0, 1.0),          # cream/olive camouflage patches: London plane
    "bark_brown_02": ("polyhaven", 1.0, 1.0),    # dark plated ridges: honey locust
    "tree_bark_03": ("polyhaven", 1.0, 1.0),     # grey-brown fine furrows: maple
    "bark_willow": ("polyhaven", 1.0, 1.0),      # brown-grey interlaced furrows: linden
    "sakura_bark": ("polyhaven", 1.6, 1.6),      # cherry, horizontal lenticels: ornamental
    "bark_brown_01": ("polyhaven", 1.0, 1.0),    # grey-tan furrows: ginkgo
    "birch_white": ("procedural", 1.0, 1.0),
    "birch_river": ("procedural", 1.0, 1.0),
}


def get(url):
    req = Request(url, headers={"User-Agent": "forza-MIT student project (HTMAA)"})
    for attempt in range(4):
        try:
            return urlopen(req, timeout=120).read()
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(url)


def fetch_polyhaven(asset):
    d = TEX / "polyhaven" / asset
    want = {"diff": "Diffuse", "nor": "nor_dx", "nor_gl": "nor_gl", "arm": "arm"}
    if all((d / f"{k}.jpg").exists() for k in want):
        return d
    d.mkdir(parents=True, exist_ok=True)
    files = json.loads(get(f"https://api.polyhaven.com/files/{asset}"))
    for short, key in want.items():
        p = d / f"{short}.jpg"
        if not p.exists():
            p.write_bytes(get(files[key][RES]["jpg"]["url"]))
    return d


def fetch_ambientcg(asset):
    d = TEX / "ambientcg" / asset
    want = {"diff": "_Color", "nor": "_NormalDX", "nor_gl": "_NormalGL", "rough": "_Roughness"}
    if all((d / f"{k}.jpg").exists() for k in want):
        return d
    d.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(get(f"https://ambientcg.com/get?file={asset}_2K-JPG.zip")))
    for short, suffix in want.items():
        name = next(n for n in z.namelist() if n.endswith(f"{suffix}.jpg"))
        (d / f"{short}.jpg").write_bytes(z.read(name))
    return d


# ---------------------------------------------------------------- procedural birch bark
def tile_noise(rng, n, scale_u, scale_v, power=2.0):
    """Tileable fractal noise in [0,1] via spectral synthesis (anisotropic: scale_u across, scale_v along)."""
    fu = np.fft.fftfreq(n)[None, :] * scale_u
    fv = np.fft.fftfreq(n)[:, None] * scale_v
    f = np.sqrt(fu * fu + fv * fv)
    f[0, 0] = 1.0
    spec = (rng.normal(size=(n, n)) + 1j * rng.normal(size=(n, n))) / f ** power
    spec[0, 0] = 0
    x = np.real(np.fft.ifft2(spec))
    return (x - x.min()) / (x.max() - x.min())


def stamp_ellipses(rng, n, count, w_range, h_range, depth_range):
    """Horizontal dark dashes (lenticels), tileable. Returns a mask in [0,1]."""
    m = np.zeros((n, n), np.float32)
    for _ in range(count):
        cx, cy = rng.uniform(0, n), rng.uniform(0, n)
        w, h = rng.uniform(*w_range) * n, rng.uniform(*h_range) * n
        dep = rng.uniform(*depth_range)
        x0, x1 = int(cx - w), int(cx + w) + 1
        y0, y1 = int(cy - h), int(cy + h) + 1
        xs = np.arange(x0, x1)
        ys = np.arange(y0, y1)
        dx = (xs[None, :] - cx) / w
        dy = (ys[:, None] - cy) / h
        e = np.clip(1.0 - (dx * dx + dy * dy), 0, 1) ** 0.5 * dep
        m[np.ix_(ys % n, xs % n)] = np.maximum(m[np.ix_(ys % n, xs % n)], e)
    return m


def normal_from_height(h, strength):
    gy, gx = np.gradient(h)
    # wrap edges for tiling
    gx[:, 0] = (h[:, 1] - h[:, -1]) * 0.5
    gx[:, -1] = (h[:, 0] - h[:, -2]) * 0.5
    gy[0, :] = (h[1, :] - h[-1, :]) * 0.5
    gy[-1, :] = (h[0, :] - h[-2, :]) * 0.5
    nx, ny = -gx * strength, -gy * strength
    nz = np.ones_like(h)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    return nx / l, ny / l, nz / l


def save_png(path, rgb):
    import bpy
    n = rgb.shape[0]
    img = bpy.data.images.new(path.stem, n, n, alpha=False, float_buffer=False)
    rgba = np.ones((n, n, 4), np.float32)
    rgba[..., :3] = np.clip(rgb, 0, 1)
    # Blender images are bottom-up; our arrays are top-down (row 0 = v 1)
    img.pixels.foreach_set(rgba[::-1].ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def bake_birch(kind, n=1024):
    d = TEX / "procedural" / kind
    want = ["diff.png", "nor.png", "nor_gl.png", "rough.png"]
    if all((d / w).exists() for w in want):
        return d
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7 if kind == "birch_white" else 11)
    # rows = along the trunk (v), columns = around (u). Lenticels are horizontal = across u.
    fine = tile_noise(rng, n, 1.0, 0.25, 1.6)            # streaky along u (horizontal grain)
    mid = tile_noise(rng, n, 1.0, 1.0, 2.2)
    if kind == "birch_white":
        base = np.array([0.80, 0.79, 0.75])
        col = base[None, None, :] * (0.88 + 0.16 * fine[..., None]) * (0.92 + 0.1 * mid[..., None])
        # faint warm/peach where outer bark has peeled
        peel = np.clip((tile_noise(rng, n, 1.0, 0.35, 2.0) - 0.72) * 6, 0, 1)
        col = col * (1 - peel[..., None] * 0.35) + np.array([0.78, 0.60, 0.48]) * peel[..., None] * 0.35
        lent = stamp_ellipses(rng, n, 260, (0.006, 0.045), (0.0012, 0.0028), (0.35, 0.75))
        scars = stamp_ellipses(rng, n, 7, (0.04, 0.10), (0.006, 0.014), (0.7, 0.95))
        scars *= np.clip(tile_noise(rng, n, 1, 1, 1.5) * 1.6, 0, 1)
        dark = np.maximum(lent, scars)
        col = col * (1 - dark[..., None]) + np.array([0.16, 0.14, 0.13]) * dark[..., None]
        height = 0.5 * fine + 0.3 * mid - 0.9 * dark
        rough = 0.62 + 0.25 * dark - 0.08 * fine
    else:  # river birch: salmon / cinnamon papery curls, darker grey-brown where peeled through
        layers = tile_noise(rng, n, 4.0, 0.7, 1.7)        # horizontal sheets
        curls = np.clip((layers - 0.45) * 3.0, 0, 1)
        base = np.array([0.55, 0.38, 0.29])
        light = np.array([0.80, 0.66, 0.55])
        under = np.array([0.30, 0.25, 0.22])
        col = base * (0.85 + 0.25 * fine[..., None])
        col = col * (1 - curls[..., None]) + light * curls[..., None] * (0.9 + 0.2 * fine[..., None])
        holes = np.clip((tile_noise(rng, n, 2.5, 1.0, 1.8) - 0.62) * 5, 0, 1)
        col = col * (1 - holes[..., None]) + under * holes[..., None]
        lent = stamp_ellipses(rng, n, 500, (0.006, 0.03), (0.0015, 0.003), (0.4, 0.8))
        col = col * (1 - 0.6 * lent[..., None])
        height = 0.6 * curls + 0.3 * fine - 0.5 * holes - 0.5 * lent
        rough = 0.7 + 0.15 * holes - 0.1 * curls
    nx, ny, nz = normal_from_height(height, 6.0)
    # image rows go down = -v, so the GL green (+v) is -ny; DX flips green again.
    gl = np.stack([nx * 0.5 + 0.5, -ny * 0.5 + 0.5, nz * 0.5 + 0.5], -1)
    dx = gl.copy()
    dx[..., 1] = 1.0 - dx[..., 1]
    save_png(d / "diff.png", col ** 1.0)  # values above are already display (sRGB) colours
    save_png(d / "nor_gl.png", gl)
    save_png(d / "nor.png", dx)
    save_png(d / "rough.png", np.repeat(np.clip(rough, 0, 1)[..., None], 3, -1))
    return d


def bark_sets():
    """Fetch/bake everything; return {id: {diff, nor_dx, nor_gl, rough, rough_channel, size_m, source}}."""
    out = {}
    for asset, (src, su, sv) in BARKS.items():
        if src == "polyhaven":
            d = fetch_polyhaven(asset)
            rough, ch, ext = d / "arm.jpg", "G", "jpg"
        elif src == "ambientcg":
            d = fetch_ambientcg(asset)
            rough, ch, ext = d / "rough.jpg", "R", "jpg"
        else:
            d = bake_birch(asset)
            rough, ch, ext = d / "rough.png", "R", "png"
        out[asset] = {"source": src, "license": "CC0" if src != "procedural" else "generated (tree_textures.py)",
                      "diff": d / f"diff.{ext}", "nor_dx": d / f"nor.{ext}", "nor_gl": d / f"nor_gl.{ext}",
                      "rough": rough, "rough_channel": ch, "size_m": [su, sv]}
        print(f"  bark {asset:16s} {src}")
    return out


if __name__ == "__main__":
    bark_sets()
